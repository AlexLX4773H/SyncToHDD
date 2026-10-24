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

        del_res = client.delete("/api/pairs/api-test-pair")
        assert del_res.status_code == 200

        # 4. Web UI routes
        res_dash = client.get("/")
        assert res_dash.status_code == 200
        assert "SyncToHDD" in res_dash.text

        res_pairs = client.get("/pairs")
        assert res_pairs.status_code == 200
        assert "Configured Sync Pairs" in res_pairs.text

        res_active = client.get("/active")
        assert res_active.status_code == 200
        assert "Active Sync Monitor" in res_active.text

        res_runs = client.get("/runs")
        assert res_runs.status_code == 200
        assert "Sync Run History" in res_runs.text

        # 5. Run History & Clear API
        import asyncio
        from synctohdd.db.database import get_session_factory
        from synctohdd.db import crud

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
        del_runs = client.delete("/api/runs")
        assert del_runs.status_code == 200
        assert del_runs.json()["deleted_count"] >= 2

        # Verify run history is cleared
        res_after = client.get("/api/runs")
        assert res_after.status_code == 200
        assert res_after.json()["total"] == 0

        # Test POST /runs/clear web action
        res_clear_web = client.post("/runs/clear", follow_redirects=False)
        assert res_clear_web.status_code == 303

        print("All API & Web UI integration tests passed successfully!")

if __name__ == "__main__":
    test_api_and_web_ui()

