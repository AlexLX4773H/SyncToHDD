from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Callable
from synctohdd.config import SyncPairConfig

@dataclass
class FileItem:
    rel_path: str
    abs_path: str
    size: int
    mtime: float
    is_dir: bool = False

@dataclass
class FileDiff:
    action: str  # "added" | "modified" | "deleted" | "unchanged" | "error"
    rel_path: str
    size: Optional[int] = None
    source_mtime: Optional[datetime] = None
    error: Optional[str] = None

@dataclass
class SyncProgressEvent:
    run_id: str
    pair_id: str
    pair_name: str
    status: str  # "scanning" | "syncing" | "completed" | "failed" | "cancelled"
    current_file: Optional[str] = None
    current_action: Optional[str] = None
    files_processed: int = 0
    total_files_to_sync: int = 0
    bytes_transferred: int = 0
    total_bytes_to_transfer: int = 0
    percent: float = 0.0
    files_added: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    files_unchanged: int = 0
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

@dataclass
class SyncSummary:
    run_id: str
    status: str  # "completed" | "failed" | "cancelled"
    files_added: int = 0
    files_modified: int = 0
    files_deleted: int = 0
    files_unchanged: int = 0
    bytes_transferred: int = 0
    changes: List[FileDiff] = field(default_factory=list)
    error_log: Optional[str] = None

ProgressCallback = Callable[[SyncProgressEvent], None]

class BaseSyncBackend(ABC):
    """Abstract base class for sync backends."""

    @abstractmethod
    def run_sync(
        self,
        pair: SyncPairConfig,
        run_id: str,
        dry_run: bool = False,
        progress_cb: Optional[ProgressCallback] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> SyncSummary:
        """Execute the synchronization process."""
        pass
