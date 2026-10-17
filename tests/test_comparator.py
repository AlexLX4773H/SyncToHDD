import tempfile
from pathlib import Path
from datetime import datetime, timezone
from synctohdd.engine.comparator import should_exclude, compute_sha256, compare_file_trees
from synctohdd.engine.base import FileItem

def test_should_exclude():
    patterns = ["*.tmp", ".thumbs/", "node_modules/", "*.bak", "/root_only.txt"]

    # File extensions
    assert should_exclude("file.tmp", False, patterns) is True
    assert should_exclude("folder/file.tmp", False, patterns) is True
    assert should_exclude("file.txt", False, patterns) is False

    # Directory patterns
    assert should_exclude(".thumbs", True, patterns) is True
    assert should_exclude("nested/.thumbs/preview.jpg", False, patterns) is True
    assert should_exclude("node_modules/express/index.js", False, patterns) is True

def test_compare_file_trees():
    with tempfile.TemporaryDirectory() as tmp_src, tempfile.TemporaryDirectory() as tmp_dst:
        src_path = Path(tmp_src)
        dst_path = Path(tmp_dst)

        # Build mock FileItems
        src_items = {
            "new_file.txt": FileItem("new_file.txt", str(src_path / "new_file.txt"), size=100, mtime=1000.0),
            "modified.txt": FileItem("modified.txt", str(src_path / "modified.txt"), size=200, mtime=2000.0),
            "same.txt": FileItem("same.txt", str(src_path / "same.txt"), size=300, mtime=1500.0),
        }

        dst_items = {
            "modified.txt": FileItem("modified.txt", str(dst_path / "modified.txt"), size=150, mtime=1800.0),
            "same.txt": FileItem("same.txt", str(dst_path / "same.txt"), size=300, mtime=1500.0),
            "obsolete.txt": FileItem("obsolete.txt", str(dst_path / "obsolete.txt"), size=50, mtime=1200.0),
        }

        added, modified, deleted, unchanged = compare_file_trees(
            src_items=src_items,
            dst_items=dst_items,
            src_base=src_path,
            dst_base=dst_path,
            checksum=False,
            mode="mirror",
        )

        assert len(added) == 1
        assert added[0].rel_path == "new_file.txt"

        assert len(modified) == 1
        assert modified[0].rel_path == "modified.txt"

        assert len(deleted) == 1
        assert deleted[0].rel_path == "obsolete.txt"

        assert len(unchanged) == 1
        assert unchanged[0].rel_path == "same.txt"

def test_additive_mode_no_deletions():
    with tempfile.TemporaryDirectory() as tmp_src, tempfile.TemporaryDirectory() as tmp_dst:
        src_path = Path(tmp_src)
        dst_path = Path(tmp_dst)

        src_items = {}
        dst_items = {
            "keep_me.txt": FileItem("keep_me.txt", str(dst_path / "keep_me.txt"), size=50, mtime=1000.0)
        }

        added, modified, deleted, unchanged = compare_file_trees(
            src_items=src_items,
            dst_items=dst_items,
            src_base=src_path,
            dst_base=dst_path,
            mode="additive",
        )

        # In additive mode, deleted should be empty
        assert len(deleted) == 0

if __name__ == "__main__":
    test_should_exclude()
    test_compare_file_trees()
    test_additive_mode_no_deletions()
    print("All comparator tests passed!")
