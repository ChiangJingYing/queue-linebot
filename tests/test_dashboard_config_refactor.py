from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_config_uses_single_render_pipeline(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1", "2"]})
    client = TestClient(main.app)

    response = client.get('/dashboard/config')

    assert response.status_code == 200
    text = response.text
    assert 'function setLayout(nextLayout)' in text
    assert 'function syncStageImage()' in text
    assert 'requestAnimationFrame(() => renderEditor());' not in text
    assert 'setTimeout(() => renderEditor(), 50);' not in text
    assert 'stageImage.removeAttribute(\'src\');' not in text
    assert 'layout = { imageUrl: payload.imageUrl, markers: [] };' not in text


def test_dashboard_config_upload_sets_layout_via_single_path(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    response = client.get('/dashboard/config')

    assert response.status_code == 200
    text = response.text
    assert 'setLayout({ ...layout, imageUrl: payload.imageUrl, markers: [] });' in text
    assert 'syncStageImage();' in text
    assert 'renderEditor();' in text
