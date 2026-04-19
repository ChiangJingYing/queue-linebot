from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_config_uses_image_ratio_canvas(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert 'aspect-ratio: var(--stage-aspect-ratio, 16 / 9)' in response.text
    assert 'function updateStageAspectRatio()' in response.text
    assert "stage.style.setProperty('--stage-aspect-ratio'" in response.text
    assert 'if (stageImage.naturalWidth && stageImage.naturalHeight)' in response.text


def test_dashboard_page_uses_image_ratio_board(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert 'aspect-ratio: var(--board-aspect-ratio, 16 / 9)' in response.text
    assert 'function updateBoardAspectRatio()' in response.text
    assert "board.style.setProperty('--board-aspect-ratio'" in response.text
