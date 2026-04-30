"""FastAPI and config integration tests."""

from __future__ import annotations

import io
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

import main
from config import load_config
from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.notifier import Notifier
from services.telegram_commands import TelegramCommandService
from services.discord_commands import DiscordCommandService
from services.vip_service import VipService
from bot.handler import LineBotHandler


def _setup_runtime(tmp_path, location_options=None):
    db = DatabaseManager(str(tmp_path / "webhook.db"))
    qm = QueueManager(db)
    vip = VipService(db)
    notifier = Notifier("", "", discord_sender=lambda user_id, text: None, db=db)
    handler = LineBotHandler(
        channel_secret="",
        channel_access_token="",
        queue_manager=qm,
        vip_service=vip,
        admin_ids=["admin"],
        location_options=location_options or {"A": ["1", "2"], "B": ["1", "2"]},
    )
    main.dashboard_announcement_service = None

    main.db_manager = db
    main.queue_manager = qm
    main.vip_service = vip
    main.notifier = notifier
    main.line_handler = handler
    main.telegram_command_service = TelegramCommandService(db=db, queue_manager=qm, telegram_sender=lambda user_id, text: None)
    main.discord_command_service = DiscordCommandService(db=db, location_options=location_options or {"A": ["1", "2"], "B": ["1", "2"]})
    main.CHANNEL_SECRET = ""
    main.CHANNEL_ACCESS_TOKEN = ""
    main.TELEGRAM_BOT_TOKEN = ""
    main.TELEGRAM_WEBHOOK_SECRET = ""
    main.DISCORD_PUBLIC_KEY = ""
    main.LOCATION_OPTIONS = location_options or {"A": ["1", "2"], "B": ["1", "2"]}
    main.dashboard_layout_store = main.DashboardLayoutStore(tmp_path / "dashboard_layout")
    main.config["web_ui"] = {
        "admin_token": "",
        "protect_read_routes": False,
        "allow_query_token": False,
        "session_cookie_name": "queue_admin_session",
        "session_secret": "",
    }

    return qm


def _sign_discord_payload(private_key: Ed25519PrivateKey, body: bytes, timestamp: str = "1714454100") -> dict[str, str]:
    signature = private_key.sign(timestamp.encode("utf-8") + body).hex()
    return {
        "x-signature-ed25519": signature,
        "x-signature-timestamp": timestamp,
        "content-type": "application/json",
    }




def test_telegram_command_service_reuses_shared_queue_manager_with_notifier(tmp_path):
    db = DatabaseManager(str(tmp_path / "webhook.db"))
    shared_qm = QueueManager(db, notifier=Notifier("", "", discord_sender=lambda user_id, text: None, db=db))

    service = TelegramCommandService(
        db=db,
        queue_manager=shared_qm,
        telegram_sender=lambda user_id, text: None,
    )

    assert service.queue_manager is shared_qm
    assert service.queue_manager.notifier is shared_qm.notifier

def test_docker_runtime_timezone_is_asia_taipei():
    compose_text = Path("docker-compose.yml").read_text(encoding="utf-8")
    dockerfile_text = Path("Dockerfile").read_text(encoding="utf-8")

    assert "TZ=Asia/Taipei" in compose_text or "TZ=Asia/Taipei" in dockerfile_text
    assert "Asia/Taipei" in compose_text or "Asia/Taipei" in dockerfile_text


def test_load_config_returns_defaults_when_missing_file(tmp_path):
    config = load_config(str(tmp_path / "missing.yaml"))

    assert config["server"]["port"] == 8000
    assert config["queue"]["max_capacity"] == 50
    assert "line_bot" in config


def test_load_config_prefers_config_directory_default_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "queue_config.yaml").write_text(
        "server:\n  port: 9100\nqueue:\n  max_capacity: 88\n",
        encoding="utf-8",
    )
    (tmp_path / "queue_config.yaml").write_text(
        "server:\n  port: 9200\n",
        encoding="utf-8",
    )

    config = load_config()

    assert config["server"]["port"] == 9100
    assert config["queue"]["max_capacity"] == 88


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


def test_load_config_reads_admin_ids_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LINE_ADMIN_IDS", "admin_1, admin_2 ,admin_3")

    config = load_config(str(tmp_path / "missing.yaml"))

    assert config["line_bot"]["admin_ids"] == ["admin_1", "admin_2", "admin_3"]


