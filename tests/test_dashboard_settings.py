from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


def test_dashboard_settings_page_and_data_api(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1", "2"]})
    config_path = tmp_path / "config" / "queue_config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            "queue:\n"
            "  max_capacity: 50\n"
            "  special_serve_rules:\n"
            "    enabled: true\n"
            "    match_field: display_name\n"
            "    skip_message: skip\n"
            "    no_next_reply: none\n"
            "    admins:\n"
            "      admin-1:\n"
            "        targets:\n"
            "          - A001\n"
            "registration:\n"
            "  location_options:\n"
            "    '1': ['1', '2']\n"
            "web_ui:\n"
            "  protect_read_routes: false\n"
            "line_bot:\n"
            "  push_on_served: false\n"
        ),
        encoding="utf-8",
    )
    main.CONFIG_FILE_PATH = config_path
    client = TestClient(main.app)

    page = client.get("/settings")
    data = client.get("/settings/data")

    assert page.status_code == 200
    assert "系統設定" in page.text
    assert "settings-form" in page.text
    assert "mode-visual" in page.text
    assert "mode-raw" in page.text
    assert "theme-toggle" in page.text
    assert "THEME_STORAGE_KEY" in page.text
    assert "raw-editor-form" in page.text
    assert "UNSAVED_CHANGES_MESSAGE" in page.text
    assert "beforeunload" in page.text
    assert "restart-app" in page.text
    assert "special-rules-list" in page.text
    assert "location-rows" in page.text
    assert data.status_code == 200
    payload = data.json()
    assert payload["config"]["queue"]["special_serve_rules"]["enabled"] is True
    assert payload["config"]["registration"]["location_options"] == {"1": ["1", "2"]}
    assert payload["meta"]["hotReloadableSections"]["registration"] is True
    assert "special_serve_rules:" in payload["rawYaml"]
    assert "timeout_minutes" not in payload["config"]["queue"]
    assert "timeout_action" not in payload["config"]["queue"]
    assert "coffee_url" not in payload["config"]["vip"]


def test_dashboard_settings_template_avoids_html_injection_patterns(tmp_path):
    _setup_runtime(tmp_path, location_options={"<script>alert(1)</script>": ['"><img src=x onerror=alert(1)>']})
    assert main.db_manager is not None
    main.db_manager.upsert_user_profile('"><svg onload=alert(1)>', "Admin", verified=True, role="admin")
    config_path = tmp_path / "config" / "queue_config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            "queue:\n"
            "  special_serve_rules:\n"
            "    enabled: true\n"
            "    match_field: display_name\n"
            "    skip_message: skip\n"
            "    no_next_reply: none\n"
            "    admins:\n"
            "      '\"><svg onload=alert(1)>':\n"
            "        targets:\n"
            "          - '<img src=x onerror=alert(1)>'\n"
            "registration:\n"
            "  location_options:\n"
            "    '<script>alert(1)</script>': ['\"><img src=x onerror=alert(1)>']\n"
        ),
        encoding="utf-8",
    )
    main.CONFIG_FILE_PATH = config_path
    client = TestClient(main.app)

    page = client.get("/settings")

    assert page.status_code == 200
    assert 'tag.innerHTML = `<span>${value}</span><button type="button">x</button>`;' not in page.text
    assert 'value="${item.admin_id || \'\'}"' not in page.text
    assert 'value="${item.row || \'\'}"' not in page.text


