"""Additional queue manager tests for uncovered branches."""

from core.queue_manager import QueueManager
from core.database import DatabaseManager


class TestQueueManagerAdditional:
    def test_join_rejects_when_vip_disabled(self, queue_manager):
        queue_manager.db.set_config("vip_enabled", "false")

        result = queue_manager.join("vip_alice", "vip")

        assert result["status"] == "error"
        assert "disabled" in result["message"].lower()

    def test_join_vip_success_after_verified_purchase(self, db_path):
        db = DatabaseManager(db_path)
        db.add_vip_purchase("vip_alice", platform="line", coffee_id="coffee_1")
        db.set_config("vip_enabled", "true")
        with db._connection() as conn:
            conn.execute("UPDATE vip_purchases SET verified = 1 WHERE user_id = ?", ("vip_alice",))
            conn.commit()

        queue_manager = QueueManager(db)
        result = queue_manager.join("vip_alice", "vip")

        assert result["status"] == "success"
        assert result["queue_number"] == 1
        assert result["total_in_queue"] == 1

    def test_skip_specific_missing_user_returns_error(self, queue_manager):
        result = queue_manager.skip_specific("ghost")
        assert result["status"] == "error"
        assert "not in queue" in result["message"].lower()

    def test_skip_specific_invalid_user_returns_error(self, queue_manager):
        result = queue_manager.skip_specific("bad user")
        assert result["status"] == "error"
        assert "invalid" in result["message"].lower()

    def test_serve_specific_invalid_user_returns_error(self, queue_manager):
        result = queue_manager.serve_specific("bad user")
        assert result["status"] == "error"
        assert "invalid" in result["message"].lower()

    def test_cancel_strips_whitespace_from_user_id(self, queue_manager):
        queue_manager.join("alice", "regular")

        result = queue_manager.cancel("  alice  ")

        assert result["status"] == "cancelled"
        assert result["id"] == "alice"

    def test_cancel_invalid_user_returns_error(self, queue_manager):
        result = queue_manager.cancel("bad user")

        assert result["status"] == "error"
        assert "invalid" in result["message"].lower()

    def test_get_status_formats_heads_and_vip_enabled(self, db_path):
        db = DatabaseManager(db_path)
        db.set_config("vip_enabled", "true")
        with db._connection() as conn:
            conn.execute("INSERT INTO vip_purchases (user_id, platform, coffee_id, purchased_at, verified) VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)", ("vip_alice", "line", "coffee_1"))
            conn.commit()

        queue_manager = QueueManager(db)
        queue_manager.join("alice", "regular")
        queue_manager.join("vip_alice", "vip")

        status = queue_manager.get_status()

        assert status["regular_head"] == "user_alice"
        assert status["regular_next"] == "user_alice"
        assert status["vip_next"] == "user_vip_alice"
        assert status["vip_enabled"] is True

    def test_get_queue_returns_all_active_entries(self, queue_manager):
        queue_manager.join("alice", "regular")
        queue_manager.join("bob", "regular")

        queue_entries = queue_manager.get_queue()

        assert [entry.user_id for entry in queue_entries] == ["alice", "bob"]

    def test_set_and_get_max_capacity(self, queue_manager):
        result = queue_manager.set_max_capacity(7)

        assert result == {"status": "ok", "max_capacity": 7}
        assert queue_manager.get_max_capacity() == 7

    def test_serve_next_returns_failed_to_serve_when_db_returns_none(self):
        class StubDB:
            def get_all_queue(self):
                return [type("Entry", (), {"user_id": "alice", "queue_type": "regular", "queue_number": 1})()]

            def serve_queue(self, user_id):
                return None

            def log_event(self, *args, **kwargs):
                raise AssertionError("log_event should not be called")

        queue_manager = QueueManager(StubDB())

        result = queue_manager.serve_next()

        assert result == {"status": "error", "message": "Failed to serve."}

    def test_skip_next_returns_failed_to_skip_when_db_returns_none(self):
        class StubDB:
            def get_all_queue(self):
                return [type("Entry", (), {"user_id": "alice", "queue_type": "regular", "queue_number": 1})()]

            def skip_queue(self, user_id):
                return None

            def log_event(self, *args, **kwargs):
                raise AssertionError("log_event should not be called")

        queue_manager = QueueManager(StubDB())

        result = queue_manager.skip_next()

        assert result == {"status": "error", "message": "Failed to skip."}
