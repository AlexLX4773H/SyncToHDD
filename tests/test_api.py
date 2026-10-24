import os
import tempfile
from fastapi.testclient import TestClient
from synctohdd.api.app import app

def test_api_and_web_ui():
    with TestClient(app) as client:
        # 1. Health check
        res = client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["app"] == "SyncToHDD"

        # 2. Sync status
        res = client.get("/api/sync/status")
        assert res.status_code == 200
        data = res.json()
        assert "is_running" in data
        assert "backend" in data

        # 3. Pairs CRUD API
        new_pair = {
            "id": "api-test-pair",
            "name": "API Test Pair",
            "source": "/tmp/source_test",
            "destination": "/tmp/dest_test",
            "mode": "mirror",
            "exclude": ["*.log"],
            "checksum": False,
            "bandwidth_limit": None,
        }
        create_res = client.post("/api/pairs", json=new_pair)
        assert create_res.status_code == 201

        get_res = client.get("/api/pairs/api-test-pair")
        assert get_res.status_code == 200
        assert get_res.json()["name"] == "API Test Pair"

        # Test duplicate via API
        dup_res = client.post("/api/pairs/api-test-pair/duplicate")
        assert dup_res.status_code == 201
        dup_data = dup_res.json()
        assert dup_data["name"] == "API Test Pair (Copy)"
        assert dup_data["id"] == "api-test-pair-copy"
        assert dup_data["source"] == "/tmp/source_test"
        assert dup_data["destination"] == "/tmp/dest_test"

        # Duplicate again to verify suffix increment
        dup2_res = client.post("/api/pairs/api-test-pair/duplicate")
        assert dup2_res.status_code == 201
        dup2_data = dup2_res.json()
        assert dup2_data["name"] == "API Test Pair (Copy 2)"
        assert dup2_data["id"] == "api-test-pair-copy-2"

        # Clean up duplicates
        client.delete(f"/api/pairs/{dup_data['id']}")
        client.delete(f"/api/pairs/{dup2_data['id']}")

        # 4. Web UI routes
        res_dash = client.get("/")
        assert res_dash.status_code == 200
        assert "SyncToHDD" in res_dash.text
        assert 'rel="icon"' in res_dash.text

        # Tab favicon routes
        res_fav = client.get("/favicon.ico")
        assert res_fav.status_code == 200
        assert "image" in res_fav.headers.get("content-type", "")

        res_static_fav = client.get("/static/favicon.ico")
        assert res_static_fav.status_code == 200

        res_static_icon = client.get("/static/icon.png")
        assert res_static_icon.status_code == 200

        res_pairs = client.get("/pairs")
        assert res_pairs.status_code == 200
        assert "Configured Sync Pairs" in res_pairs.text
        assert "Duplicate" in res_pairs.text
        assert f"/pairs/api-test-pair/duplicate" in res_pairs.text

        # Test duplicate form view
        res_dup_view = client.get("/pairs/api-test-pair/duplicate")
        assert res_dup_view.status_code == 200
        assert "Duplicate Sync Pair" in res_dup_view.text
        assert "API Test Pair (Copy)" in res_dup_view.text
        assert "Create Duplicate Pair" in res_dup_view.text

        # Test saving duplicate pair via form submission
        res_dup_save = client.post(
            "/pairs/save",
            data={
                "id": "",
                "name": "API Test Pair (Copy Saved)",
                "source": "/tmp/source_test",
                "destination": "/tmp/dest_test_copy",
                "mode": "mirror",
                "exclude_text": "*.log\n*.bak",
                "checksum": "true",
                "bandwidth_limit": "25M",
            },
            follow_redirects=False,
        )
        assert res_dup_save.status_code == 303
        saved_copy_res = client.get("/api/pairs/api-test-pair-copy-saved")
        assert saved_copy_res.status_code == 200
        assert saved_copy_res.json()["checksum"] is True
        client.delete("/api/pairs/api-test-pair-copy-saved")

        del_res = client.delete("/api/pairs/api-test-pair")
        assert del_res.status_code == 200

        res_active = client.get("/active")
        assert res_active.status_code == 200
        assert "Active Sync Monitor" in res_active.text

        res_runs = client.get("/runs")
        assert res_runs.status_code == 200
        assert "Sync Run History" in res_runs.text

        # 5. Run History & Clear API
        import asyncio
        import time
        from synctohdd.db.database import get_session_factory
        from synctohdd.db import crud

        # Clear any prior runs to ensure deterministic state
        client.delete("/api/runs?keep_running=false")

        async def setup_test_runs():
            factory = get_session_factory()
            async with factory() as session:
                await crud.create_sync_run(
                    session=session,
                    run_id="test-run-1",
                    sync_pair_id="pair-1",
                    sync_pair_name="Pair One",
                    source="/tmp/src",
                    destination="/tmp/dst",
                )
                await crud.finish_sync_run(session, "test-run-1", status="completed", files_added=2)
                await crud.create_sync_run(
                    session=session,
                    run_id="test-run-2",
                    sync_pair_id="pair-2",
                    sync_pair_name="Pair Two",
                    source="/tmp/src",
                    destination="/tmp/dst",
                )
                await crud.finish_sync_run(session, "test-run-2", status="failed", error_log="Err")

        asyncio.run(setup_test_runs())

        # Check runs list API
        res_runs_api = client.get("/api/runs")
        assert res_runs_api.status_code == 200
        assert res_runs_api.json()["total"] >= 2

        # Check runs web page shows Clear All History button
        res_runs_html = client.get("/runs")
        assert res_runs_html.status_code == 200
        assert "Clear All History" in res_runs_html.text

        # Test DELETE /api/runs (clear all history)
        del_runs = client.delete("/api/runs?keep_running=false")
        assert del_runs.status_code == 200
        assert del_runs.json()["deleted_count"] >= 2

        # Verify run history is cleared
        res_after = client.get("/api/runs")
        assert res_after.status_code == 200
        assert res_after.json()["total"] == 0

        # Test POST /runs/clear web action
        res_clear_web = client.post("/runs/clear", follow_redirects=False)
        assert res_clear_web.status_code == 303

        # 7. Test /api/sync/all routing (prevent /{pair_id} capturing 'all')
        with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as dst_dir:
            test_pair_obj = {
                "id": "sync-all-test-pair",
                "name": "Sync All Test Pair",
                "source": src_dir,
                "destination": dst_dir,
                "mode": "mirror",
            }
            client.post("/api/pairs", json=test_pair_obj)

            # Trigger sync all dry run
            res_sync_all = client.post("/api/sync/all", json={"dry_run": True})
            assert res_sync_all.status_code == 200, f"Expected 200, got {res_sync_all.status_code}: {res_sync_all.text}"
            sync_all_data = res_sync_all.json()
            assert sync_all_data["status"] == "started"
            assert "queued_pairs" in sync_all_data
            assert "sync-all-test-pair" in sync_all_data["queued_pairs"]

            # Give sequence a moment to finish dry run
            time.sleep(0.5)
            client.delete("/api/sync/active")

            # Cleanup pair and runs
            client.delete("/api/pairs/sync-all-test-pair")
            client.delete("/api/runs?keep_running=false")

        print("All API & Web UI integration tests passed successfully!")

if __name__ == "__main__":
    test_api_and_web_ui()

