"""FastAPI and config integration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient

import main
from config import load_config
from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.notifier import Notifier
from services.vip_service import VipService
from bot.handler import LineBotHandler


def _setup_runtime(tmp_path):
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
    )

    main.db_manager = db
    main.queue_manager = qm
    main.vip_service = vip
    main.notifier = notifier
    main.line_handler = handler
    main.CHANNEL_SECRET = ""
    main.CHANNEL_ACCESS_TOKEN = ""

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
