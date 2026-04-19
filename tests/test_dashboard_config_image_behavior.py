from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_config_does_not_use_repeating_background_for_stage(tmp_path):
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
    assert 'background:#020617 center/contain no-repeat' not in response.text
    assert 'class=\"stage-image\"' in response.text
    assert "pointer-events:auto" not in response.text
    assert "stageImage.complete" in response.text


def test_dashboard_config_click_places_marker_only_when_image_ready(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert "if (layout.imageUrl && !stageImage.complete && !(stageImage.naturalWidth && stageImage.naturalHeight)) return;" in response.text
