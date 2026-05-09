"""Database manager tests."""

from datetime import datetime
from datetime import timezone

from core.database import DatabaseManager
from core.time_utils import TAIPEI_TZ, format_display_time


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

    def test_user_can_rejoin_after_cancel(self, db_manager):
        first = db_manager.join_queue("alice", "regular")
        cancelled = db_manager.cancel_queue("alice")
        second = db_manager.join_queue("alice", "regular")

        assert first.user_id == "alice"
        assert cancelled is not None
        assert second.user_id == "alice"
        assert second.queue_number >= 1
        assert db_manager.get_active_queue_entry("alice") is not None

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

    def test_clear_all_user_profiles_keeps_all_admin_roles_but_clears_dashboard_fields(self, db_manager):
        db_manager.upsert_user_profile("config_admin", "Config Admin", location="A-1", verified=True, role="admin")
        db_manager.upsert_user_profile("dynamic_admin", "Dynamic Admin", location="B-1", verified=True, role="admin")
        db_manager.upsert_user_profile("regular_user", "Regular User", location="C-1", role="user")

        cleared_user_count, kept_admin_count = db_manager.clear_all_user_profiles(keep_user_ids={"config_admin"})

        assert cleared_user_count == 1
        assert kept_admin_count == 2

        config_profile = db_manager.get_user_profile("config_admin")
        assert config_profile is not None
        assert config_profile.role == "admin"
        assert config_profile.display_name == ""
        assert config_profile.location == ""
        assert config_profile.verified == 0

        dynamic_profile = db_manager.get_user_profile("dynamic_admin")
        assert dynamic_profile is not None
        assert dynamic_profile.role == "admin"
        assert dynamic_profile.display_name == ""
        assert dynamic_profile.location == ""
        assert dynamic_profile.verified == 0

        assert db_manager.get_user_profile("regular_user") is None

    def test_format_display_time_treats_naive_timestamp_as_taipei_time(self):
        value = "2026-04-30T10:12:00"

        rendered = format_display_time(value)

        assert rendered == "2026-04-30 10:12"

    def test_join_queue_stores_taipei_timezone_timestamp(self, db_manager):
        entry = db_manager.join_queue("alice", "regular")

        parsed = datetime.fromisoformat(entry.join_time)

        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == TAIPEI_TZ.utcoffset(None)

    def test_format_display_time_converts_utc_timestamp_to_taipei_time(self):
        value = "2026-04-30T02:12:00+00:00"

        rendered = format_display_time(value)

        assert rendered == "2026-04-30 10:12"


class TestLocationAndForceReleaseMethods:
    """Tests for find_user_profile_by_location, find_called_user_by_location, force_release_queue."""

    def test_find_user_profile_by_location_returns_profile_when_found(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "find-profile-loc.db"))
        db.upsert_user_profile("alice", "王小明", location="A-1", verified=True, role="user")

        profile = db.find_user_profile_by_location("A-1")

        assert profile is not None
        assert profile.user_id == "alice"
        assert profile.location == "A-1"

    def test_find_user_profile_by_location_returns_none_when_not_found(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "find-profile-loc-miss.db"))

        profile = db.find_user_profile_by_location("Z-9")

        assert profile is None

    def test_find_called_user_by_location_returns_entry_when_user_is_called(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "find-called-loc.db"))
        db.upsert_user_profile("alice", "王小明", location="A-1", verified=True, role="user")
        db.join_queue("alice", "regular")
        db.serve_queue("alice")

        entry = db.find_called_user_by_location("A-1")

        assert entry is not None
        assert entry.user_id == "alice"
        assert entry.release_time is None

    def test_find_called_user_by_location_returns_none_when_not_called(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "find-called-loc-miss.db"))
        db.upsert_user_profile("alice", "王小明", location="A-1", verified=True, role="user")

        entry = db.find_called_user_by_location("A-1")

        assert entry is None

    def test_force_release_queue_sets_release_time_and_served_flag(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "force-release.db"))
        db.join_queue("alice", "regular")

        released = db.force_release_queue("alice")

        assert released is not None
        assert released.user_id == "alice"
        assert released.served == 1
        # verify release_time is persisted in DB
        called = db.get_called_entry("alice")
        assert called is None  # no longer in called state after release

    def test_force_release_queue_returns_none_when_no_queue_entry(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "force-release-empty.db"))

        released = db.force_release_queue("ghost")

        assert released is None
