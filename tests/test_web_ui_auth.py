from __future__ import annotations

import io

from fastapi.testclient import TestClient

import main
from tests.test_main_and_config import _setup_runtime


ADMIN_TOKEN = "secret-token"


def _configure_web_ui_auth(tmp_path, *, protect_read_routes: bool) -> TestClient:
    _setup_runtime(tmp_path, location_options={"1": ["1", "2"]})
    main.config["web_ui"] = {
        "admin_token": ADMIN_TOKEN,
        "protect_read_routes": protect_read_routes,
        "allow_query_token": False,
        "session_cookie_name": "queue_admin_session",
    }
    return TestClient(main.app)


def test_reset_queue_requires_token(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=False)

    response = client.post("/api/queue/reset")

    assert response.status_code == 401


def test_reset_queue_rejects_wrong_token(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=False)

    response = client.post("/api/queue/reset", headers={"X-Admin-Token": "wrong-token"})

    assert response.status_code == 401


def test_reset_queue_accepts_valid_header_token(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=False)

    response = client.post("/api/queue/reset", headers={"X-Admin-Token": ADMIN_TOKEN})

    assert response.status_code == 200
    assert response.json()["status"] == "reset"


def test_dashboard_layout_requires_token_for_write(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=False)

    response = client.post(
        "/dashboard/layout",
        json={"imageUrl": "/dashboard/assets/sample.png", "markers": []},
    )

    assert response.status_code == 401


def test_dashboard_layout_accepts_valid_header_token(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=False)

    response = client.post(
        "/dashboard/layout",
        headers={"X-Admin-Token": ADMIN_TOKEN},
        json={
            "imageUrl": "/dashboard/assets/sample.png",
            "markers": [{"location": "1-1", "x": 12, "y": 24, "label": "Seat A"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["markers"][0]["location"] == "1-1"


def test_dashboard_layout_image_requires_token(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=False)
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

    assert response.status_code == 401


def test_dashboard_read_routes_stay_public_when_protection_disabled(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=False)

    page = client.get("/dashboard")
    data = client.get("/dashboard/data")
    config_page = client.get("/dashboard/config")
    layout = client.get("/dashboard/layout")

    assert page.status_code == 200
    assert data.status_code == 200
    assert config_page.status_code == 200
    assert layout.status_code == 200


def test_dashboard_read_routes_require_token_when_protection_enabled(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=True)

    page = client.get("/dashboard", follow_redirects=False)
    config_page = client.get("/dashboard/config", follow_redirects=False)
    data = client.get("/dashboard/data")
    layout = client.get("/dashboard/layout")

    assert page.status_code in {302, 303}
    assert page.headers["location"] == "/dashboard/login"
    assert config_page.status_code in {302, 303}
    assert config_page.headers["location"] == "/dashboard/login"
    assert data.status_code == 401
    assert layout.status_code == 401


def test_dashboard_read_routes_accept_valid_header_token_when_protection_enabled(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=True)
    headers = {"X-Admin-Token": ADMIN_TOKEN}

    page = client.get("/dashboard", headers=headers)
    data = client.get("/dashboard/data", headers=headers)
    config_page = client.get("/dashboard/config", headers=headers)
    layout = client.get("/dashboard/layout", headers=headers)

    assert page.status_code == 200
    assert data.status_code == 200
    assert config_page.status_code == 200
    assert layout.status_code == 200


def test_query_token_is_rejected_when_disabled(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=True)

    response = client.get(f"/dashboard?token={ADMIN_TOKEN}", follow_redirects=False)

    assert response.status_code in {302, 303}
    assert response.headers["location"] == "/dashboard/login"


def test_query_token_is_accepted_when_enabled(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=True)
    main.config["web_ui"]["allow_query_token"] = True

    response = client.get(f"/dashboard?token={ADMIN_TOKEN}")

    assert response.status_code == 200


def test_dashboard_pages_embed_auth_aware_fetch_helpers(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=True)
    main.config["web_ui"]["allow_query_token"] = True

    dashboard_page = client.get(f"/dashboard?token={ADMIN_TOKEN}")
    config_page = client.get(f"/dashboard/config?token={ADMIN_TOKEN}")

    assert dashboard_page.status_code == 200
    assert config_page.status_code == 200
    assert "function withAuthHeaders" in dashboard_page.text
    assert "function withAuthUrl" in dashboard_page.text
    assert "localStorage.setItem('queue_admin_token'" in dashboard_page.text
    assert "function withAuthHeaders" in config_page.text
    assert "function withAuthUrl" in config_page.text
    assert "X-Admin-Token" in config_page.text


def test_dashboard_login_page_renders_form(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=True)

    response = client.get("/dashboard/login")

    assert response.status_code == 200
    assert "admin token" in response.text.lower()
    assert "<form" in response.text.lower()


def test_dashboard_login_sets_session_cookie_and_redirects(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=True)

    response = client.post(
        "/dashboard/login",
        data={"token": ADMIN_TOKEN},
        follow_redirects=False,
    )

    cookie_name = main.config["web_ui"]["session_cookie_name"]
    cookie_value = response.cookies.get(cookie_name)

    assert response.status_code in {302, 303}
    assert response.headers["location"] == "/dashboard"
    assert cookie_name in response.headers.get("set-cookie", "")
    assert cookie_value
    assert cookie_value != ADMIN_TOKEN


def test_tampered_dashboard_session_cookie_is_rejected(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=True)
    cookie_name = main.config["web_ui"]["session_cookie_name"]

    page = client.get("/dashboard", cookies={cookie_name: "tampered-cookie"}, follow_redirects=False)
    data = client.get("/dashboard/data", cookies={cookie_name: "tampered-cookie"})

    assert page.status_code in {302, 303}
    assert page.headers["location"] == "/dashboard/login"
    assert data.status_code == 401


def test_dashboard_login_rejects_wrong_token(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=True)

    response = client.post("/dashboard/login", data={"token": "wrong-token"})

    assert response.status_code == 401


def test_dashboard_cookie_session_can_access_protected_read_routes(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=True)
    login_response = client.post(
        "/dashboard/login",
        data={"token": ADMIN_TOKEN},
        follow_redirects=False,
    )
    cookie_name = main.config["web_ui"]["session_cookie_name"]
    cookie_value = login_response.cookies.get(cookie_name)

    assert cookie_value

    page = client.get("/dashboard", cookies={cookie_name: cookie_value})
    data = client.get("/dashboard/data", cookies={cookie_name: cookie_value})
    config_page = client.get("/dashboard/config", cookies={cookie_name: cookie_value})

    assert page.status_code == 200
    assert data.status_code == 200
    assert config_page.status_code == 200


def test_dashboard_logout_clears_session_cookie(tmp_path):
    client = _configure_web_ui_auth(tmp_path, protect_read_routes=True)
    login_response = client.post(
        "/dashboard/login",
        data={"token": ADMIN_TOKEN},
        follow_redirects=False,
    )
    cookie_name = main.config["web_ui"]["session_cookie_name"]
    cookie_value = login_response.cookies.get(cookie_name)

    response = client.post("/dashboard/logout", cookies={cookie_name: cookie_value}, follow_redirects=False)

    assert response.status_code in {302, 303}
    assert response.headers["location"] == "/dashboard/login"
    assert f"{cookie_name}=" in response.headers.get("set-cookie", "")
