import os
import tempfile
from pathlib import Path
from synctohdd.utils.platform import (
    get_disk_usage,
    get_mount_point,
    get_drive_name,
    check_path_status,
)

def test_mount_point_and_drive_name():
    # Test with current directory
    cwd = Path.cwd().resolve()
    mount_pt = get_mount_point(cwd)
    assert mount_pt is not None
    assert isinstance(mount_pt, Path)

    drive_name = get_drive_name(mount_pt)
    assert drive_name
    assert isinstance(drive_name, str)

def test_disk_usage_metrics():
    cwd_str = str(Path.cwd().resolve())
    disk = get_disk_usage(cwd_str)
    assert disk is not None
    assert "total_bytes" in disk
    assert "used_bytes" in disk
    assert "free_bytes" in disk
    assert "percent_used" in disk
    assert "mount_path" in disk
    assert "drive_name" in disk
    assert disk["total_bytes"] > 0
    assert 0 <= disk["percent_used"] <= 100

def test_non_existent_deep_path():
    with tempfile.TemporaryDirectory() as tmp_dir:
        deep_non_existent = Path(tmp_dir) / "sub1" / "sub2" / "sub3"
        disk = get_disk_usage(str(deep_non_existent))
        assert disk is not None
        assert disk["total_bytes"] > 0
        assert disk["drive_name"]

if __name__ == "__main__":
    test_mount_point_and_drive_name()
    test_disk_usage_metrics()
    test_non_existent_deep_path()
    print("All platform tests passed!")
