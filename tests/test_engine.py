import os
import tempfile
import uuid
from pathlib import Path
from synctohdd.config import SyncPairConfig
from synctohdd.engine.python_backend import PythonSyncBackend

def test_python_backend_sync():
    with tempfile.TemporaryDirectory() as tmp_src, tempfile.TemporaryDirectory() as tmp_dst:
        src = Path(tmp_src)
        dst = Path(tmp_dst)

        # Create source files
        (src / "subfolder").mkdir()
        (src / "subfolder" / "comic1.cbz").write_text("comic data 1", encoding="utf-8")
        (src / "readme.txt").write_text("hello sync", encoding="utf-8")
        (src / "ignore.tmp").write_text("temp data", encoding="utf-8")

        pair = SyncPairConfig(
            id="test-pair",
            name="Test Pair",
            source=str(src),
            destination=str(dst),
            mode="mirror",
            exclude=["*.tmp"],
            checksum=False,
        )

        backend = PythonSyncBackend()

        # 1. Test Dry Run
        run_id_dry = str(uuid.uuid4())
        dry_summary = backend.run_sync(pair, run_id=run_id_dry, dry_run=True)
        assert dry_summary.status == "completed"
        assert dry_summary.files_added == 2  # comic1.cbz and readme.txt
        # Ensure nothing was actually written to destination
        assert not (dst / "readme.txt").exists()

        # 2. Test Live Sync
        run_id_live = str(uuid.uuid4())
        live_summary = backend.run_sync(pair, run_id=run_id_live, dry_run=False)
        assert live_summary.status == "completed"
        assert live_summary.files_added == 2
        assert (dst / "readme.txt").read_text(encoding="utf-8") == "hello sync"
        assert (dst / "subfolder" / "comic1.cbz").read_text(encoding="utf-8") == "comic data 1"
        assert not (dst / "ignore.tmp").exists()

        # 3. Modify source file and delete another
        (src / "readme.txt").write_text("modified sync content", encoding="utf-8")
        (src / "subfolder" / "comic1.cbz").unlink()

        run_id_update = str(uuid.uuid4())
        update_summary = backend.run_sync(pair, run_id=run_id_update, dry_run=False)
        assert update_summary.status == "completed"
        assert update_summary.files_modified == 1
        assert update_summary.files_deleted == 1
        assert (dst / "readme.txt").read_text(encoding="utf-8") == "modified sync content"
        assert not (dst / "subfolder" / "comic1.cbz").exists()

if __name__ == "__main__":
    test_python_backend_sync()
    print("All engine tests passed!")
