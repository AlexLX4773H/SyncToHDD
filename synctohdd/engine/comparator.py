import os
import hashlib
import fnmatch
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, Callable
from synctohdd.engine.base import FileItem, FileDiff

def should_exclude(rel_path: str, is_dir: bool, patterns: List[str]) -> bool:
    """Check if relative path matches any exclusion glob pattern."""
    if not patterns:
        return False

    norm_rel = rel_path.replace("\\", "/").strip("/")
    parts = norm_rel.split("/")

    for pattern in patterns:
        pat = pattern.strip().replace("\\", "/")
        if not pat:
            continue

        # If pattern ends with '/', it targets directories
        if pat.endswith("/"):
            dir_pat = pat.rstrip("/")
            # Check against each folder part
            if any(fnmatch.fnmatch(p, dir_pat) for p in parts):
                return True
            if fnmatch.fnmatch(norm_rel, dir_pat) or fnmatch.fnmatch(norm_rel, f"{dir_pat}/*"):
                return True
        else:
            # Match anywhere in tree if no slash in pattern
            if "/" not in pat:
                if any(fnmatch.fnmatch(p, pat) for p in parts):
                    return True
            else:
                # Direct match on path
                if fnmatch.fnmatch(norm_rel, pat.lstrip("/")):
                    return True

    return False

def compute_sha256(file_path: Path, chunk_size: int = 65536, cancel_check: Optional[Callable[[], bool]] = None) -> str:
    """Calculate SHA-256 hash of a file with chunking."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            if cancel_check and cancel_check():
                raise InterruptedError("Cancelled during hash computation")
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()

def scan_directory(
    root_path: Path,
    exclude_patterns: List[str],
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, FileItem]:
    """Recursively scan directory tree and return mapping of rel_path -> FileItem."""
    items: Dict[str, FileItem] = {}
    if not root_path.exists():
        return items

    for root, dirs, files in os.walk(root_path, followlinks=False):
        if cancel_check and cancel_check():
            raise InterruptedError("Directory scan cancelled")

        rel_root = os.path.relpath(root, root_path)
        if rel_root == ".":
            rel_root = ""

        # Filter directories in-place to avoid descending into excluded trees
        i = len(dirs) - 1
        while i >= 0:
            d_name = dirs[i]
            rel_dir = f"{rel_root}/{d_name}".lstrip("/") if rel_root else d_name
            if should_exclude(rel_dir, is_dir=True, patterns=exclude_patterns):
                del dirs[i]
            i -= 1

        for f_name in files:
            if cancel_check and cancel_check():
                raise InterruptedError("Directory scan cancelled")

            rel_file = f"{rel_root}/{f_name}".lstrip("/").replace("\\", "/") if rel_root else f_name
            if should_exclude(rel_file, is_dir=False, patterns=exclude_patterns):
                continue

            abs_file = Path(root) / f_name
            try:
                stat = abs_file.stat()
                items[rel_file] = FileItem(
                    rel_path=rel_file,
                    abs_path=str(abs_file),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                    is_dir=False,
                )
            except (OSError, PermissionError):
                # Skip unreadable files or broken links
                continue

    return items

def compare_file_trees(
    src_items: Dict[str, FileItem],
    dst_items: Dict[str, FileItem],
    src_base: Path,
    dst_base: Path,
    checksum: bool = False,
    mode: str = "mirror",
    mtime_tolerance: float = 1.0,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Tuple[List[FileDiff], List[FileDiff], List[FileDiff], List[FileDiff]]:
    """
    Compare scanned source and destination file dictionaries.
    Returns: (added, modified, deleted, unchanged)
    """
    added: List[FileDiff] = []
    modified: List[FileDiff] = []
    deleted: List[FileDiff] = []
    unchanged: List[FileDiff] = []

    # Check for added and modified
    for rel_path, src_item in src_items.items():
        if cancel_check and cancel_check():
            raise InterruptedError("Comparison cancelled")

        src_mtime_dt = datetime.fromtimestamp(src_item.mtime, tz=timezone.utc)

        if rel_path not in dst_items:
            added.append(
                FileDiff(
                    action="added",
                    rel_path=rel_path,
                    size=src_item.size,
                    source_mtime=src_mtime_dt,
                )
            )
        else:
            dst_item = dst_items[rel_path]
            # Compare size first
            size_diff = src_item.size != dst_item.size
            # Compare mtime with tolerance for filesystem granularity (FAT32/NTFS/ext4)
            time_diff = abs(src_item.mtime - dst_item.mtime) > mtime_tolerance

            is_modified = False
            if size_diff or time_diff:
                if checksum and not size_diff:
                    # Sizes match but mtime differs; compute checksum to be sure
                    try:
                        src_hash = compute_sha256(Path(src_item.abs_path), cancel_check=cancel_check)
                        dst_hash = compute_sha256(Path(dst_item.abs_path), cancel_check=cancel_check)
                        is_modified = (src_hash != dst_hash)
                    except Exception:
                        is_modified = True
                else:
                    is_modified = True

            if is_modified:
                modified.append(
                    FileDiff(
                        action="modified",
                        rel_path=rel_path,
                        size=src_item.size,
                        source_mtime=src_mtime_dt,
                    )
                )
            else:
                unchanged.append(
                    FileDiff(
                        action="unchanged",
                        rel_path=rel_path,
                        size=src_item.size,
                        source_mtime=src_mtime_dt,
                    )
                )

    # Check for deleted (only in mirror mode)
    if mode == "mirror":
        for rel_path, dst_item in dst_items.items():
            if cancel_check and cancel_check():
                raise InterruptedError("Comparison cancelled")

            if rel_path not in src_items:
                deleted.append(
                    FileDiff(
                        action="deleted",
                        rel_path=rel_path,
                        size=dst_item.size,
                        source_mtime=datetime.fromtimestamp(dst_item.mtime, tz=timezone.utc),
                    )
                )

    return added, modified, deleted, unchanged
