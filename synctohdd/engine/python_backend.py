import os
import shutil
import time
from pathlib import Path
from typing import Optional, Callable, List
from synctohdd.config import SyncPairConfig
from synctohdd.engine.base import BaseSyncBackend, SyncSummary, SyncProgressEvent, FileDiff, ProgressCallback
from synctohdd.engine.comparator import scan_directory, compare_file_trees
from synctohdd.utils.logger import logger

def parse_bandwidth_limit(limit_str: Optional[str]) -> Optional[int]:
    """Parse bandwidth limit string like '50M', '500K' to bytes/sec."""
    if not limit_str:
        return None
    s = limit_str.strip().upper()
    try:
        if s.endswith("G"):
            return int(float(s[:-1]) * 1024 * 1024 * 1024)
        if s.endswith("M"):
            return int(float(s[:-1]) * 1024 * 1024)
        if s.endswith("K"):
            return int(float(s[:-1]) * 1024)
        return int(float(s))
    except ValueError:
        return None

def copy_file_chunked(
    src_file: Path,
    dst_file: Path,
    chunk_size: int = 128 * 1024,
    bandwidth_limit_bps: Optional[int] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_cb: Optional[Callable[[int], None]] = None,
) -> int:
    """Copy a file with atomic rename and optional bandwidth throttling."""
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    temp_dst = dst_file.with_name(f".{dst_file.name}.synctmp")
    bytes_copied = 0

    try:
        with open(src_file, "rb") as fsrc, open(temp_dst, "wb") as fdst:
            while True:
                if cancel_check and cancel_check():
                    raise InterruptedError("Cancelled during file copy")
                start_time = time.time()
                buf = fsrc.read(chunk_size)
                if not buf:
                    break
                fdst.write(buf)
                n = len(buf)
                bytes_copied += n
                if progress_cb:
                    progress_cb(n)

                if bandwidth_limit_bps and bandwidth_limit_bps > 0:
                    elapsed = time.time() - start_time
                    expected_time = n / bandwidth_limit_bps
                    if expected_time > elapsed:
                        time.sleep(expected_time - elapsed)

        # Preserve permissions and timestamps
        shutil.copystat(src_file, temp_dst)
        # Atomic rename
        temp_dst.replace(dst_file)
        return bytes_copied
    except Exception:
        if temp_dst.exists():
            try:
                temp_dst.unlink()
            except Exception:
                pass
        raise

