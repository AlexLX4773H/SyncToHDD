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

        print("All API & Web UI integration tests passed successfully!")

if __name__ == "__main__":
    test_api_and_web_ui()
