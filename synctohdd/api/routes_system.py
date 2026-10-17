import sys
import platform
from fastapi import APIRouter, Query
from typing import Dict, Any, Optional
from synctohdd.utils.platform import is_linux, is_windows, has_rsync, get_disk_usage, check_path_status

router = APIRouter(prefix="/api/system", tags=["System"])

@router.get("/info", response_model=Dict[str, Any])
def get_system_info():
    """Retrieve runtime host info, OS, rsync availability, and Python details."""
    return {
        "platform": platform.platform(),
        "system": platform.system(),
        "is_linux": is_linux(),
        "is_windows": is_windows(),
        "has_rsync": has_rsync(),
        "python_version": sys.version,
    }

@router.get("/disk", response_model=Dict[str, Any])
def check_disk(path: str = Query(..., description="Directory or mount path to query")):
    """Get disk usage metrics for a specific directory path."""
    disk = get_disk_usage(path)
    status = check_path_status(path)
    return {
        "path": path,
        "status": status,
        "disk": disk,
    }