def test_dashboard_settings_requires_login_when_admin_token_is_configured(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    main.config["web_ui"] = {
        "admin_token": "secret-token",
        "protect_read_routes": False,
        "allow_query_token": False,
        "session_cookie_name": "queue_admin_session",
        "session_secret": "session-secret-123",
    }
    client = TestClient(main.app)

    page = client.get("/settings", follow_redirects=False)
    data = client.get("/settings/data", follow_redirects=False)

    assert page.status_code in {302, 303}
    assert page.headers["location"] == "/dashboard/login?next=/settings"
    assert data.status_code == 401


def test_dashboard_settings_save_writes_yaml_and_applies_runtime_updates(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    config_path = tmp_path / "config" / "queue_config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            "queue:\n"
            "  max_capacity: 50\n"
            "registration:\n"
            "  location_options:\n"
            "    '1': ['1']\n"
            "line_bot:\n"
            "  push_on_served: false\n"
        ),
        encoding="utf-8",
    )
    main.CONFIG_FILE_PATH = config_path
    client = TestClient(main.app)

    response = client.post(
        "/settings",
        json={
            "server": {"host": "127.0.0.1", "port": 9001, "debug": True},
            "queue": {
                "max_capacity": 80,
                "special_serve_rules": {
                    "enabled": True,
                    "match_field": "display_name",
                    "skip_message": "skip user",
                    "no_next_reply": "no next",
                    "admins": [{"admin_id": "admin-2", "targets": ["B001", "B002"]}],
                },
            },
            "vip": {"enabled": True, "coffee_price": 90},
            "registration": {
                "location_options": [
                    {"row": "2", "columns": ["1", "3"]},
                    {"row": "3", "columns": ["2"]},
                ]
            },
            "logging": {"level": "DEBUG", "log_file": "logs/custom.log", "max_size_mb": 20, "backup_count": 7},
            "web_ui": {"protect_read_routes": True, "allow_query_token": True, "session_cookie_name": "new_cookie"},
            "line_bot": {"push_on_served": True},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["queue"]["max_capacity"] == 80
    assert body["config"]["registration"]["location_options"] == {"2": ["1", "3"], "3": ["2"]}
    assert body["config"]["queue"]["special_serve_rules"]["admins"]["admin-2"]["targets"] == ["B001", "B002"]
    assert body["meta"]["adminOptions"] == []
    written = config_path.read_text(encoding="utf-8")
    assert "session_cookie_name: new_cookie" in written
    assert "admin-2:" in written
    assert "B001" in written
    assert '  "2": ["1", "3"]' in written or "  '2': ['1', '3']" in written
    assert '  "3": ["2"]' in written or "  '3': ['2']" in written
    assert "timeout_minutes:" not in written
    assert "timeout_action:" not in written
    assert "coffee_url:" not in written
    assert main.LOCATION_OPTIONS == {"2": ["1", "3"], "3": ["2"]}
    assert main.line_handler is not None
    assert main.line_handler.location_options == {"2": ["1", "3"], "3": ["2"]}
    assert main.telegram_command_service is not None
    assert main.telegram_command_service.location_options == {"2": ["1", "3"], "3": ["2"]}
    assert main.discord_command_service is not None
    assert main.discord_command_service.location_options == {"2": ["1", "3"], "3": ["2"]}
    assert main.queue_manager is not None
    assert main.queue_manager.notifier is main.notifier
    assert main._server_bind_config() == ("127.0.0.1", 9001)


def test_dashboard_settings_supports_unset_queue_values_and_admin_options(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    assert main.db_manager is not None
    main.db_manager.upsert_user_profile("admin-1", "Alice Admin", verified=True, role="admin")
    main.db_manager.upsert_user_profile("user-1", "Bob User", verified=True, role="user")
    config_path = tmp_path / "config" / "queue_config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            "queue:\n"
            "  max_capacity:\n"
            "registration:\n"
            "  location_options:\n"
            "    '1': ['1']\n"
        ),
        encoding="utf-8",
    )
    main.CONFIG_FILE_PATH = config_path
    main.config = main.load_config(str(config_path))
    client = TestClient(main.app)

    data = client.get("/settings/data")
    save = client.post(
        "/settings",
        json={
            "server": {"host": "127.0.0.1", "port": 9001, "debug": False},
            "queue": {
                "max_capacity": None,
                "special_serve_rules": {
                    "enabled": True,
                    "match_field": "display_name",
                    "skip_message": "skip",
                    "no_next_reply": "none",
                    "admins": [{"admin_id": "admin-1", "targets": ["A001"]}],
                },
            },
            "vip": {"enabled": True, "coffee_price": 60},
            "registration": {"location_options": [{"row": "1", "columns": ["1"]}]},
            "logging": {"level": "INFO", "log_file": "logs/x.log", "max_size_mb": 10, "backup_count": 2},
            "web_ui": {"protect_read_routes": False, "allow_query_token": False, "session_cookie_name": "cookie"},
            "line_bot": {"push_on_served": False},
        },
    )

    assert data.status_code == 200
    payload = data.json()
    assert payload["meta"]["adminOptions"] == [{"user_id": "admin-1", "display_name": "Alice Admin"}]
    assert payload["config"]["queue"]["max_capacity"] is None
    assert "timeout_minutes" not in payload["config"]["queue"]
    assert "timeout_action" not in payload["config"]["queue"]
    assert save.status_code == 200
    assert save.json()["config"]["queue"]["max_capacity"] is None
    assert "timeout_minutes" not in save.json()["config"]["queue"]
    assert "timeout_action" not in save.json()["config"]["queue"]
    assert save.json()["meta"]["adminOptions"] == [{"user_id": "admin-1", "display_name": "Alice Admin"}]
    assert main.queue_manager is not None
    assert main.queue_manager.get_max_capacity() is None
    written = config_path.read_text(encoding="utf-8")
    assert "max_capacity:" not in written
    assert "timeout_minutes:" not in written
    assert "timeout_action:" not in written


def test_dashboard_settings_raw_save_updates_yaml_and_runtime(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    config_path = tmp_path / "config" / "queue_config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        (
            "queue:\n"
            "  max_capacity: 50\n"
            "registration:\n"
            "  location_options:\n"
            "    '1': ['1']\n"
            "line_bot:\n"
            "  push_on_served: false\n"
        ),
        encoding="utf-8",
    )
    main.CONFIG_FILE_PATH = config_path
    client = TestClient(main.app)

    response = client.post(
        "/settings/raw",
        json={
            "rawYaml": (
                "queue:\n"
                "  max_capacity: 77\n"
                "  special_serve_rules:\n"
                "    enabled: true\n"
                "    match_field: display_name\n"
                "    skip_message: skip raw\n"
                "    no_next_reply: none raw\n"
                "    admins:\n"
                "      raw-admin:\n"
                "        targets:\n"
                "          - RAW001\n"
                "registration:\n"
                "  location_options:\n"
                "    '9': ['1', '2']\n"
                "line_bot:\n"
                "  push_on_served: true\n"
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["config"]["queue"]["max_capacity"] == 77
    assert body["config"]["registration"]["location_options"] == {"9": ["1", "2"]}
    assert "raw-admin:" in body["rawYaml"]
    assert main.LOCATION_OPTIONS == {"9": ["1", "2"]}
    assert main.line_handler is not None
    assert main.line_handler.location_options == {"9": ["1", "2"]}
    assert config_path.read_text(encoding="utf-8").startswith("queue:\n  max_capacity: 77\n")


def test_dashboard_settings_raw_save_rejects_invalid_yaml(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    config_path = tmp_path / "config" / "queue_config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("queue:\n  max_capacity: 50\n", encoding="utf-8")
    main.CONFIG_FILE_PATH = config_path
    client = TestClient(main.app)

    response = client.post(
        "/settings/raw",
        json={"rawYaml": "queue:\n  max_capacity: [\n"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "YAML 格式錯誤"


def test_dashboard_settings_restart_endpoint_requests_process_restart(tmp_path, monkeypatch):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    main.config["web_ui"] = {
        "admin_token": "secret-token",
        "protect_read_routes": False,
        "allow_query_token": False,
        "session_cookie_name": "queue_admin_session",
    }
    called = {"value": False}

    def fake_schedule_process_restart(*, delay_seconds: float = 0.25) -> None:
        called["value"] = True

    monkeypatch.setattr(main, "_schedule_process_restart", fake_schedule_process_restart)
    client = TestClient(main.app)

    response = client.post("/settings/restart", headers={"X-Admin-Token": "secret-token"})

    assert response.status_code == 200
    assert response.json()["status"] == "restarting"
    assert called["value"] is True


def test_dashboard_settings_rejects_invalid_payload(tmp_path):
    _setup_runtime(tmp_path, location_options={"1": ["1"]})
    config_path = tmp_path / "config" / "queue_config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("queue:\n  max_capacity: 50\n", encoding="utf-8")
    main.CONFIG_FILE_PATH = config_path
    client = TestClient(main.app)

    response = client.post(
        "/settings",
        json={
            "server": {"host": "127.0.0.1", "port": 9001, "debug": False},
            "queue": {"max_capacity": 0},
            "vip": {"enabled": True, "coffee_price": 60},
            "registration": {"location_options": [{"row": "1", "columns": ["1"]}]},
            "logging": {"level": "INFO", "log_file": "logs/x.log", "max_size_mb": 10, "backup_count": 2},
            "web_ui": {"protect_read_routes": False, "allow_query_token": False, "session_cookie_name": "cookie"},
            "line_bot": {"push_on_served": False},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "queue.max_capacity 必須大於或等於 1"
