"""Additional queue manager tests for uncovered branches."""

from datetime import datetime, timedelta

from core.queue_manager import QueueManager
from core.database import DatabaseManager


class TestQueueManagerAdditional:
    def test_join_rejects_when_vip_disabled(self, queue_manager):
        queue_manager.db.set_config("vip_enabled", "false")

        result = queue_manager.join("vip_alice", "vip")

        assert result["status"] == "error"
        assert "停用" in result["message"]

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
        assert "不在隊列" in result["message"]

    def test_skip_specific_invalid_user_returns_error(self, queue_manager):
        result = queue_manager.skip_specific("bad user")
        assert result["status"] == "error"
        assert "格式不正確" in result["message"]

    def test_serve_specific_invalid_user_returns_error(self, queue_manager):
        result = queue_manager.serve_specific("bad user")
        assert result["status"] == "error"
        assert "格式不正確" in result["message"]

    def test_cancel_strips_whitespace_from_user_id(self, queue_manager):
        queue_manager.join("alice", "regular")

        result = queue_manager.cancel("  alice  ")

        assert result["status"] == "cancelled"
        assert result["id"] == "alice"

    def test_cancel_invalid_user_returns_error(self, queue_manager):
        result = queue_manager.cancel("bad user")

        assert result["status"] == "error"
        assert "格式不正確" in result["message"]

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

        assert status["regular_head"] == "alice"
        assert status["regular_next"] == "alice"
        assert status["vip_next"] == "vip_alice"
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

    def test_get_stats_summarizes_today_and_average_wait(self, db_path):
        db = DatabaseManager(db_path)
        db.add_vip_purchase("vip_alice", platform="line", coffee_id="coffee_1")
        with db._connection() as conn:
            conn.execute("UPDATE vip_purchases SET verified = 1 WHERE user_id = ?", ("vip_alice",))
            conn.commit()

        queue_manager = QueueManager(db)
        queue_manager.join("alice", "regular")
        queue_manager.join("bob", "regular")
        queue_manager.join("vip_alice", "vip")
        queue_manager.serve_specific("alice")
        queue_manager.skip_specific("bob")

        with db._connection() as conn:
            base = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
            join_time = base.isoformat()
            served_time = (base + timedelta(minutes=5)).isoformat()
            conn.execute(
                "UPDATE queues SET join_time = ?, served_time = ? WHERE user_id = ?",
                (join_time, served_time, "alice"),
            )
            conn.commit()

        stats = queue_manager.get_stats()

        assert stats["joined_today"] == 3
        assert stats["served_count"] == 1
        assert stats["skipped_count"] == 1
        assert stats["vip"]["active_count"] == 1
        assert stats["average_wait_minutes"] >= 4.5

    def test_get_user_history_returns_latest_events(self, queue_manager):
        queue_manager.join("alice", "regular")
        queue_manager.cancel("alice")

        history = queue_manager.get_user_history("alice")

        assert len(history) >= 2
        assert history[0]["event_type"] in {"join", "cancel"}
        assert {item["event_type"] for item in history} >= {"join", "cancel"}

    def test_export_queue_csv_contains_header_and_rows(self, queue_manager):
        queue_manager.join("alice", "regular")
        csv_data = queue_manager.export_queue_csv()

        assert "user_id,queue_type,queue_number,join_time,cancel_time,served_time,served" in csv_data
        assert "alice,regular,1," in csv_data

    def test_clear_vip_queue_cancels_all_active_vip_entries(self, db_path):
        db = DatabaseManager(db_path)
        for user_id in ("vip_alice", "vip_bob"):
            db.add_vip_purchase(user_id, platform="line", coffee_id=f"coffee_{user_id}")
        with db._connection() as conn:
            conn.execute("UPDATE vip_purchases SET verified = 1")
            conn.commit()

        queue_manager = QueueManager(db)
        queue_manager.join("vip_alice", "vip")
        queue_manager.join("vip_bob", "vip")

        result = queue_manager.clear_vip_queue()

        assert result["removed_count"] == 2
        assert result["removed_users"] == ["vip_alice", "vip_bob"]
        assert db.get_vip_queue() == []

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

        assert result == {"status": "error", "message": "叫號失敗，請稍後再試。"}

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

        assert result == {"status": "error", "message": "跳過失敗，請稍後再試。"}

    def test_clear_all_queue_also_clears_registered_profiles(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "clear-all.db"))
        queue_manager = QueueManager(db)
        queue_manager.register_name("alice", "王小明")
        queue_manager.join("alice", "regular")

        result = queue_manager.clear_all_queue()

        assert result["removed_count"] == 1
        assert result["cleared_profiles_user"] == 1
        assert db.get_user_profile("alice") is None

    def test_clear_all_queue_keeps_admin_role_profiles(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "clear-all-admins.db"))
        queue_manager = QueueManager(db)
        db.upsert_user_profile("admin_a", "管理員甲", location="A-9", verified=True, role="admin")
        db.upsert_user_profile("user_a", "使用者甲", location="A-1", verified=True, role="user")
        queue_manager.join("user_a", "regular")

        result = queue_manager.clear_all_queue()

        assert result["removed_count"] == 1
        assert result["cleared_profiles_user"] == 1
        assert result["kept_admin_profiles"] == 1
        admin_profile = db.get_user_profile("admin_a")
        assert admin_profile is not None
        assert admin_profile.role == "admin"
        assert admin_profile.display_name == ""
        assert admin_profile.location == ""
        assert admin_profile.verified == 0

    def test_ping_user_targets_queue_head_when_missing_id(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "ping-user.db"))
        queue_manager = QueueManager(db)
        queue_manager.register_name("alice", "王小明")
        queue_manager.join("alice", "regular")

        result = queue_manager.ping_user()

        assert result["status"] == "success"
        assert result["user_id"] == "alice"
        assert result["display_name"] == "王小明"
