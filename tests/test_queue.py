import tempfile
import time
from pathlib import Path
from fastapi.testclient import TestClient
from synctohdd.api.app import app
from synctohdd.config import SyncPairConfig
from synctohdd.engine.manager import sync_manager

def test_sync_manager_queue_logic():
    """Unit test for SyncManager queueing, ordering, duplicate checks, and removals."""
    sync_manager.cancel_current_sync(clear_queue=True)
    sync_manager.clear_queue()

    pair1 = SyncPairConfig(
        id="queue-test-pair-1",
        name="Queue Pair 1",
        source="/tmp/src1",
        destination="/tmp/dst1",
        mode="mirror",
    )
    pair2 = SyncPairConfig(
        id="queue-test-pair-2",
        name="Queue Pair 2",
        source="/tmp/src2",
        destination="/tmp/dst2",
        mode="mirror",
    )
    pair3 = SyncPairConfig(
        id="queue-test-pair-3",
        name="Queue Pair 3",
        source="/tmp/src3",
        destination="/tmp/dst3",
        mode="mirror",
    )

    # 1. Enqueue job
    job1 = sync_manager.enqueue_job(pair1, dry_run=False)
    assert job1.pair_id == "queue-test-pair-1"
    assert len(sync_manager.get_queue()) == 1
    assert sync_manager.get_job_position(job1.job_id) == 1

    # 2. Duplicate check (same pair and dry_run)
    try:
        sync_manager.enqueue_job(pair1, dry_run=False)
        assert False, "Expected ValueError on duplicate enqueue"
    except ValueError as e:
        assert "already queued" in str(e)

    # 3. Enqueue second and third jobs
    job2 = sync_manager.enqueue_job(pair2, dry_run=True)
    job3 = sync_manager.enqueue_job(pair3, dry_run=False)
    assert len(sync_manager.get_queue()) == 3
    assert sync_manager.get_job_position(job2.job_id) == 2
    assert sync_manager.get_job_position(job3.job_id) == 3

    # Check serialized queue
    q = sync_manager.get_queue()
    assert len(q) == 3
    assert q[0]["pair_name"] == "Queue Pair 1"
    assert q[1]["dry_run"] is True
    assert q[2]["position"] == 3

    # 4. Remove second job
    removed = sync_manager.remove_from_queue(job2.job_id)
    assert removed is not None
    assert removed.job_id == job2.job_id
    assert len(sync_manager.get_queue()) == 2
    assert sync_manager.get_job_position(job3.job_id) == 2

    # 5. Clear queue
    cleared = sync_manager.clear_queue()
    assert cleared == 2
    assert len(sync_manager.get_queue()) == 0

