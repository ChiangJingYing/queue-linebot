from __future__ import annotations

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


ADMIN_TOKEN = "secret-token"


def _client_with_auth_enabled(tmp_path) -> TestClient:
    _setup_runtime(tmp_path, location_options={"1": ["1", "2"]})
    main.config["web_ui"] = {
        "admin_token": ADMIN_TOKEN,
        "protect_read_routes": True,
        "allow_query_token": False,
        "session_cookie_name": "queue_admin_session",
        "session_secret": "session-secret-123",
    }
    return TestClient(main.app)


def test_dashboard_login_to_logout_smoke_flow(tmp_path):
    client = _client_with_auth_enabled(tmp_path)

    login_page = client.get("/dashboard/login")
    assert login_page.status_code == 200

    unauth_dashboard = client.get("/dashboard", follow_redirects=False)
    assert unauth_dashboard.status_code in {302, 303}
    assert unauth_dashboard.headers["location"] == "/dashboard/login?next=/dashboard"

    login = client.post("/dashboard/login", data={"token": ADMIN_TOKEN}, follow_redirects=False)
    assert login.status_code in {302, 303}
    assert login.headers["location"] == "/dashboard"

    dashboard = client.get("/dashboard")
    data = client.get("/dashboard/data")
    config_page = client.get("/dashboard/config")
    layout = client.get("/dashboard/layout")

    assert dashboard.status_code == 200
    assert data.status_code == 200
    assert config_page.status_code == 200
    assert layout.status_code == 200

    save_layout = client.post(
        "/dashboard/layout",
        json={
            "imageUrl": "/dashboard/assets/sample.png",
            "markers": [{"location": "1-1", "x": 10, "y": 20, "label": "Seat 1"}],
        },
    )
    assert save_layout.status_code == 200
    assert save_layout.json()["markers"][0]["location"] == "1-1"

    logout = client.post("/dashboard/logout", follow_redirects=False)
    assert logout.status_code in {302, 303}
    assert logout.headers["location"] == "/dashboard/login"

    after_logout_dashboard = client.get("/dashboard", follow_redirects=False)
    after_logout_data = client.get("/dashboard/data")
    assert after_logout_dashboard.status_code in {302, 303}
    assert after_logout_dashboard.headers["location"] == "/dashboard/login?next=/dashboard"
    assert after_logout_data.status_code == 401
