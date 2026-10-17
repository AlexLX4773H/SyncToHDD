import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Callable, List
from synctohdd.config import SyncPairConfig
from synctohdd.engine.base import BaseSyncBackend, SyncSummary, SyncProgressEvent, FileDiff, ProgressCallback
from synctohdd.utils.logger import logger

def parse_rsync_bwlimit(bw_str: Optional[str]) -> Optional[str]:
    """Format bandwidth string for rsync --bwlimit in KBytes/sec."""
    if not bw_str:
        return None
    s = bw_str.strip().upper()
    try:
        if s.endswith("G"):
            return str(int(float(s[:-1]) * 1024 * 1024))
        if s.endswith("M"):
            return str(int(float(s[:-1]) * 1024))
        if s.endswith("K"):
            return str(int(float(s[:-1])))
        return str(int(float(s) / 1024))
    except Exception:
        return None

class RsyncBackend(BaseSyncBackend):
    """rsync-based synchronization backend for Linux and Unix-like environments."""

    def __init__(self):
        self.rsync_bin = shutil.which("rsync")
        if not self.rsync_bin:
            raise RuntimeError("rsync executable not found on system")

    def run_sync(
        self,
        pair: SyncPairConfig,
        run_id: str,
        dry_run: bool = False,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> SyncSummary:
        src = str(Path(pair.source).resolve()).rstrip("/\\") + "/"
        dst = str(Path(pair.destination).resolve()).rstrip("/\\") + "/"

        cmd = [
            self.rsync_bin,
            "-a",
            "--itemize-changes",
            "--stats",
            "--info=progress2",
        ]

        if dry_run:
            cmd.append("--dry-run")
        if pair.mode == "mirror":
            cmd.append("--delete")
        if pair.checksum:
            cmd.append("--checksum")
        if pair.bandwidth_limit:
            bw = parse_rsync_bwlimit(pair.bandwidth_limit)
            if bw:
                cmd.append(f"--bwlimit={bw}")

        for exc in pair.exclude:
            cmd.extend(["--exclude", exc])

        cmd.extend([src, dst])

        logger.info(f"Running rsync command: {' '.join(cmd)}")

        if progress_cb:
            progress_cb(
                SyncProgressEvent(
                    run_id=run_id,
                    pair_id=pair.id,
                    pair_name=pair.name,
                    status="syncing",
                    message="Starting rsync...",
                )
            )

        changes: List[FileDiff] = []
        files_added = 0
        files_modified = 0
        files_deleted = 0
        bytes_transferred = 0
        error_output: List[str] = []

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            progress_pattern = re.compile(r"(\d+)%\s+([0-9.]+[kKMGT]?B/s)")
            bytes_pattern = re.compile(r"Total transferred file size:\s+([0-9,]+)")

            while proc.poll() is None:
                if cancel_check and cancel_check():
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                    return SyncSummary(
                        run_id=run_id,
                        status="cancelled",
                        changes=changes,
                        error_log="rsync cancelled by user",
                    )

                line = proc.stdout.readline() if proc.stdout else ""
                if not line:
                    continue

                line = line.strip()

                # Parse progress2 output
                prog_match = progress_pattern.search(line)
                if prog_match:
                    pct = float(prog_match.group(1))
                    speed = prog_match.group(2)
                    if progress_cb:
                        progress_cb(
                            SyncProgressEvent(
                                run_id=run_id,
                                pair_id=pair.id,
                                pair_name=pair.name,
                                status="syncing",
                                percent=pct,
                                message=f"Syncing at {speed} ({pct}%)",
                            )
                        )
                    continue

                # Parse itemize-changes output
                if line.startswith("*deleting"):
                    rel_p = line.replace("*deleting", "").strip()
                    files_deleted += 1
                    changes.append(FileDiff(action="deleted", rel_path=rel_p))
                elif len(line) > 11 and line[0] in [">", "c", "h", "."]:
                    item_type = line[1]
                    code = line[:11]
                    rel_p = line[12:].strip()
                    if item_type == "f":  # file
                        if "++++++" in code or code.startswith(">f+++++++++"):
                            files_added += 1
                            changes.append(FileDiff(action="added", rel_path=rel_p))
                        else:
                            files_modified += 1
                            changes.append(FileDiff(action="modified", rel_path=rel_p))

            # Read remaining output
            rest_stdout, stderr = proc.communicate()
            if rest_stdout:
                for line in rest_stdout.splitlines():
                    b_match = bytes_pattern.search(line)
                    if b_match:
                        raw = b_match.group(1).replace(",", "")
                        bytes_transferred = int(raw)

            if proc.returncode != 0:
                err_text = stderr.strip() if stderr else f"rsync exited with code {proc.returncode}"
                return SyncSummary(
                    run_id=run_id,
                    status="failed",
                    files_added=files_added,
                    files_modified=files_modified,
                    files_deleted=files_deleted,
                    bytes_transferred=bytes_transferred,
                    changes=changes,
                    error_log=err_text,
                )

        except Exception as e:
            return SyncSummary(
                run_id=run_id,
                status="failed",
                error_log=str(e),
            )

        if progress_cb:
            progress_cb(
                SyncProgressEvent(
                    run_id=run_id,
                    pair_id=pair.id,
                    pair_name=pair.name,
                    status="completed",
                    percent=100.0,
                    files_added=files_added,
                    files_modified=files_modified,
                    files_deleted=files_deleted,
                    bytes_transferred=bytes_transferred,
                    message=f"Sync completed. +{files_added}, ~{files_modified}, -{files_deleted}",
                )
            )

        return SyncSummary(
            run_id=run_id,
            status="completed",
            files_added=files_added,
            files_modified=files_modified,
            files_deleted=files_deleted,
            bytes_transferred=bytes_transferred,
            changes=changes,
        )