def test_load_config_reads_new_order_announcement_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NEW_ORDER_ANNOUNCEMENT_TEXT", "/app/audio/new-order.mp3")

    config = load_config(str(tmp_path / "missing.yaml"))

    assert config["tts"]["new_order_announcement_text"] == "/app/audio/new-order.mp3"


def test_load_config_ignores_empty_section_and_keeps_env_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "env-secret")
    monkeypatch.setenv("LINE_CHANNEL_TOKEN", "env-token")
    monkeypatch.setenv("WEB_UI_ADMIN_TOKEN", "env-admin-token")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "line_bot:\nweb_ui:\n",
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config["line_bot"]["channel_secret"] == "env-secret"
    assert config["line_bot"]["channel_access_token"] == "env-token"
    assert config["web_ui"]["admin_token"] == "env-admin-token"
    assert config["web_ui"]["session_cookie_name"] == "queue_admin_session"


def test_load_config_reads_telegram_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-123")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret-xyz")

    config = load_config(str(tmp_path / "missing.yaml"))

    assert config["telegram_bot"]["bot_token"] == "bot-123"
    assert config["telegram_bot"]["webhook_secret"] == "secret-xyz"


def test_load_config_reads_discord_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord-bot-token")
    monkeypatch.setenv("DISCORD_APPLICATION_ID", "discord-app-id")
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", "discord-public-key")

    config = load_config(str(tmp_path / "missing.yaml"))

    assert config["discord_bot"]["bot_token"] == "discord-bot-token"
    assert config["discord_bot"]["application_id"] == "discord-app-id"
    assert config["discord_bot"]["public_key"] == "discord-public-key"


def test_discord_interactions_returns_ping_pong(tmp_path):
    _setup_runtime(tmp_path)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    main.DISCORD_PUBLIC_KEY = public_key
    client = TestClient(main.app)
    body = json.dumps({"type": 1}).encode("utf-8")

    response = client.post(
        "/api/discord/interactions",
        content=body,
        headers=_sign_discord_payload(private_key, body),
    )

    assert response.status_code == 200
    assert response.json() == {"type": 1}


def test_discord_interactions_marks_user_as_discord_user(tmp_path):
    _setup_runtime(tmp_path)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    main.DISCORD_PUBLIC_KEY = public_key
    client = TestClient(main.app)
    payload = {
        "type": 2,
        "data": {"name": "menu"},
        "member": {"user": {"id": "discord_user_1"}},
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/api/discord/interactions",
        content=body,
        headers=_sign_discord_payload(private_key, body),
    )

    assert response.status_code == 200
    assert main.db_manager.get_config("discord_user:discord_user_1") == "1"




def test_discord_interactions_stores_dm_channel_id(tmp_path):
    _setup_runtime(tmp_path)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    main.DISCORD_PUBLIC_KEY = public_key
    client = TestClient(main.app)
    payload = {
        "type": 3,
        "data": {"custom_id": "menu:status", "component_type": 2},
        "channel_id": "dm_chan_123",
        "member": {"user": {"id": "discord_user_1"}},
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/api/discord/interactions",
        content=body,
        headers=_sign_discord_payload(private_key, body),
    )

    assert response.status_code == 200
    assert main.db_manager.get_config("discord_user:discord_user_1") == "1"
    assert main.db_manager.get_config("discord_channel:discord_user_1") == "dm_chan_123"


def test_send_discord_text_fetches_dm_channel_from_user_id(monkeypatch, tmp_path):
    calls = []

    class DummyResponse:
        def __init__(self, payload: str = '{"id":"msg_1"}') -> None:
            self.payload = payload

        def read(self):
            return self.payload.encode('utf-8')

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout=10):
        calls.append((request.full_url, request.method, request.data.decode('utf-8') if request.data else None))
        if request.full_url.endswith('/users/@me/channels'):
            return DummyResponse('{"id":"dm_chan_123"}')
        return DummyResponse()

    db = DatabaseManager(str(tmp_path / 'discord.db'))
    db.set_config('discord_channel:discord_user_1', 'stale_chan_should_not_be_used')
    monkeypatch.setattr(main, 'db_manager', db)
    monkeypatch.setattr(main, 'DISCORD_BOT_TOKEN', 'token')
    monkeypatch.setattr(main.urllib.request, 'urlopen', fake_urlopen)

    assert main._send_discord_text('discord_user_1', '輪到你了') is True
    assert calls == [
        ('https://discord.com/api/v10/users/@me/channels', 'POST', '{"recipient_id": "discord_user_1"}'),
        ('https://discord.com/api/v10/channels/dm_chan_123/messages', 'POST', '{"content": "\\u8f2a\\u5230\\u4f60\\u4e86"}')
    ]

