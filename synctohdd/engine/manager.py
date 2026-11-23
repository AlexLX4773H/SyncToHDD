import asyncio
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Set
from synctohdd.config import AppConfig, SyncPairConfig, load_config
from synctohdd.db.database import get_session_factory
from synctohdd.db import crud
from synctohdd.engine.base import BaseSyncBackend, SyncProgressEvent, SyncSummary
from synctohdd.engine.python_backend import PythonSyncBackend
from synctohdd.engine.rsync_backend import RsyncBackend
from synctohdd.utils.platform import is_linux, has_rsync
from synctohdd.utils.logger import logger

@dataclass
class QueuedSyncJob:
    """Represents a sync job waiting in the execution queue."""
    job_id: str
    pair_id: str
    pair_name: str
    source: str
    destination: str
    dry_run: bool
    enqueued_at: datetime
    pair_config: Optional[SyncPairConfig] = None

class SyncManager:
    """Singleton coordinator for scheduling, running, and broadcasting sync operations."""

    def __init__(self):
        self._lock = threading.RLock()
        self.is_running: bool = False
        self.is_batch_running: bool = False
        self.active_run_id: Optional[str] = None
        self.active_pair_id: Optional[str] = None
        self.active_pair_name: Optional[str] = None
        self._cancel_flag = threading.Event()
        self.latest_event: Optional[SyncProgressEvent] = None
        self._listeners: Set[asyncio.Queue] = set()
        self._backend: Optional[BaseSyncBackend] = None
        self._queue: List[QueuedSyncJob] = []

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
        event.queue_length = len(self._queue)
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

    def _broadcast_status(self) -> None:
        """Dispatch current engine and queue status to all active SSE listener queues."""
        status_payload = {"type": "status", "data": self.get_status()}
        dead_queues = []
        for q in self._listeners:
            try:
                q.put_nowait(status_payload)
            except asyncio.QueueFull:
                pass
            except Exception:
                dead_queues.append(q)
        for dq in dead_queues:
            self._listeners.discard(dq)

    def cancel_current_sync(self, clear_queue: bool = True) -> bool:
        """Signal cancellation for currently running sync, optionally clearing queued jobs."""
        with self._lock:
            if clear_queue:
                self._queue.clear()
                self.is_batch_running = False

            if not self.is_running and not self.is_batch_running and not self._queue:
                return False
            self._cancel_flag.set()
            logger.info(f"Cancellation requested for run {self.active_run_id} (batch={self.is_batch_running}, clear_queue={clear_queue})")

        self._broadcast_status()
        return True

    def get_status(self) -> Dict[str, Any]:
        """Return current status dictionary for API and UI."""
        with self._lock:
            queue_items = [
                {
                    "job_id": job.job_id,
                    "pair_id": job.pair_id,
                    "pair_name": job.pair_name,
                    "source": job.source,
                    "destination": job.destination,
                    "dry_run": job.dry_run,
                    "enqueued_at": job.enqueued_at.isoformat(),
                    "position": idx + 1,
                }
                for idx, job in enumerate(self._queue)
            ]
            return {
                "is_running": self.is_running or self.is_batch_running or bool(self._queue),
                "is_batch_running": self.is_batch_running or bool(self._queue),
                "active_run_id": self.active_run_id,
                "active_pair_id": self.active_pair_id,
                "active_pair_name": self.active_pair_name,
                "backend": self.get_backend_name(),
                "queue": queue_items,
                "queue_length": len(self._queue),
                "latest_event": self.latest_event.__dict__ if self.latest_event else None,
            }

    def enqueue_job(self, pair: SyncPairConfig, dry_run: bool = False) -> QueuedSyncJob:
        """Add a sync job to the execution queue."""
        with self._lock:
            for idx, existing in enumerate(self._queue):
                if existing.pair_id == pair.id and existing.dry_run == dry_run:
                    raise ValueError(f"Sync pair '{pair.name}' is already queued at position {idx + 1}")

            job = QueuedSyncJob(
                job_id=str(uuid.uuid4()),
                pair_id=pair.id,
                pair_name=pair.name,
                source=pair.source,
                destination=pair.destination,
                dry_run=dry_run,
                enqueued_at=datetime.now(timezone.utc),
                pair_config=pair,
            )
            self._queue.append(job)
            self.is_batch_running = True

        self._broadcast_status()
        logger.info(f"Sync job for '{pair.name}' enqueued at position {len(self._queue)} (job_id={job.job_id})")
        return job

    def enqueue_sync_all(self, dry_run: bool = False, config: Optional[AppConfig] = None) -> List[QueuedSyncJob]:
        """Add all configured sync pairs to queue (avoiding duplicates)."""
        cfg = config or load_config()
        if not cfg.sync_pairs:
            raise ValueError("No sync pairs configured")

        added_jobs: List[QueuedSyncJob] = []
        with self._lock:
            queued_keys = {(j.pair_id, j.dry_run) for j in self._queue}
            for pair in cfg.sync_pairs:
                if self.is_running and self.active_pair_id == pair.id:
                    continue
                if (pair.id, dry_run) in queued_keys:
                    continue

                job = QueuedSyncJob(
                    job_id=str(uuid.uuid4()),
                    pair_id=pair.id,
                    pair_name=pair.name,
                    source=pair.source,
                    destination=pair.destination,
                    dry_run=dry_run,
                    enqueued_at=datetime.now(timezone.utc),
                    pair_config=pair,
                )
                self._queue.append(job)
                queued_keys.add((pair.id, dry_run))
                added_jobs.append(job)

            if added_jobs:
                self.is_batch_running = True

        self._broadcast_status()
        return added_jobs

    def remove_from_queue(self, job_id: str) -> Optional[QueuedSyncJob]:
        """Remove a specific job from queue by job_id."""
        removed: Optional[QueuedSyncJob] = None
        with self._lock:
            for idx, job in enumerate(self._queue):
                if job.job_id == job_id:
                    removed = self._queue.pop(idx)
                    break
            if not self._queue:
                self.is_batch_running = False

        if removed:
            self._broadcast_status()
            logger.info(f"Removed job '{job_id}' ({removed.pair_name}) from sync queue")
        return removed

    def clear_queue(self) -> int:
        """Clear all pending sync jobs from the queue."""
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            self.is_batch_running = False

        self._broadcast_status()
        logger.info(f"Cleared {count} job(s) from sync queue")
        return count

    def get_queue(self) -> List[Dict[str, Any]]:
        """Return list of currently queued sync jobs with order positions."""
        with self._lock:
            return [
                {
                    "job_id": job.job_id,
                    "pair_id": job.pair_id,
                    "pair_name": job.pair_name,
                    "source": job.source,
                    "destination": job.destination,
                    "dry_run": job.dry_run,
                    "enqueued_at": job.enqueued_at.isoformat(),
                    "position": idx + 1,
                }
                for idx, job in enumerate(self._queue)
            ]

    def get_job_position(self, job_id: str) -> int:
        """Return 1-based queue position of a job_id, or 0 if not found."""
        with self._lock:
            for idx, job in enumerate(self._queue):
                if job.job_id == job_id:
                    return idx + 1
            return 0

    async def request_sync_job(
        self,
        pair: SyncPairConfig,
        dry_run: bool = False,
        queue: bool = False,
        config: Optional[AppConfig] = None,
    ) -> Dict[str, Any]:
        """Request a sync job. If already running and queue=True, enqueue the job; otherwise raise."""
        with self._lock:
            is_busy = self.is_running

        if is_busy:
            if not queue:
                raise RuntimeError(f"A sync is already in progress: {self.active_pair_name or 'Active Sync'} ({self.active_run_id})")
            job = self.enqueue_job(pair, dry_run=dry_run)
            pos = self.get_job_position(job.job_id)
            return {
                "status": "queued",
                "job_id": job.job_id,
                "pair_id": pair.id,
                "pair_name": pair.name,
                "dry_run": dry_run,
                "queue_position": pos,
                "message": f"Sync job for '{pair.name}' added to queue at position {pos}",
            }
        else:
            run_id = await self.start_sync_job(pair, dry_run=dry_run, config=config)
            return {
                "status": "started",
                "run_id": run_id,
                "pair_id": pair.id,
                "pair_name": pair.name,
                "dry_run": dry_run,
                "message": f"Sync started for '{pair.name}'",
            }

    async def start_sync_job(
        self,
        pair: SyncPairConfig,
        dry_run: bool = False,
        config: Optional[AppConfig] = None,
        from_batch: bool = False,
        from_queue: bool = False,
    ) -> str:
        """Initiate a sync job for a single pair immediately."""
        with self._lock:
            if self.is_running:
                raise RuntimeError(f"A sync is already in progress: {self.active_pair_name or 'Batch'} ({self.active_run_id})")
            if self.is_batch_running and not from_batch and not from_queue:
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

    async def start_sync_all_jobs(self, dry_run: bool = False, queue: bool = False) -> Dict[str, Any]:
        """Queue and run sync for all configured pairs sequentially (never parallel)."""
        cfg = load_config()
        if not cfg.sync_pairs:
            raise ValueError("No sync pairs configured")

        with self._lock:
            is_busy = self.is_running

        if is_busy:
            if not queue:
                raise RuntimeError(f"A sync is already in progress: {self.active_pair_name or 'Active Sync'} ({self.active_run_id})")
            queued_jobs = self.enqueue_sync_all(dry_run=dry_run, config=cfg)
            return {
                "status": "queued",
                "queued_pairs": [j.pair_id for j in queued_jobs],
                "queue_length": len(self.get_queue()),
                "dry_run": dry_run,
                "message": f"Queued {len(queued_jobs)} sync pair(s) to run sequentially",
            }
        else:
            pairs = cfg.sync_pairs
            first_pair = pairs[0]

            with self._lock:
                self._cancel_flag.clear()
                self.is_batch_running = True
                for p in pairs[1:]:
                    job = QueuedSyncJob(
                        job_id=str(uuid.uuid4()),
                        pair_id=p.id,
                        pair_name=p.name,
                        source=p.source,
                        destination=p.destination,
                        dry_run=dry_run,
                        enqueued_at=datetime.now(timezone.utc),
                        pair_config=p,
                    )
                    self._queue.append(job)

            run_id = await self.start_sync_job(first_pair, dry_run=dry_run, from_batch=True)
            self._broadcast_status()
            return {
                "status": "started",
                "run_id": run_id,
                "queued_pairs": [p.id for p in pairs],
                "dry_run": dry_run,
                "message": f"Started sequence with '{first_pair.name}', {len(pairs) - 1} remaining pairs queued",
            }

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
            queue_length=len(self._queue),
        )
        self._broadcast_event(final_event)

        # Process next queued job sequentially
        await self._process_next_in_queue()

    async def _process_next_in_queue(self) -> None:
        """Pick the next queued sync job and start it, ensuring strictly sequential execution."""
        next_job: Optional[QueuedSyncJob] = None
        should_broadcast_empty = False
        with self._lock:
            if self.is_running:
                # Do not start next job if a job is already executing
                return
            if not self._queue:
                self.is_batch_running = False
                should_broadcast_empty = True
            else:
                next_job = self._queue.pop(0)

        if should_broadcast_empty:
            self._broadcast_status()
            return

        cfg = load_config()
        pair = cfg.get_pair_by_id(next_job.pair_id) or next_job.pair_config
        if not pair:
            logger.warning(f"Queued pair '{next_job.pair_id}' no longer found in configuration, skipping.")
            await self._process_next_in_queue()
            return

        try:
            self._cancel_flag.clear()
            logger.info(f"Auto-starting next queued sync job for: {pair.name} (dry_run={next_job.dry_run})")
            await self.start_sync_job(pair, dry_run=next_job.dry_run, config=cfg, from_queue=True)
            self._broadcast_status()
        except Exception as e:
            logger.error(f"Failed to start queued sync job for pair {pair.name}: {e}")
            await self._process_next_in_queue()

sync_manager = SyncManager()
