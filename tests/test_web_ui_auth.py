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

    for path in ["/dashboard", "/dashboard/data", "/dashboard/config", "/dashboard/layout"]:
        response = client.get(path)
        assert response.status_code == 401


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

    response = client.get(f"/dashboard?token={ADMIN_TOKEN}")

    assert response.status_code == 401