def test_discord_interactions_handles_application_command(tmp_path):
    qm = _setup_runtime(tmp_path)
    qm.register_name("45678", "B12345678", location="A-1")
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    main.DISCORD_PUBLIC_KEY = public_key
    client = TestClient(main.app)
    payload = {
        "type": 2,
        "data": {"name": "join"},
        "member": {"user": {"id": "45678"}},
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/api/discord/interactions",
        content=body,
        headers=_sign_discord_payload(private_key, body),
    )

    assert response.status_code == 200
    assert response.json()["type"] == 4
    assert "已加入隊列" in response.json()["data"]["content"]
    assert response.json()["data"]["flags"] == 64


def test_discord_interactions_returns_register_modal_for_command(tmp_path):
    _setup_runtime(tmp_path)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    main.DISCORD_PUBLIC_KEY = public_key
    client = TestClient(main.app)
    payload = {
        "type": 2,
        "data": {"name": "register"},
        "member": {"user": {"id": "45678"}},
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/api/discord/interactions",
        content=body,
        headers=_sign_discord_payload(private_key, body),
    )

    assert response.status_code == 200
    assert response.json()["type"] == 9
    assert response.json()["data"]["custom_id"] == "register:submit"
    assert response.json()["data"]["title"] == "設定基本資料"


def test_discord_interactions_handles_modal_submit_and_followup_buttons(tmp_path):
    _setup_runtime(tmp_path, location_options={"A": ["1", "2"], "B": ["1"]})
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    ).hex()
    main.DISCORD_PUBLIC_KEY = public_key
    client = TestClient(main.app)
    payload = {
        "type": 5,
        "data": {
            "custom_id": "register:submit",
            "components": [
                {
                    "components": [
                        {
                            "custom_id": "student_id",
                            "value": "B12345678",
                        }
                    ]
                }
            ],
        },
        "member": {"user": {"id": "45678"}},
    }
    body = json.dumps(payload).encode("utf-8")

    response = client.post(
        "/api/discord/interactions",
        content=body,
        headers=_sign_discord_payload(private_key, body),
    )

    assert response.status_code == 200
    assert response.json()["type"] == 4
    assert "請選擇您在第幾排座位" in response.json()["data"]["content"]
    assert response.json()["data"]["components"][0]["components"][0]["label"] == "A"


def test_discord_interactions_rejects_invalid_signature(tmp_path):
    _setup_runtime(tmp_path)
    main.DISCORD_PUBLIC_KEY = "4d95aca64555a6e56bb315a684a7890407203a3082e5f91abbf4bf1d04c91458"
    client = TestClient(main.app)

    response = client.post(
        "/api/discord/interactions",
        content=json.dumps({"type": 1}).encode("utf-8"),
        headers={
            "x-signature-ed25519": "00",
            "x-signature-timestamp": "1714454100",
            "content-type": "application/json",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Discord signature 驗證失敗"


def test_load_config_prefers_config_directory_default_path(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "queue_config.yaml").write_text(
        "server:\n  port: 9100\nqueue:\n  max_capacity: 88\n",
        encoding="utf-8",
    )
    (tmp_path / "queue_config.yaml").write_text(
        "server:\n  port: 9200\n",
        encoding="utf-8",
    )

    config = load_config()

    assert config["server"]["port"] == 9100
    assert config["queue"]["max_capacity"] == 88


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


def test_load_config_reads_admin_ids_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LINE_ADMIN_IDS", "admin_1, admin_2 ,admin_3")

    config = load_config(str(tmp_path / "missing.yaml"))

    assert config["line_bot"]["admin_ids"] == ["admin_1", "admin_2", "admin_3"]


def test_load_config_reads_new_order_announcement_env(monkeypatch, tmp_path):
    monkeypatch.setenv("NEW_ORDER_ANNOUNCEMENT_TEXT", "/app/audio/new-order.mp3")

    config = load_config(str(tmp_path / "missing.yaml"))

    assert config["tts"]["new_order_announcement_text"] == "/app/audio/new-order.mp3"


def test_load_config_ignores_empty_section_and_keeps_env_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "env-secret")
    monkeypatch.setenv("LINE_CHANNEL_TOKEN", "env-token")
    monkeypatch.setenv("WEB_UI_ADMIN_TOKEN", "env-admin-token")

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "line_bot:\nweb_ui:\n",
        encoding="utf-8",
    )

    config = load_config(str(config_path))

    assert config["line_bot"]["channel_secret"] == "env-secret"
    assert config["line_bot"]["channel_access_token"] == "env-token"
    assert config["web_ui"]["admin_token"] == "env-admin-token"
    assert config["web_ui"]["session_cookie_name"] == "queue_admin_session"


