"""FastAPI and config integration tests."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

import main
from config import load_config
from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.notifier import Notifier
from services.vip_service import VipService
from bot.handler import LineBotHandler


def _setup_runtime(tmp_path, location_options=None):
    db = DatabaseManager(str(tmp_path / "webhook.db"))
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

    return qm


def test_load_config_returns_defaults_when_missing_file(tmp_path):
    config = load_config(str(tmp_path / "missing.yaml"))

    assert config["server"]["port"] == 8000
    assert config["queue"]["max_capacity"] == 50
    assert "line_bot" in config


def test_load_config_merges_partial_yaml_with_defaults(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "server:\n  port: 9000\nline_bot:\n  admin_ids:\n    - admin_1\n",
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config["server"]["port"] == 9000
    assert config["server"]["host"] == "0.0.0.0"
    assert config["line_bot"]["admin_ids"] == ["admin_1"]
    assert "channel_secret" in config["line_bot"]


def test_webhook_processes_join_event_and_returns_counts(tmp_path):
    qm = _setup_runtime(tmp_path)
    qm.register_name("alice", "Alice", location="A-1")
    client = TestClient(main.app)

    response = client.post(
        "/api/line/webhook",
        json={
            "events": [
                {
                    "type": "message",
                    "replyToken": "reply-1",
                    "source": {"userId": "alice"},
                    "message": {"type": "text", "text": "/join"},
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["processed_events"] == 1
    assert response.json()["replies_sent"] == 1
    assert [entry.user_id for entry in qm.get_queue()] == ["alice"]


def test_webhook_rejects_invalid_signature_when_secret_configured(tmp_path):
    _setup_runtime(tmp_path)
    main.CHANNEL_SECRET = "top-secret"
    client = TestClient(main.app)

    response = client.post(
        "/api/line/webhook",
        headers={"x-line-signature": "bad-signature"},
        json={"events": []},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "LINE 簽章驗證失敗"


def test_webhook_supports_history_command(tmp_path):
    qm = _setup_runtime(tmp_path)
    qm.join("alice", "regular")
    qm.cancel("alice")
    client = TestClient(main.app)

    response = client.post(
        "/api/line/webhook",
        json={
            "events": [
                {
                    "type": "message",
                    "replyToken": "reply-2",
                    "source": {"userId": "alice"},
                    "message": {"type": "text", "text": "/history"},
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["processed_events"] == 1


def test_load_config_overrides_location_options_without_merging_defaults(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "registration:\n  location_options:\n    '1':\n      - '1'\n      - '2'\n    '2':\n      - '4'\n",
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config["registration"]["location_options"] == {"1": ["1", "2"], "2": ["4"]}


def test_dashboard_renders_all_configured_cells_and_statuses(tmp_path):
    qm = _setup_runtime(tmp_path, location_options={"1": ["1", "2"], "2": ["1", "4"]})
    qm.register_name("alice", "王小明", location="1-1")
    qm.register_name("bob", "陳小美", location="1-2")
    qm.register_name("carol", "林小華", location="2-1")
    qm.join("bob", "regular")
    qm.join("carol", "regular")
    qm.serve_specific("carol")
    client = TestClient(main.app)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "1-1" in response.text
    assert "1-2" in response.text
    assert "2-1" in response.text
    assert "2-4" in response.text
    assert "lamp empty" in response.text
    assert "lamp blue" in response.text
    assert "lamp yellow" in response.text
    assert "lamp green" in response.text
    assert "/dashboard/data" in response.text
    assert "空位" in response.text
    assert "已註冊" in response.text
    assert "排隊中" in response.text
    assert "已叫號" in response.text
    assert "previousGrid" in response.text


def test_dashboard_data_cleared_and_reregistered_user_is_not_served(tmp_path):
    qm = _setup_runtime(tmp_path, location_options={"1": ["1"]})
    qm.register_name("alice", "王小明", location="1-1")
    qm.join("alice", "regular")
    qm.serve_specific("alice")
    qm.db.clear_all_queue()
    qm.register_name("alice", "王小明", location="1-1")
    client = TestClient(main.app)

    response = client.get("/dashboard/data")

    assert response.status_code == 200
    assert response.json()["grid"]["1"]["1"]["status"] == "registered"


def test_dashboard_config_page_and_layout_api(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1", "2"]})
    client = TestClient(main.app)

    page = client.get("/dashboard/config")
    layout = client.get("/dashboard/layout")

    assert page.status_code == 200
    assert "版面設定" in page.text
    assert "marker-editor" in page.text
    assert "刪除目前位置標記" in page.text
    assert "未放置位置" in page.text
    assert "draggable" in page.text
    assert layout.status_code == 200
    assert layout.json()["markers"] == []


def test_dashboard_layout_can_be_saved_and_rendered(tmp_path):
    qm = _setup_runtime(tmp_path, location_options={"1": ["1", "2"]})
    qm.register_name("alice", "王小明", location="1-1")
    client = TestClient(main.app)

    save_response = client.post(
        "/dashboard/layout",
        json={
            "imageUrl": "/dashboard/assets/sample.png",
            "markers": [
                {"location": "1-1", "x": 12.5, "y": 34.0, "label": "座位 A"},
                {"location": "1-2", "x": 60.0, "y": 70.0, "label": "座位 B"},
            ],
        },
    )
    page = client.get("/dashboard")
    layout = client.get("/dashboard/layout")
    data = client.get("/dashboard/data")

    assert save_response.status_code == 200
    assert layout.status_code == 200
    assert layout.json()["imageUrl"] == "/dashboard/assets/sample.png"
    assert len(layout.json()["markers"]) == 2
    assert "座位 A" in page.text
    assert "background-image" in page.text
    assert 'data-location="1-1"' in page.text
    assert data.json()["layout"]["markers"][0]["location"] == "1-1"


def test_dashboard_layout_image_upload(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    client = TestClient(main.app)

    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x02\x00\x01H\xaf\xa4q"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    response = client.post(
        "/dashboard/layout/image",
        files={"file": ("layout.png", io.BytesIO(png_bytes), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["imageUrl"].startswith("/dashboard/assets/")
    asset_path = tmp_path / "dashboard_layout" / Path(payload["imageUrl"]).name
    assert asset_path.exists()


def test_dashboard_data_returns_version_and_grid_statuses(tmp_path):
    qm = _setup_runtime(tmp_path, location_options={"1": ["1", "2"], "2": ["1", "4"]})
    qm.register_name("alice", "王小明", location="1-1")
    qm.register_name("bob", "陳小美", location="1-2")
    qm.register_name("carol", "林小華", location="2-1")
    qm.join("bob", "regular")
    qm.join("carol", "regular")
    qm.serve_specific("carol")
    client = TestClient(main.app)

    response = client.get("/dashboard/data")

    assert response.status_code == 200
    payload = response.json()
    assert payload["rows"] == ["1", "2"]
    assert payload["cols"] == ["1", "2", "4"]
    assert payload["version"]
    assert payload["grid"]["1"]["1"]["status"] == "registered"
    assert payload["grid"]["1"]["2"]["status"] == "queued"
    assert payload["grid"]["2"]["1"]["status"] == "served"
    assert payload["grid"]["2"]["4"]["status"] == "empty"
