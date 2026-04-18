"""Database manager tests."""

from core.database import DatabaseManager


class TestDatabaseManager:
    """Direct database operation tests."""

    def test_join_queue_assigns_incrementing_numbers(self, db_manager):
        first = db_manager.join_queue("alice", "regular")
        second = db_manager.join_queue("bob", "regular")

        assert first.queue_number == 1
        assert second.queue_number == 2
        assert second.queue_type == "regular"

    def test_join_queue_separate_numbering_for_vip(self, db_manager):
        db_manager.set_config("vip_enabled", "true")
        first = db_manager.join_queue("vip_alice", "vip")
        second = db_manager.join_queue("vip_bob", "vip")

        assert first.queue_number == 1
        assert second.queue_number == 2

    def test_cancel_queue_marks_entry_cancelled(self, db_manager):
        db_manager.join_queue("alice", "regular")

        cancelled = db_manager.cancel_queue("alice")

        assert cancelled is not None
        assert cancelled.user_id == "alice"
        assert cancelled.cancel_time is not None
        assert db_manager.get_regular_queue() == []

    def test_cancel_queue_returns_none_for_missing_user(self, db_manager):
        assert db_manager.cancel_queue("ghost") is None

    def test_serve_queue_marks_entry_served(self, db_manager):
        db_manager.join_queue("alice", "regular")

        served = db_manager.serve_queue("alice")

        assert served is not None
        assert served.user_id == "alice"
        assert served.served is True
        assert served.served_time is not None
        assert db_manager.get_regular_queue() == []

    def test_serve_queue_returns_none_for_missing_user(self, db_manager):
        assert db_manager.serve_queue("ghost") is None

    def test_skip_queue_delegates_to_cancel(self, db_manager):
        db_manager.join_queue("alice", "regular")

        skipped = db_manager.skip_queue("alice")

        assert skipped is not None
        assert skipped.user_id == "alice"
        assert skipped.cancel_time is not None

    def test_get_all_queue_combines_regular_and_vip(self, db_manager):
        db_manager.join_queue("alice", "regular")
        db_manager.join_queue("vip_alice", "vip")

        all_queue = db_manager.get_all_queue()

        assert [entry.user_id for entry in all_queue] == ["alice", "vip_alice"]

    def test_add_vip_purchase_is_not_verified_by_default(self, db_manager):
        purchase = db_manager.add_vip_purchase("alice", platform="line", coffee_id="coffee_1")

        assert purchase.user_id == "alice"
        assert purchase.platform == "line"
        assert purchase.coffee_id == "coffee_1"
        assert db_manager.is_vip_purchased("alice") is False

    def test_log_event_returns_event_record(self, db_manager):
        event = db_manager.log_event("join", "alice", "regular", "details")

        assert event.event_type == "join"
        assert event.user_id == "alice"
        assert event.queue_type == "regular"
        assert event.details == "details"

    def test_config_helpers_return_defaults_and_updates(self, db_manager):
        assert db_manager.get_queue_max_capacity() == 50
        assert db_manager.get_queue_timeout_minutes() == 30
        assert db_manager.is_vip_enabled() is True

        db_manager.set_config("queue_max_capacity", "12")
        db_manager.set_config("queue_timeout_minutes", "45")
        db_manager.set_config("vip_enabled", "false")

        assert db_manager.get_queue_max_capacity() == 12
        assert db_manager.get_queue_timeout_minutes() == 45
        assert db_manager.is_vip_enabled() is False
