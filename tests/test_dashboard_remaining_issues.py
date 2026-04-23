from __future__ import annotations

from fastapi.testclient import TestClient

import main
from bot.handler import LineBotHandler
from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.notifier import Notifier
from services.vip_service import VipService


def _setup_runtime(tmp_path):
    db = DatabaseManager(str(tmp_path / "remaining-issues.db"))
    qm = QueueManager(db)
    vip = VipService(db)
    notifier = Notifier("", "")
    handler = LineBotHandler(
        channel_secret="",
        channel_access_token="",
        queue_manager=qm,
        vip_service=vip,
        admin_ids=["admin"],
        location_options={"A": ["1", "2"], "B": ["1"]},
    )

    main.db_manager = db
    main.queue_manager = qm
    main.vip_service = vip
    main.notifier = notifier
    main.line_handler = handler
    main.CHANNEL_SECRET = ""
    main.CHANNEL_ACCESS_TOKEN = ""
    main.LOCATION_OPTIONS = {"A": ["1", "2"], "B": ["1"]}
    main.dashboard_layout_store = main.DashboardLayoutStore(tmp_path / "dashboard_layout")


def test_dashboard_config_upload_flow_resets_marker_state_in_client(tmp_path):
    _setup_runtime(tmp_path)
    client = TestClient(main.app)

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert "setLayout({ ...layout, imageUrl: payload.imageUrl, markers: [] });" in response.text
    assert "selectedLocations = new Set();" in response.text
    assert "selectedLocation = '';" in response.text


def test_dashboard_config_marker_editor_is_appended_to_overlay(tmp_path):
    _setup_runtime(tmp_path)
    client = TestClient(main.app)

    response = client.get("/dashboard/config")

    assert response.status_code == 200
    assert "stageOverlay.appendChild(el);" in response.text
    assert "const markerLeft = imageRect.left + (marker.x / 100) * imageRect.width;" in response.text
    assert "const markerTop = imageRect.top + (marker.y / 100) * imageRect.height;" in response.text
