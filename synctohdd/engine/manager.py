import asyncio
import threading
import uuid
from typing import Optional, List, Dict, Any, Set
from synctohdd.config import AppConfig, SyncPairConfig, load_config
from synctohdd.db.database import get_session_factory
from synctohdd.db import crud
from synctohdd.engine.base import BaseSyncBackend, SyncProgressEvent, SyncSummary
from synctohdd.engine.python_backend import PythonSyncBackend
from synctohdd.engine.rsync_backend import RsyncBackend
from synctohdd.utils.platform import is_linux, has_rsync
from synctohdd.utils.logger import logger

class SyncManager:
    """Singleton coordinator for scheduling, running, and broadcasting sync operations."""

    def __init__(self):
        self._lock = threading.Lock()
        self.is_running: bool = False
        self.is_batch_running: bool = False
        self.active_run_id: Optional[str] = None
        self.active_pair_id: Optional[str] = None
        self.active_pair_name: Optional[str] = None
        self._cancel_flag = threading.Event()
        self.latest_event: Optional[SyncProgressEvent] = None
        self._listeners: Set[asyncio.Queue] = set()
        self._backend: Optional[BaseSyncBackend] = None

    def get_preferred_backend(self) -> BaseSyncBackend:
        """Select rsync on Linux if available, otherwise pure Python backend."""
        if is_linux() and has_rsync():
            try:
                return RsyncBackend()
            except Exception as e:
                logger.warning(f"Failed to initialize RsyncBackend, falling back to Python backend: {e}")
        return PythonSyncBackend()

    def get_backend_name(self) -> str:
        if is_linux() and has_rsync():
            return "rsync"
        return "python"

    def subscribe(self) -> asyncio.Queue:
        """Subscribe an SSE client queue for real-time progress events."""
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._listeners.add(q)
        # Push latest event immediately if active
        if self.latest_event:
            try:
                q.put_nowait(self.latest_event)
            except Exception:
                pass
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Unsubscribe an SSE client queue."""
        self._listeners.discard(q)

    def _broadcast_event(self, event: SyncProgressEvent) -> None:
        """Dispatch event to all active listener queues."""
        self.latest_event = event
        dead_queues = []
        for q in self._listeners:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass
            except Exception:
                dead_queues.append(q)
        for dq in dead_queues:
            self._listeners.discard(dq)

    def cancel_current_sync(self) -> bool:
        """Signal cancellation for currently running sync or batch."""
        with self._lock:
            if not self.is_running and not self.is_batch_running:
                return False
            self._cancel_flag.set()
            logger.info(f"Cancellation requested for run {self.active_run_id} (batch={self.is_batch_running})")
            return True

    def get_status(self) -> Dict[str, Any]:
        """Return current status dictionary for API and UI."""
        with self._lock:
            return {
                "is_running": self.is_running or self.is_batch_running,
                "is_batch_running": self.is_batch_running,
                "active_run_id": self.active_run_id,
                "active_pair_id": self.active_pair_id,
                "active_pair_name": self.active_pair_name,
                "backend": self.get_backend_name(),
                "latest_event": self.latest_event.__dict__ if self.latest_event else None,
            }

    async def start_sync_job(
        self,
        pair: SyncPairConfig,
        dry_run: bool = False,
        config: Optional[AppConfig] = None,
        from_batch: bool = False,
    ) -> str:
        """Initiate a sync job for a single pair."""
        with self._lock:
            if self.is_running or (self.is_batch_running and not from_batch):
                raise RuntimeError(f"A sync is already in progress: {self.active_pair_name or 'Batch'} ({self.active_run_id})")

            run_id = str(uuid.uuid4())
            self.is_running = True
            self.active_run_id = run_id
            self.active_pair_id = pair.id
            self.active_pair_name = pair.name
            self._cancel_flag.clear()
            self.latest_event = None

        # Create record in database
        session_factory = get_session_factory()
        async with session_factory() as session:
            await crud.create_sync_run(
                session=session,
                run_id=run_id,
                sync_pair_id=pair.id,
                sync_pair_name=pair.name,
                source=pair.source,
                destination=pair.destination,
                dry_run=dry_run,
            )

        # Launch background worker task
        asyncio.create_task(self._execute_sync_task(pair, run_id, dry_run))
        return run_id

    async def start_sync_all_jobs(self, dry_run: bool = False) -> List[str]:
        """Queue and run sync for all configured pairs sequentially."""
        cfg = load_config()
        if not cfg.sync_pairs:
            raise ValueError("No sync pairs configured")

        with self._lock:
            if self.is_running or self.is_batch_running:
                raise RuntimeError("A sync is already in progress")
            self._cancel_flag.clear()
            self.is_batch_running = True

        # Launch background sequence runner
        asyncio.create_task(self._execute_all_sequence(cfg.sync_pairs, dry_run))
        return [p.id for p in cfg.sync_pairs]

    async def _execute_all_sequence(self, pairs: List[SyncPairConfig], dry_run: bool) -> None:
        """Run multiple pairs in sequence."""
        try:
            for pair in pairs:
                if self._cancel_flag.is_set():
                    logger.info("Batch sync aborted due to cancellation flag")
                    break
                try:
                    run_id = await self.start_sync_job(pair, dry_run=dry_run, from_batch=True)
                    # Wait until active job completes
                    while self.is_running and self.active_run_id == run_id:
                        await asyncio.sleep(0.5)
                except Exception as e:
                    logger.error(f"Error in batch sequence for pair {pair.name}: {e}")
        finally:
            with self._lock:
                self.is_batch_running = False

    async def _execute_sync_task(
        self,
        pair: SyncPairConfig,
        run_id: str,
        dry_run: bool,
    ) -> None:
        """Worker executing sync logic in a worker thread and persisting results."""
        backend = self.get_preferred_backend()
        loop = asyncio.get_running_loop()

        def progress_cb(evt: SyncProgressEvent):
            # Dispatch event to asyncio event loop
            loop.call_soon_threadsafe(self._broadcast_event, evt)

        def cancel_check() -> bool:
            return self._cancel_flag.is_set()

        try:
            # Run backend in thread pool executor so it doesn't block async loop
            summary: SyncSummary = await loop.run_in_executor(
                None,
                backend.run_sync,
                pair,
                run_id,
                dry_run,
                progress_cb,
                cancel_check,
            )
        except Exception as e:
            logger.exception("Unexpected exception in sync worker")
            summary = SyncSummary(
                run_id=run_id,
                status="failed",
                error_log=f"Internal error: {e}",
            )

        # Update database with final summary and changes
        session_factory = get_session_factory()
        async with session_factory() as session:
            await crud.finish_sync_run(
                session=session,
                run_id=run_id,
                status=summary.status,
                error_log=summary.error_log,
                files_added=summary.files_added,
                files_modified=summary.files_modified,
                files_deleted=summary.files_deleted,
                files_unchanged=summary.files_unchanged,
                bytes_transferred=summary.bytes_transferred,
            )

            # Insert file changes in chunks
            if summary.changes:
                batch_size = 500
                for i in range(0, len(summary.changes), batch_size):
                    chunk = [
                        {
                            "action": c.action,
                            "file_path": c.rel_path,
                            "file_size": c.size,
                            "source_mtime": c.source_mtime,
                            "error": c.error,
                        }
                        for c in summary.changes[i : i + batch_size]
                    ]
                    await crud.add_file_changes_batch(session, run_id, chunk)

        # Mark manager as idle
        with self._lock:
            self.is_running = False
            self.active_run_id = None
            self.active_pair_id = None
            self.active_pair_name = None

        # Final broadcast
        final_event = SyncProgressEvent(
            run_id=run_id,
            pair_id=pair.id,
            pair_name=pair.name,
            status=summary.status,
            percent=100.0,
            files_added=summary.files_added,
            files_modified=summary.files_modified,
            files_deleted=summary.files_deleted,
            files_unchanged=summary.files_unchanged,
            bytes_transferred=summary.bytes_transferred,
            message=summary.error_log or f"Sync {summary.status}",
        )
        self._broadcast_event(final_event)

sync_manager = SyncManager()
