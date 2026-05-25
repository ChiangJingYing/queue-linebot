"""Tests for dashboard stats panel and reset endpoint."""
from fastapi.testclient import TestClient


def _get_stats(client: TestClient) -> dict:
    response = client.get("/dashboard/data")
    assert response.status_code == 200
    return response.json()["stats"]


def _register(qm, user_id: str, display_name: str, location: str) -> None:
    result = qm.register_name(user_id, display_name, location)
    assert result["status"] == "success"


class TestDashboardStats:
    """Test /dashboard/data stats payload and dashboard rendering."""

    def test_dashboard_data_has_stats_field(self, client: TestClient):
        response = client.get("/dashboard/data")
        assert response.status_code == 200
        data = response.json()
        assert "stats" in data
        assert data["stats"] == {"registered": 0, "queue": 0, "served": 0}

    def test_dashboard_stats_registered_queue_served_counts(self, client: TestClient):
        import main
        qm = main.queue_manager
        _register(qm, "alice", "Alice A", "A-1")
        _register(qm, "bob", "Bob B", "A-2")
        qm.join("alice", "regular")
        qm.join("bob", "regular")
        qm.serve_next()

        response = client.get("/dashboard/data")
        assert response.status_code == 200
        payload = response.json()
        stats = payload["stats"]
        assert stats["registered"] == 2
        assert stats["queue"] == 1
        assert stats["served"] == 1
        assert payload["served_recent"][0]["user_id"] == "alice"
        assert payload["served_recent"][0]["location"] == "A-1"

    def test_dashboard_stats_queue_includes_vip(self, client: TestClient):
        import main
        qm = main.queue_manager
        qm.db.set_config("vip_enabled", "true")
        qm.db.add_vip_purchase("vip_alice", "line", "coffee1", True)
        _register(qm, "vip_alice", "VIP Alice", "B-1")

        result = qm.join("vip_alice", "vip")
        assert result["status"] == "success"

        stats = _get_stats(client)
        assert stats["registered"] == 1
        assert stats["queue"] == 1
        assert stats["served"] == 0

    def test_dashboard_stats_cancel_does_not_increase_served_count(self, client: TestClient):
        import main
        qm = main.queue_manager
        _register(qm, "alice", "Alice A", "A-1")
        qm.join("alice", "regular")
        qm.cancel("alice")

        stats = _get_stats(client)
        assert stats["registered"] == 1
        assert stats["queue"] == 0
        assert stats["served"] == 0

    def test_dashboard_page_renders_stats_panel(self, client: TestClient):
        response = client.get("/dashboard")
        assert response.status_code == 200
        assert 'stats-panel' in response.text
        assert 'id="stat-registered"' in response.text
        assert 'id="stat-queue"' in response.text
        assert 'id="stat-served"' in response.text
        assert 'id="served-tooltip-body"' in response.text
        assert '最近已叫號（最新在上）' in response.text

    def test_dashboard_data_served_recent_latest_first_max_five(self, client: TestClient):
        import main
        qm = main.queue_manager
        for idx in range(6):
            user_id = f"u{idx}"
            _register(qm, user_id, f"User {idx}", f"A-{idx}")
            qm.join(user_id, "regular")
            qm.serve_next()

        response = client.get("/dashboard/data")
        assert response.status_code == 200
        served_recent = response.json()["served_recent"]
        assert len(served_recent) == 5
        assert served_recent[0]["user_id"] == "u5"
        assert served_recent[-1]["user_id"] == "u1"

    def test_dashboard_data_served_recent_hides_duplicate_served_rows(self, client: TestClient):
        import main
        qm = main.queue_manager
        _register(qm, "alice", "Alice A", "A-1")
        served_time = "2026-05-25T10:00:00+08:00"
        with qm.db._connection() as conn:
            conn.execute(
                "INSERT INTO queues (user_id, queue_type, queue_number, join_time, served_time, served) "
                "VALUES (?, 'regular', 1, ?, ?, 1)",
                ("alice", "2026-05-25T09:50:00+08:00", served_time),
            )
            conn.execute(
                "INSERT INTO queues (user_id, queue_type, queue_number, join_time, served_time, served) "
                "VALUES (?, 'regular', 2, ?, ?, 1)",
                ("alice", "2026-05-25T09:51:00+08:00", served_time),
            )
            conn.commit()

        response = client.get("/dashboard/data")

        assert response.status_code == 200
        served_recent = response.json()["served_recent"]
        assert len(served_recent) == 1
        assert served_recent[0]["user_id"] == "alice"
        assert served_recent[0]["served_time"] == "2026-05-25 10:00"


class TestResetEndpoint:
    """Test POST /api/queue/reset clears queue/profile/served data."""

    def test_reset_empty_queue(self, client: TestClient):
        response = client.post("/api/queue/reset")
        assert response.status_code == 200
        assert response.json()["status"] == "reset"
        assert response.json()["removed_count"] == 0
        assert _get_stats(client) == {"registered": 0, "queue": 0, "served": 0}

    def test_reset_clears_queue_profiles_and_served(self, client: TestClient):
        import main
        qm = main.queue_manager
        _register(qm, "alice", "Alice A", "A-1")
        _register(qm, "bob", "Bob B", "A-2")
        qm.join("alice", "regular")
        qm.join("bob", "regular")
        qm.serve_next()

        stats_before = _get_stats(client)
        assert stats_before == {"registered": 2, "queue": 1, "served": 1}

        response = client.post("/api/queue/reset")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "reset"
        assert payload["removed_count"] == 1
        assert payload["cleared_profiles"] == 2
        assert payload["cleared_served"] >= 2

        stats_after = _get_stats(client)
        assert stats_after == {"registered": 0, "queue": 0, "served": 0}

    def test_dashboard_config_has_reset_button(self, client: TestClient):
        response = client.get("/dashboard/config")
        assert response.status_code == 200
        assert 'id="reset-layout"' in response.text
        assert '/dashboard/layout/reset' in response.text
        assert '清除已放置位置' in response.text
