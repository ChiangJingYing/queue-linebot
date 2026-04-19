from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_config_no_longer_uses_stage_background_image(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert 'stage.style.backgroundImage' not in response.text
    assert 'stageImage.src = layout.imageUrl || \"\"' in response.text


def test_dashboard_config_upload_replaces_image_src_immediately(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert 'stageImage.src = layout.imageUrl || ""' in response.text
    assert 'stageImage.src = payload.imageUrl;' in response.text


def test_dashboard_config_marker_editor_is_appended_to_overlay(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert 'stageOverlay.appendChild(el);' in response.text


def test_dashboard_board_fits_without_scroll_target_size(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert 'max-width:min(100vw - 48px, 1400px)' in response.text
    assert 'max-height:calc(100vh - 140px)' in response.text
