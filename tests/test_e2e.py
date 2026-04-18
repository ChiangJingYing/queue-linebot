"""End-to-end tests for queue system."""

import pytest

from core.queue_manager import QueueManager


class TestEndToEnd:
    """End-to-end tests."""

    def test_full_join_serve_cancel(self, queue_manager):
        """Join -> serve -> check."""
        queue_manager.join("alice", "regular")
        queue_manager.join("bob", "regular")

        served = queue_manager.serve_next()
        assert served["status"] == "served"
        assert served["id"] == "alice"

        status = queue_manager.get_status()
        assert status["regular_count"] == 1

    def test_full_join_status_cancel(self, queue_manager):
        """Join -> status -> cancel."""
        queue_manager.join("alice", "regular")

        status = queue_manager.get_status()
        assert status["regular_count"] == 1

        cancelled = queue_manager.cancel("alice")
        assert cancelled["status"] == "cancelled"
        assert cancelled["new_total"] == 0

    def test_multiple_users_order(self, queue_manager):
        """Multiple users maintain order."""
        queue_manager.join("alice", "regular")
        queue_manager.join("bob", "regular")
        queue_manager.join("charlie", "regular")

        # First serve should be alice
        first = queue_manager.serve_next()
        assert first["id"] == "alice"

        # Second serve should be bob
        second = queue_manager.serve_next()
        assert second["id"] == "bob"

    def test_vip_priority_flow(self, queue_manager):
        """VIP join flow."""
        with queue_manager.db._connection() as conn:
            conn.execute(
                "INSERT INTO vip_purchases (user_id, platform, coffee_id, purchased_at, verified) VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)",
                ("vip_alice", "line", "coffee_1"),
            )
            conn.commit()

        vip_result = queue_manager.join("vip_alice", "vip")
        assert vip_result["status"] == "success"

        status = queue_manager.get_status()
        assert status["vip_count"] == 1

    def test_over_capacity_rejection(self, queue_manager):
        """Over capacity rejection."""
        queue_manager.set_max_capacity(1)
        queue_manager.join("alice", "regular")
        result = queue_manager.join("bob", "regular")
        assert result["status"] == "error"
        assert "full" in result["message"].lower()
