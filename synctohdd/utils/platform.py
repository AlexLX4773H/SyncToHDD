import os
import sys
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

def is_linux() -> bool:
    """Check if current operating system is Linux."""
    return sys.platform.startswith("linux")

def is_windows() -> bool:
    """Check if current operating system is Windows."""
    return sys.platform.startswith("win")

def has_rsync() -> bool:
    """Check if rsync command is available in PATH."""
    return shutil.which("rsync") is not None

def normalize_path(path_str: str) -> Path:
    """Normalize and expand path for local filesystem."""
    expanded = os.path.expanduser(os.path.expandvars(path_str.strip()))
    return Path(expanded).resolve()

def check_path_status(path_str: str, check_write: bool = False) -> Dict[str, Any]:
    """Inspect existence and permissions for a path safely."""
    path = Path(path_str)
    exists = path.exists()
    is_dir = path.is_dir() if exists else False
    readable = os.access(path, os.R_OK) if exists else False
    writable = False

    if exists:
        writable = os.access(path, os.W_OK)
    else:
        # Check if parent is writable if path doesn't exist yet
        try:
            parent = path.parent
            if parent.exists() and os.access(parent, os.W_OK):
                writable = True
        except Exception:
            writable = False

    return {
        "path": str(path),
        "exists": exists,
        "is_dir": is_dir,
        "readable": readable,
        "writable": writable,
    }

def get_disk_usage(path_str: str) -> Optional[Dict[str, Any]]:
    """Retrieve disk space metrics for the given path."""
    try:
        path = Path(path_str)
        # Find closest existing ancestor if directory doesn't exist yet
        check_path = path
        while not check_path.exists() and check_path.parent != check_path:
            check_path = check_path.parent

        if not check_path.exists():
            return None

        total, used, free = shutil.disk_usage(check_path)
        percent = (used / total * 100.0) if total > 0 else 0.0

        return {
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "percent_used": round(percent, 1),
            "mount_path": str(check_path),
        }
    except Exception:
        return None
