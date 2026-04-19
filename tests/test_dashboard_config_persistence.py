from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_config_bootstraps_stage_image_from_initial_layout(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)
    client.post(
        "/dashboard/layout",
        json={"imageUrl": "/dashboard/assets/existing.png?v=123", "markers": []},
    )

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert 'let layout = {"imageUrl": "/dashboard/assets/existing.png?v=123", "markers": []};' in response.text
    assert 'stageImage.src = layout.imageUrl || "";' in response.text
    assert 'renderEditor();' in response.text


def test_dashboard_layout_save_keeps_latest_uploaded_image_url(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    upload = client.post('/dashboard/layout/image', files={'file': ('new.png', b'pngdata', 'image/png')})
    assert upload.status_code == 200
    image_url = upload.json()['imageUrl']

    save = client.post('/dashboard/layout', json={'markers': [{'location': '1-1', 'x': 10, 'y': 20, 'label': 'A'}]})
    assert save.status_code == 200
    assert save.json()['imageUrl'] == image_url
