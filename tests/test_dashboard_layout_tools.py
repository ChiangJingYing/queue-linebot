"""Tests for dashboard layout editor tools and coordinate consistency."""

from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_config_includes_layout_reset_and_alignment_tools(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1", "2", "3"]})
    client = TestClient(main.app)

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert 'id="reset-layout"' in response.text
    assert 'id="align-horizontal"' in response.text
    assert 'id="align-vertical"' in response.text
    assert 'selectedLocations' in response.text
    assert 'getImagePlacementRect' in response.text
    assert '/dashboard/layout/reset' in response.text


def test_dashboard_layout_reset_clears_markers_only(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1", "2"]})
    client = TestClient(main.app)

    save_response = client.post(
        "/dashboard/layout",
        json={
            "imageUrl": "/dashboard/assets/sample.png",
            "markers": [
                {"location": "1-1", "x": 12.5, "y": 34.0, "label": "座位 A"},
                {"location": "1-2", "x": 60.0, "y": 70.0, "label": "座位 B"},
            ],
        },
    )
    assert save_response.status_code == 200

    reset_response = client.post("/dashboard/layout/reset")
    assert reset_response.status_code == 200
    payload = reset_response.json()
    assert payload["status"] == "reset"
    assert payload["markers"] == []
    assert payload["imageUrl"] == "/dashboard/assets/sample.png"

    layout_response = client.get("/dashboard/layout")
    assert layout_response.status_code == 200
    assert layout_response.json()["markers"] == []
    assert layout_response.json()["imageUrl"] == "/dashboard/assets/sample.png"


def test_dashboard_uses_image_canvas_markup_for_marker_alignment(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)
    client.post(
        "/dashboard/layout",
        json={
            "imageUrl": "/dashboard/assets/sample.png",
            "markers": [
                {"location": "1-1", "x": 20.0, "y": 30.0, "label": "座位 A"},
            ],
        },
    )

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert 'board-image' in response.text
    assert 'board-overlay' in response.text
    assert 'left:calc(' in response.text
    assert 'top:calc(' in response.text