class PythonSyncBackend(BaseSyncBackend):
    """Pure-Python file synchronization engine with cross-platform support."""

    def run_sync(
        self,
        pair: SyncPairConfig,
        run_id: str,
        dry_run: bool = False,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> SyncSummary:
        src_root = Path(pair.source).resolve()
        dst_root = Path(pair.destination).resolve()

        if not src_root.exists():
            err_msg = f"Source directory does not exist: {src_root}"
            logger.error(err_msg)
            return SyncSummary(run_id=run_id, status="failed", error_log=err_msg)

        # 1. Scanning
        if progress_cb:
            progress_cb(
                SyncProgressEvent(
                    run_id=run_id,
                    pair_id=pair.id,
                    pair_name=pair.name,
                    status="scanning",
                    message="Scanning source and destination directories...",
                )
            )

        try:
            src_items = scan_directory(src_root, pair.exclude, cancel_check=cancel_check)
            dst_items = scan_directory(dst_root, pair.exclude, cancel_check=cancel_check) if dst_root.exists() else {}

            added, modified, deleted, unchanged = compare_file_trees(
                src_items=src_items,
                dst_items=dst_items,
                src_base=src_root,
                dst_base=dst_root,
                checksum=pair.checksum,
                mode=pair.mode,
                cancel_check=cancel_check,
            )
        except InterruptedError:
            return SyncSummary(run_id=run_id, status="cancelled", error_log="Sync cancelled by user during scan")
        except Exception as e:
            logger.exception("Error during directory comparison")
            return SyncSummary(run_id=run_id, status="failed", error_log=str(e))

        all_changes: List[FileDiff] = []
        all_changes.extend(added)
        all_changes.extend(modified)
        all_changes.extend(deleted)
        all_changes.extend(unchanged)

        to_copy = added + modified
        total_files_to_sync = len(to_copy) + (len(deleted) if pair.mode == "mirror" else 0)
        total_bytes_to_transfer = sum(f.size or 0 for f in to_copy)

        files_added_count = 0
        files_modified_count = 0
        files_deleted_count = 0
        bytes_transferred_total = 0
        files_processed_count = 0

        bw_limit = parse_bandwidth_limit(pair.bandwidth_limit)

        if dry_run:
            logger.info(f"Dry run completed for pair '{pair.name}'. Changes found: +{len(added)}, ~{len(modified)}, -{len(deleted)}")
            if progress_cb:
                progress_cb(
                    SyncProgressEvent(
                        run_id=run_id,
                        pair_id=pair.id,
                        pair_name=pair.name,
                        status="completed",
                        percent=100.0,
                        files_added=len(added),
                        files_modified=len(modified),
                        files_deleted=len(deleted),
                        files_unchanged=len(unchanged),
                        bytes_transferred=total_bytes_to_transfer,
                        message=f"Dry run complete. Found {len(added)} added, {len(modified)} modified, {len(deleted)} deleted.",
                    )
                )
            return SyncSummary(
                run_id=run_id,
                status="completed",
                files_added=len(added),
                files_modified=len(modified),
                files_deleted=len(deleted),
                files_unchanged=len(unchanged),
                bytes_transferred=total_bytes_to_transfer,
                changes=all_changes,
            )

        # 2. Execution
        try:
            dst_root.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return SyncSummary(
                run_id=run_id,
                status="failed",
                error_log=f"Failed to create destination folder {dst_root}: {e}",
            )

        # Copy added and modified files
        for item in to_copy:
            if cancel_check and cancel_check():
                return SyncSummary(
                    run_id=run_id,
                    status="cancelled",
                    files_added=files_added_count,
                    files_modified=files_modified_count,
                    files_deleted=files_deleted_count,
                    files_unchanged=len(unchanged),
                    bytes_transferred=bytes_transferred_total,
                    changes=all_changes,
                    error_log="Sync cancelled by user",
                )

            src_file = src_root / item.rel_path
            dst_file = dst_root / item.rel_path

            if progress_cb:
                pct = (
                    (bytes_transferred_total / total_bytes_to_transfer * 100.0)
                    if total_bytes_to_transfer > 0
                    else 0.0
                )
                progress_cb(
                    SyncProgressEvent(
                        run_id=run_id,
                        pair_id=pair.id,
                        pair_name=pair.name,
                        status="syncing",
                        current_file=item.rel_path,
                        current_action=item.action,
                        files_processed=files_processed_count,
                        total_files_to_sync=total_files_to_sync,
                        bytes_transferred=bytes_transferred_total,
                        total_bytes_to_transfer=total_bytes_to_transfer,
                        percent=round(pct, 1),
                        files_added=files_added_count,
                        files_modified=files_modified_count,
                        files_deleted=files_deleted_count,
                        files_unchanged=len(unchanged),
                        message=f"{item.action.capitalize()} {item.rel_path}",
                    )
                )

            try:
                copied = copy_file_chunked(
                    src_file=src_file,
                    dst_file=dst_file,
                    bandwidth_limit_bps=bw_limit,
                    cancel_check=cancel_check,
                )
                bytes_transferred_total += copied
                if item.action == "added":
                    files_added_count += 1
                else:
                    files_modified_count += 1
            except InterruptedError:
                return SyncSummary(
                    run_id=run_id,
                    status="cancelled",
                    files_added=files_added_count,
                    files_modified=files_modified_count,
                    files_deleted=files_deleted_count,
                    files_unchanged=len(unchanged),
                    bytes_transferred=bytes_transferred_total,
                    changes=all_changes,
                    error_log="Cancelled during transfer",
                )
            except Exception as e:
                item.error = str(e)
                logger.warning(f"Failed to copy {item.rel_path}: {e}")

            files_processed_count += 1

        # Delete files if in mirror mode
        if pair.mode == "mirror":
            for item in deleted:
                if cancel_check and cancel_check():
                    return SyncSummary(
                        run_id=run_id,
                        status="cancelled",
                        files_added=files_added_count,
                        files_modified=files_modified_count,
                        files_deleted=files_deleted_count,
                        files_unchanged=len(unchanged),
                        bytes_transferred=bytes_transferred_total,
                        changes=all_changes,
                        error_log="Cancelled during deletion",
                    )

                dst_file = dst_root / item.rel_path
                if progress_cb:
                    progress_cb(
                        SyncProgressEvent(
                            run_id=run_id,
                            pair_id=pair.id,
                            pair_name=pair.name,
                            status="syncing",
                            current_file=item.rel_path,
                            current_action="deleted",
                            files_processed=files_processed_count,
                            total_files_to_sync=total_files_to_sync,
                            bytes_transferred=bytes_transferred_total,
                            total_bytes_to_transfer=total_bytes_to_transfer,
                            percent=100.0 if total_bytes_to_transfer == 0 else round(bytes_transferred_total / total_bytes_to_transfer * 100.0, 1),
                            files_added=files_added_count,
                            files_modified=files_modified_count,
                            files_deleted=files_deleted_count,
                            files_unchanged=len(unchanged),
                            message=f"Deleting {item.rel_path}",
                        )
                    )

                try:
                    if dst_file.exists():
                        dst_file.unlink()
                        files_deleted_count += 1
                except Exception as e:
                    item.error = str(e)
                    logger.warning(f"Failed to delete {item.rel_path}: {e}")

                files_processed_count += 1

            # Clean empty directories left over in destination
            for root, dirs, _ in os.walk(dst_root, topdown=False):
                for d in dirs:
                    d_path = Path(root) / d
                    try:
                        if d_path.exists() and not any(d_path.iterdir()):
                            d_path.rmdir()
                    except Exception:
                        pass

        # Complete
        if progress_cb:
            progress_cb(
                SyncProgressEvent(
                    run_id=run_id,
                    pair_id=pair.id,
                    pair_name=pair.name,
                    status="completed",
                    percent=100.0,
                    files_processed=total_files_to_sync,
                    total_files_to_sync=total_files_to_sync,
                    bytes_transferred=bytes_transferred_total,
                    total_bytes_to_transfer=total_bytes_to_transfer,
                    files_added=files_added_count,
                    files_modified=files_modified_count,
                    files_deleted=files_deleted_count,
                    files_unchanged=len(unchanged),
                    message=f"Sync completed successfully. +{files_added_count}, ~{files_modified_count}, -{files_deleted_count}",
                )
            )

        return SyncSummary(
            run_id=run_id,
            status="completed",
            files_added=files_added_count,
            files_modified=files_modified_count,
            files_deleted=files_deleted_count,
            files_unchanged=len(unchanged),
            bytes_transferred=bytes_transferred_total,
            changes=all_changes,
        )
