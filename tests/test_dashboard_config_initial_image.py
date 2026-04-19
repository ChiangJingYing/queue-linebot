from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_config_stage_image_has_initial_src_from_layout(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)
    client.post('/dashboard/layout', json={'imageUrl': '/dashboard/assets/existing.png?v=abc', 'markers': []})

    response = client.get('/dashboard/config')

    assert response.status_code == 200
    assert 'id=\"stage-image\" class=\"stage-image\" src=\"/dashboard/assets/existing.png?v=abc\"' in response.text


def test_dashboard_config_upload_handler_clears_old_markers_after_new_image(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1", "2"]})
    client = TestClient(main.app)
    client.post('/dashboard/layout', json={'imageUrl': '/dashboard/assets/old.png?v=1', 'markers': [{'location': '1-1', 'x': 10, 'y': 10, 'label': 'A'}]})

    response = client.get('/dashboard/config')

    assert response.status_code == 200
    assert 'layout = { imageUrl: payload.imageUrl, markers: [] };' in response.text
