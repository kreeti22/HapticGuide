"""
test_routes.py
--------------
Unit tests for FastAPI endpoints (/cmd, /stats, /health) using TestClient.
"""

import sys
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from routes import router
import globals
from shared_state import stream_stats


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_get_cmd_endpoint(client):
    with globals.command_lock:
        globals.latest_command.update({"left": 0, "front": 255, "right": 0, "back": 0})

    response = client.get("/cmd")
    assert response.status_code == 200
    data = response.json()

    assert "left" in data
    assert "front" in data
    assert "right" in data
    assert "back" in data
    assert data["front"] == 255


def test_get_stats_endpoint(client):
    stream_stats.mark_connected("tcp://192.168.1.100:9000", 640, 480)

    response = client.get("/stats")
    assert response.status_code == 200
    data = response.json()

    assert "camera_fps" in data
    assert "recv_fps" in data
    assert "ai_fps" in data
    assert "frame_age_ms" in data
    assert "yolo_time_ms" in data
    assert "current_resolution" in data
    assert "client_ip" in data
    assert "connected" in data

    assert data["connected"] is True
    assert data["current_resolution"] == "640×480"
    assert data["client_ip"] == "192.168.1.100"

    stream_stats.mark_disconnected()


def test_get_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert "connected" in data


def test_removed_frame_endpoint(client):
    response = client.get("/frame")
    assert response.status_code == 404