def test_load_config_reads_telegram_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-123")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "secret-xyz")

    config = load_config(str(tmp_path / "missing.yaml"))

    assert config["telegram_bot"]["bot_token"] == "bot-123"
    assert config["telegram_bot"]["webhook_secret"] == "secret-xyz"


def test_load_config_reads_discord_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord-bot-token")
    monkeypatch.setenv("DISCORD_APPLICATION_ID", "discord-app-id")
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", "discord-public-key")

    config = load_config(str(tmp_path / "missing.yaml"))

    assert config["discord_bot"]["bot_token"] == "discord-bot-token"
    assert config["discord_bot"]["application_id"] == "discord-app-id"
    assert config["discord_bot"]["public_key"] == "discord-public-key"


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
    assert '\\"' not in response.text
    assert "* { box-sizing:border-box; }" in response.text
    assert '.legend {' in response.text


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


def test_telegram_webhook_processes_text_command_and_sends_reply(tmp_path, monkeypatch):
    qm = _setup_runtime(tmp_path)
    qm.register_name("5524536015", "B12345678", location="A-1")
    sent = []

    def fake_sender(chat_id: str, text: str, reply_markup=None) -> bool:
        sent.append((chat_id, text, reply_markup))
        return True

    monkeypatch.setattr(main, "_send_telegram_text", fake_sender)
    client = TestClient(main.app)

    response = client.post(
        "/api/telegram/webhook",
        json={
            "message": {
                "message_id": 1,
                "text": "/join",
                "chat": {"id": -5186025491, "type": "group"},
                "from": {"id": 5524536015, "is_bot": False, "first_name": "Alice"},
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["processed_updates"] == 1
    assert response.json()["replies_sent"] == 1
    assert [entry.user_id for entry in qm.get_queue()] == ["5524536015"]
    assert sent == [("-5186025491", sent[0][1], sent[0][2])]
    assert "已加入隊列" in sent[0][1]


def test_telegram_webhook_sends_reply_keyboard_markup(tmp_path, monkeypatch):
    _setup_runtime(tmp_path)
    sent = []

    def fake_sender(chat_id: str, text: str, reply_markup=None) -> bool:
        sent.append((chat_id, text, reply_markup))
        return True

    monkeypatch.setattr(main, "_send_telegram_text", fake_sender)
    client = TestClient(main.app)

    response = client.post(
        "/api/telegram/webhook",
        json={
            "message": {
                "message_id": 1,
                "text": "/menu",
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 45678, "is_bot": False, "first_name": "Alice"},
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["processed_updates"] == 1
    assert response.json()["replies_sent"] == 1
    assert sent[0][0] == "12345"
    assert sent[0][2]["keyboard"][0][0]["text"] == "舉手"
    assert sent[0][2]["is_persistent"] is True


def test_telegram_webhook_sends_inline_keyboard_markup(tmp_path, monkeypatch):
    _setup_runtime(tmp_path)
    sent = []

    def fake_sender(chat_id: str, text: str, reply_markup=None) -> bool:
        sent.append((chat_id, text, reply_markup))
        return True

    monkeypatch.setattr(main, "_send_telegram_text", fake_sender)
    client = TestClient(main.app)

    response = client.post(
        "/api/telegram/webhook",
        json={
            "message": {
                "message_id": 1,
                "text": "/join",
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 45678, "is_bot": False, "first_name": "Alice"},
            }
        },
    )

    assert response.status_code == 200
    assert response.json()["processed_updates"] == 1
    assert response.json()["replies_sent"] == 1
    assert sent[0][2]["inline_keyboard"] == [
        [{"text": "設定基本資料", "callback_data": "/register"}]
    ]


def test_telegram_webhook_processes_callback_query_registration_flow(tmp_path, monkeypatch):
    _setup_runtime(tmp_path, location_options={"A": ["1", "2"], "B": ["1"]})
    sent = []

    def fake_sender(chat_id: str, text: str, reply_markup=None) -> bool:
        sent.append((chat_id, text, reply_markup))
        return True

    monkeypatch.setattr(main, "_send_telegram_text", fake_sender)
    client = TestClient(main.app)

    response1 = client.post(
        "/api/telegram/webhook",
        json={
            "callback_query": {
                "id": "cb-1",
                "data": "/register",
                "from": {"id": 45678, "is_bot": False, "first_name": "Alice"},
                "message": {
                    "message_id": 10,
                    "chat": {"id": 12345, "type": "private"},
                },
            }
        },
    )

    response2 = client.post(
        "/api/telegram/webhook",
        json={
            "message": {
                "message_id": 11,
                "text": "B12345678",
                "chat": {"id": 12345, "type": "private"},
                "from": {"id": 45678, "is_bot": False, "first_name": "Alice"},
            }
        },
    )

    response3 = client.post(
        "/api/telegram/webhook",
        json={
            "callback_query": {
                "id": "cb-2",
                "data": "A",
                "from": {"id": 45678, "is_bot": False, "first_name": "Alice"},
                "message": {
                    "message_id": 12,
                    "chat": {"id": 12345, "type": "private"},
                },
            }
        },
    )

    response4 = client.post(
        "/api/telegram/webhook",
        json={
            "callback_query": {
                "id": "cb-3",
                "data": "1",
                "from": {"id": 45678, "is_bot": False, "first_name": "Alice"},
                "message": {
                    "message_id": 13,
                    "chat": {"id": 12345, "type": "private"},
                },
            }
        },
    )

    assert response1.status_code == 200
    assert response2.status_code == 200
    assert response3.status_code == 200
    assert response4.status_code == 200
    assert sent[0][1] == "請輸入你的學號。"
    assert sent[1][2]["inline_keyboard"] == [[{"text": "A", "callback_data": "A"}, {"text": "B", "callback_data": "B"}]]
    assert sent[2][2]["inline_keyboard"] == [[{"text": "1", "callback_data": "1"}, {"text": "2", "callback_data": "2"}]]
    assert sent[3][1] == "✅ 已更新學號：B12345678\n位置：A-1"


class FakeDashboardAnnouncementService:
    def __init__(self):
        self.payload = {
            "id": "ann-1",
            "text": "來賓 110316888 請準備demo",
            "audioUrl": "/dashboard/audio/ann-1.mp3",
            "createdAt": "2026-04-29T00:00:00",
        }

    def get_latest(self):
        return self.payload


def test_dashboard_data_includes_latest_announcement_payload(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    main.dashboard_announcement_service = FakeDashboardAnnouncementService()
    client = TestClient(main.app)

    response = client.get("/dashboard/data")

    assert response.status_code == 200
    assert response.json()["announcement"]["id"] == "ann-1"
    assert response.json()["announcement"]["audioUrl"] == "/dashboard/audio/ann-1.mp3"


def test_dashboard_page_includes_audio_announcement_player_hooks(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    main.dashboard_announcement_service = FakeDashboardAnnouncementService()
    client = TestClient(main.app)

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "announcement-audio-toggle" in response.text
    assert "announcement-audio-status" in response.text
    assert "announcement-audio" in response.text
    assert "playAnnouncementIfNeeded" in response.text
    assert "payload.announcement" in response.text
    assert "legend-actions" in response.text
    assert "toggle-switch" in response.text
    assert "toggle-track" in response.text
    assert "flex-wrap:nowrap" in response.text


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
    assert "stage-overlay" in page.text
    assert "清除已放置位置" in page.text
    assert "function setLayout(nextLayout)" in page.text
    assert "function syncStageImage()" in page.text
    assert "selected-marker" in page.text
    assert "beforeunload" in page.text
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
    assert 'board-image' in page.text
    assert 'board-overlay' in page.text
    assert 'data-location="1-1"' in page.text
    assert data.json()["layout"]["markers"][0]["location"] == "1-1"
    assert data.json()["layout"]["markers"][1]["location"] == "1-2"


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
    assert "?v=" in payload["imageUrl"]
    image_path = payload["imageUrl"].split("?", 1)[0]
    asset_path = tmp_path / "dashboard_layout" / Path(image_path).name
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
