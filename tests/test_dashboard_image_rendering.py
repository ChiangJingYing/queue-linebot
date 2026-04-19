from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_page_renders_uploaded_image_element(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    client.post(
        "/dashboard/layout",
        json={
            "imageUrl": "/dashboard/assets/sample.png",
            "markers": [{"location": "1-1", "x": 10, "y": 20, "label": "A"}],
        },
    )

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert 'id="board-image"' in response.text
    assert 'src="/dashboard/assets/sample.png"' in response.text
    assert 'window.addEventListener(\'resize\'' in response.text


def test_dashboard_config_renders_stage_image_element(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    client.post(
        "/dashboard/layout",
        json={
            "imageUrl": "/dashboard/assets/sample.png",
            "markers": [],
        },
    )

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert 'id=\"stage-image\"' in response.text
    assert 'stageImage.addEventListener(\'load\'' in response.text
    assert 'window.addEventListener(\'resize\'' in response.text
