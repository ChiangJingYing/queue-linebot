"""Tests for dashboard layout editor tools and coordinate consistency."""

from __future__ import annotations

from fastapi.testclient import TestClient

import main
from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.notifier import Notifier
from services.vip_service import VipService
from bot.handler import LineBotHandler


def _setup_runtime(tmp_path, location_options=None):
    db = DatabaseManager(str(tmp_path / "dashboard-tools.db"))
    qm = QueueManager(db)
    vip = VipService(db)
    notifier = Notifier("", "")
    handler = LineBotHandler(
        channel_secret="",
        channel_access_token="",
        queue_manager=qm,
        vip_service=vip,
        admin_ids=["admin"],
        location_options=location_options or {"A": ["1", "2"], "B": ["1", "2"]},
    )

    main.db_manager = db
    main.queue_manager = qm
    main.vip_service = vip
    main.notifier = notifier
    main.line_handler = handler
    main.CHANNEL_SECRET = ""
    main.CHANNEL_ACCESS_TOKEN = ""
    main.LOCATION_OPTIONS = location_options or {"A": ["1", "2"], "B": ["1", "2"]}
    main.dashboard_layout_store = main.DashboardLayoutStore(tmp_path / "dashboard_layout")


def test_dashboard_layout_editor_supports_alignment_actions(tmp_path):
    _setup_runtime(tmp_path)
    client = TestClient(main.app)

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert 'id="align-horizontal"' in response.text
    assert 'id="align-vertical"' in response.text
    assert "function alignSelected(axis)" in response.text
    assert "showToast('請至少選兩個位置再對齊')" in response.text


def test_dashboard_uses_image_canvas_markup_for_marker_alignment(tmp_path):
    _setup_runtime(tmp_path)
    client = TestClient(main.app)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert 'id="board"' in response.text
    assert 'id="board-image"' in response.text
    assert 'id="board-overlay"' in response.text
    assert 'function getImagePlacementRect()' in response.text
    assert "marker.style.left = (imageRect.left + (x / 100) * imageRect.width) + 'px';" in response.text
    assert "marker.style.top  = (imageRect.top  + (y / 100) * imageRect.height) + 'px';" in response.text


def test_dashboard_config_uses_image_canvas_markup_for_click_alignment(tmp_path):
    _setup_runtime(tmp_path)
    client = TestClient(main.app)

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert 'id="stage"' in response.text
    assert 'id="stage-image"' in response.text
    assert 'id="stage-overlay"' in response.text
    assert 'function getImagePlacementRect()' in response.text
    assert "const x = ((event.clientX - stageRect.left - imageRect.left) / imageRect.width) * 100;" in response.text
    assert "const y = ((event.clientY - stageRect.top - imageRect.top) / imageRect.height) * 100;" in response.text
