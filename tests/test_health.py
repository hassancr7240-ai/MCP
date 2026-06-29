import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


def test_root_endpoint():
    with patch("app.storage.sql_db._get_connection", side_effect=Exception("no db")):
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["service"] == "MCP Azure Server"