def test_sync_queue_api_endpoints():
    """Integration test for queue API endpoints (/api/sync/queue, /api/sync/{pair_id}?queue=true, etc.)."""
    with TestClient(app) as client:
        # Ensure clean state
        client.delete("/api/sync/active?clear_queue=true")
        client.delete("/api/sync/queue")

        # 1. Check empty queue
        q_res = client.get("/api/sync/queue")
        assert q_res.status_code == 200
        assert q_res.json()["total"] == 0

        with tempfile.TemporaryDirectory() as src1, tempfile.TemporaryDirectory() as dst1, \
             tempfile.TemporaryDirectory() as src2, tempfile.TemporaryDirectory() as dst2:

            (Path(src1) / "file1.txt").write_text("file 1 content", encoding="utf-8")
            (Path(src2) / "file2.txt").write_text("file 2 content", encoding="utf-8")

            pair1_data = {
                "id": "api-queue-p1",
                "name": "API Queue P1",
                "source": src1,
                "destination": dst1,
                "mode": "mirror",
            }
            pair2_data = {
                "id": "api-queue-p2",
                "name": "API Queue P2",
                "source": src2,
                "destination": dst2,
                "mode": "mirror",
            }
            client.post("/api/pairs", json=pair1_data)
            client.post("/api/pairs", json=pair2_data)

            # Start pair 1
            start_p1 = client.post("/api/sync/api-queue-p1", json={"dry_run": False})
            assert start_p1.status_code == 200
            assert start_p1.json()["status"] == "started"

            # Attempt triggering pair 2 without queue while pair 1 is running -> 409 Conflict
            # Or if pair 1 finished immediately, test queueing directly
            if sync_manager.is_running:
                p2_conflict = client.post("/api/sync/api-queue-p2", json={"dry_run": False, "queue": False})
                assert p2_conflict.status_code == 409

                # Trigger pair 2 WITH queue -> 200 OK with status="queued"
                p2_queue = client.post("/api/sync/api-queue-p2", json={"dry_run": True, "queue": True})
                assert p2_queue.status_code == 200
                assert p2_queue.json()["status"] == "queued"
                assert p2_queue.json()["queue_position"] == 1
                job_id = p2_queue.json()["job_id"]

                # Inspect queue via GET
                q_res2 = client.get("/api/sync/queue")
                assert q_res2.status_code == 200
                assert q_res2.json()["total"] == 1
                assert q_res2.json()["queue"][0]["job_id"] == job_id
                assert q_res2.json()["queue"][0]["dry_run"] is True

                # Inspect active sync monitor HTML renders queue section
                active_html = client.get("/active")
                assert active_html.status_code == 200
                assert "Sync Queue" in active_html.text
                assert "API Queue P2" in active_html.text

                # Delete queued job via API
                del_job = client.delete(f"/api/sync/queue/{job_id}")
                assert del_job.status_code == 200
                assert del_job.json()["remaining_queue_length"] == 0

            # Wait for any active sync from earlier to settle
            max_wait = 5
            t0 = time.time()
            while sync_manager.is_running and time.time() - t0 < max_wait:
                time.sleep(0.05)

            # Test enqueueing and clear queue endpoint
            pair1_config = SyncPairConfig(**pair1_data)
            pair2_config = SyncPairConfig(**pair2_data)
            sync_manager.enqueue_job(pair2_config, dry_run=False)
            sync_manager.enqueue_job(pair1_config, dry_run=True)
            assert len(sync_manager.get_queue()) == 2

            clear_res = client.delete("/api/sync/queue")
            assert clear_res.status_code == 200
            assert clear_res.json()["cleared_count"] == 2
            assert len(sync_manager.get_queue()) == 0

            # Test cancelling active with clear_queue
            client.delete("/api/sync/active?clear_queue=true")

            # Clean up test pairs
            client.delete("/api/pairs/api-queue-p1")
            client.delete("/api/pairs/api-queue-p2")
            client.delete("/api/runs?keep_running=false")

def test_queue_when_busy_and_endpoints():
    """Verify queuing works without 409 when batch is running, using both query param and /queue route."""
    with TestClient(app) as client:
        client.delete("/api/sync/active?clear_queue=true")
        client.delete("/api/sync/queue")

        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
            p_data = {
                "id": "busy-test-p1",
                "name": "Busy Test P1",
                "source": src,
                "destination": dst,
                "mode": "mirror",
            }
            client.post("/api/pairs", json=p_data)

            # Simulate batch running state
            sync_manager.is_batch_running = True
            try:
                # 1. Calling without queue -> 409 Conflict
                res_no_q = client.post("/api/sync/busy-test-p1", json={"dry_run": False, "queue": False})
                assert res_no_q.status_code == 409
                assert "A sync is already in progress" in res_no_q.json()["detail"]

                # 2. Calling with query param ?queue=true -> 200 Queued
                res_q_param = client.post("/api/sync/busy-test-p1?queue=true", json={"dry_run": False})
                assert res_q_param.status_code == 200
                assert res_q_param.json()["status"] == "queued"
                assert res_q_param.json()["queue_position"] == 1

                # 3. Calling duplicate with queue=True -> 200 Queued with existing position (no 409 or crash)
                res_dup = client.post("/api/sync/busy-test-p1", json={"dry_run": False, "queue": True})
                assert res_dup.status_code == 200
                assert res_dup.json()["status"] == "queued"
                assert res_dup.json()["queue_position"] == 1

                # 4. Calling explicit /queue endpoint for dry run -> 200 Queued at position 2
                res_explicit = client.post("/api/sync/busy-test-p1/queue", json={"dry_run": True})
                assert res_explicit.status_code == 200
                assert res_explicit.json()["status"] == "queued"
                assert res_explicit.json()["queue_position"] == 2

                # 5. Calling /api/sync/all/queue
                res_all_q = client.post("/api/sync/all/queue", json={"dry_run": False})
                assert res_all_q.status_code == 200
                assert res_all_q.json()["status"] == "queued"
            finally:
                sync_manager.cancel_current_sync(clear_queue=True)
                sync_manager.is_batch_running = False
                client.delete("/api/pairs/busy-test-p1")
                client.delete("/api/runs?keep_running=false")

if __name__ == "__main__":
    test_sync_manager_queue_logic()
    test_sync_queue_api_endpoints()
    test_queue_when_busy_and_endpoints()
    print("All queue tests passed!")
