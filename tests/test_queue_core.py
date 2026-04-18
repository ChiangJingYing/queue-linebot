"""Queue core logic tests."""

from core.queue_manager import QueueManager
from core.validators import validate_user_id


class TestJoinQueue:
    """Tests for joining queues."""

    def test_join_regular_queue(self, queue_manager):
        """Normal join to regular queue."""
        result = queue_manager.join("alice", "regular")
        assert result["status"] == "success"
        assert result["queue_number"] == 1
        assert result["position"] == 1
        assert result["total_in_queue"] == 1

    def test_join_regular_second(self, queue_manager):
        """Second person joins queue."""
        queue_manager.join("alice", "regular")
        result = queue_manager.join("bob", "regular")
        assert result["status"] == "success"
        assert result["queue_number"] == 2
        assert result["position"] == 2
        assert result["total_in_queue"] == 2

    def test_join_vip_no_purchase(self, queue_manager):
        """VIP join without coffee purchase -> reject."""
        result = queue_manager.join("non_vip", "vip")
        assert result["status"] == "error"
        assert "購買紀錄" in result["message"]

    def test_join_duplicate_user(self, queue_manager):
        """Duplicate join should return user-friendly error."""
        queue_manager.join("alice", "regular")
        result = queue_manager.join("alice", "regular")
        assert result["status"] == "error"
        assert "重複加入" in result["message"]

    def test_join_over_capacity(self, queue_manager):
        """Queue full -> reject."""
        queue_manager.set_max_capacity(2)
        queue_manager.join("alice", "regular")
        queue_manager.join("bob", "regular")
        result = queue_manager.join("charlie", "regular")
        assert result["status"] == "error"
        assert "已滿" in result["message"]

    def test_join_empty_id(self, queue_manager):
        """Empty ID -> reject."""
        result = queue_manager.join("", "regular")
        assert result["status"] == "error"

    def test_join_special_chars_id(self, queue_manager):
        """Special characters in ID -> reject."""
        result = queue_manager.join("user!@#", "regular")
        assert result["status"] == "error"


class TestCancelQueue:
    """Tests for canceling queue."""

    def test_cancel_exists(self, queue_manager):
        """Normal cancel."""
        queue_manager.join("alice", "regular")
        result = queue_manager.cancel("alice")
        assert result["status"] == "cancelled"
        assert result["id"] == "alice"
        assert result["new_total"] == 0

    def test_cancel_nonexistent(self, queue_manager):
        """Cancel user not in queue -> reject."""
        result = queue_manager.cancel("nobody")
        assert result["status"] == "error"
        assert "不在隊列" in result["message"]

    def test_cancel_already_cancelled(self, queue_manager):
        """Cancel same user twice -> reject second time."""
        queue_manager.join("alice", "regular")
        queue_manager.cancel("alice")
        result = queue_manager.cancel("alice")
        assert result["status"] == "error"


class TestServeQueue:
    """Tests for serving queue."""

    def test_serve_next(self, queue_manager):
        """Serve head of queue."""
        queue_manager.join("alice", "regular")
        queue_manager.join("bob", "regular")
        result = queue_manager.serve_next()
        assert result["status"] == "served"
        assert result["id"] == "alice"
        assert result["queue_number"] == 1

    def test_serve_empty_queue(self, queue_manager):
        """Serve from empty queue -> error."""
        result = queue_manager.serve_next()
        assert result["status"] == "error"
        assert "空" in result["message"]

    def test_serve_resets_numbering(self, queue_manager):
        """After serving, next person gets next number."""
        queue_manager.join("alice", "regular")
        queue_manager.join("bob", "regular")
        queue_manager.serve_next()
        # bob should still be #2
        status = queue_manager.get_status()
        assert status["regular_count"] == 1

    def test_serve_specific(self, queue_manager):
        """Serve specific user."""
        queue_manager.join("alice", "regular")
        queue_manager.join("bob", "regular")
        result = queue_manager.serve_specific("bob")
        assert result["status"] == "served"
        assert result["id"] == "bob"

    def test_serve_specific_not_in_queue(self, queue_manager):
        """Serve user not in queue -> error."""
        result = queue_manager.serve_specific("nobody")
        assert result["status"] == "error"


class TestSkipQueue:
    """Tests for skipping queue."""

    def test_skip_next(self, queue_manager):
        """Skip head of queue."""
        queue_manager.join("alice", "regular")
        queue_manager.join("bob", "regular")
        result = queue_manager.skip_next()
        assert result["status"] == "skipped"
        assert result["id"] == "alice"

    def test_skip_empty_queue(self, queue_manager):
        """Skip from empty queue -> error."""
        result = queue_manager.skip_next()
        assert result["status"] == "error"

    def test_skip_specific(self, queue_manager):
        """Skip specific user."""
        queue_manager.join("alice", "regular")
        queue_manager.join("bob", "regular")
        result = queue_manager.skip_specific("bob")
        assert result["status"] == "skipped"
        assert result["id"] == "bob"


class TestQueueStatus:
    """Tests for queue status."""

    def test_empty_queue_status(self, queue_manager):
        """Empty queue status."""
        status = queue_manager.get_status()
        assert status["regular_count"] == 0
        assert status["vip_count"] == 0

    def test_status_with_regular_queue(self, queue_manager):
        """Status with regular queue."""
        queue_manager.join("alice", "regular")
        status = queue_manager.get_status()
        assert status["regular_count"] == 1
        assert status["regular_head"] == "alice"

    def test_status_with_vip_queue(self, queue_manager):
        """Status with VIP queue."""
        with queue_manager.db._connection() as conn:
            conn.execute(
                "INSERT INTO vip_purchases (user_id, platform, coffee_id, purchased_at, verified) VALUES (?, ?, ?, CURRENT_TIMESTAMP, 1)",
                ("vip_alice", "line", "coffee_1"),
            )
            conn.commit()
        queue_manager.join("vip_alice", "vip")
        status = queue_manager.get_status()
        assert status["vip_count"] == 1
