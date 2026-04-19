from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_layout_upload_updates_image_url_to_bust_cache(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    first = client.post(
        "/dashboard/layout",
        json={"imageUrl": "/dashboard/assets/old.png", "markers": []},
    )
    assert first.status_code == 200

    reset = client.post("/dashboard/layout/image", files={"file": ("new.png", b"fakepngdata", "image/png")})
    assert reset.status_code == 200
    payload = reset.json()
    assert payload["imageUrl"].startswith("/dashboard/assets/")
    assert "?v=" in payload["imageUrl"]


def test_dashboard_config_uses_image_rect_relative_marker_positioning(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert 'const imageRect = getImagePlacementRect();' in response.text
    assert 'const markerLeft = imageRect.left + (marker.x / 100) * imageRect.width;' in response.text
    assert 'const markerTop = imageRect.top + (marker.y / 100) * imageRect.height;' in response.text
    assert 'el.style.left = `${markerLeft}px`;' in response.text
    assert 'el.style.top = `${markerTop}px`;' in response.text
