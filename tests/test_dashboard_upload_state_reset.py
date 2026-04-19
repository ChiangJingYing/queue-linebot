from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_config_upload_flow_resets_layout_state_to_new_image(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1", "2"]})
    client = TestClient(main.app)

    response = client.get('/dashboard/config')

    assert response.status_code == 200
    assert 'layout = { imageUrl: payload.imageUrl, markers: [] };' in response.text
    assert "stageImage.removeAttribute('src');" in response.text
    assert "stageOverlay.innerHTML = '';" in response.text
