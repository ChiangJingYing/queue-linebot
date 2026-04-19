"""Tests for /admin/join toggle feature (TDD)."""

from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.vip_service import VipService
from bot.handler import LineBotHandler


# ----------------------------------------------------------------
# Database layer tests
# ----------------------------------------------------------------

class TestQueueEnabled:
    """Test is_queue_enabled() and set_config('queue_enabled')."""

    def test_default_is_enabled(self, db_manager: DatabaseManager):
        """Default queue_enabled should be True."""
        assert db_manager.is_queue_enabled() is True

    def test_set_disable(self, db_manager: DatabaseManager):
        """Setting queue_enabled to false returns False."""
        db_manager.set_config("queue_enabled", "false")
        assert db_manager.is_queue_enabled() is False

    def test_set_enable(self, db_manager: DatabaseManager):
        """Setting queue_enabled back to true returns True."""
        db_manager.set_config("queue_enabled", "false")
        db_manager.set_config("queue_enabled", "true")
        assert db_manager.is_queue_enabled() is True


# ----------------------------------------------------------------
# Queue manager layer tests
# ----------------------------------------------------------------

class TestJoinToggle:
    """Test join() gates on queue_enabled."""

    def test_join_when_enabled(self, queue_manager: QueueManager):
        """When enabled, join() succeeds normally."""
        queue_manager.db.set_config("queue_enabled", "true")
        result = queue_manager.join("alice", "regular")
        assert result["status"] == "success"

    def test_join_when_disabled(self, queue_manager: QueueManager):
        """When disabled, join() is rejected."""
        queue_manager.db.set_config("queue_enabled", "false")
        result = queue_manager.join("alice", "regular")
        assert result["status"] == "error"
        assert "隊列已關閉" in result["message"]

    def test_vip_join_when_disabled(self, queue_manager: QueueManager):
        """VIP join is also blocked when queue is disabled."""
        queue_manager.db.add_vip_purchase("vip_alice", platform="line", coffee_id="coffee_1", verified=True)
        queue_manager.db.set_config("queue_enabled", "false")
        result = queue_manager.join("vip_alice", "vip")
        assert result["status"] == "error"
        assert "隊列已關閉" in result["message"]

    def test_set_queue_enabled_true(self, queue_manager: QueueManager):
        """set_queue_enabled(True) persists and reads back."""
        queue_manager.db.set_config("queue_enabled", "false")
        queue_manager.set_queue_enabled(True)
        assert queue_manager.get_queue_enabled() is True

    def test_set_queue_enabled_false(self, queue_manager: QueueManager):
        """set_queue_enabled(False) persists and reads back."""
        queue_manager.db.set_config("queue_enabled", "true")
        queue_manager.set_queue_enabled(False)
        assert queue_manager.get_queue_enabled() is False

    def test_get_queue_enabled(self, queue_manager: QueueManager):
        """Default state is enabled."""
        assert queue_manager.get_queue_enabled() is True

    def test_join_still_respects_vip_requirement_when_enabled(self, queue_manager: QueueManager):
        """Even when enabled, VIP still requires purchase."""
        queue_manager.db.set_config("queue_enabled", "true")
        result = queue_manager.join("non_vip", "vip")
        assert result["status"] == "error"
        assert "VIP 購買紀錄" in result["message"]


# ----------------------------------------------------------------
# Bot handler layer tests
# ----------------------------------------------------------------

class TestAdminJoinToggle:
    """Test /admin/join toggle/status commands via handler."""

    def test_admin_join_off(self, tmp_path):
        """Admin sends /admin/join off → queue disabled."""
        db = DatabaseManager(str(tmp_path / "toggle.db"))
        qm = QueueManager(db)
        handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

        result = handler.handle_event(make_event("/admin/join off", user_id="admin"))
        assert "關閉" in reply_texts(result)[0]

    def test_admin_join_on(self, tmp_path):
        """Admin sends /admin/join on → queue enabled."""
        db = DatabaseManager(str(tmp_path / "toggle2.db"))
        qm = QueueManager(db)
        qm.db.set_config("queue_enabled", "false")
        handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

        result = handler.handle_event(make_event("/admin/join on", user_id="admin"))
        assert "開啟" in reply_texts(result)[0]

    def test_admin_join_toggle_no_arg(self, tmp_path):
        """/admin/join without args → toggle state (enabled → disabled)."""
        db = DatabaseManager(str(tmp_path / "toggle3.db"))
        qm = QueueManager(db)
        handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

        result = handler.handle_event(make_event("/admin/join", user_id="admin"))
        assert "關閉" in reply_texts(result)[0]

    def test_admin_join_toggle_back(self, tmp_path):
        """/admin/join toggle from disabled → enabled."""
        db = DatabaseManager(str(tmp_path / "toggle3b.db"))
        qm = QueueManager(db)
        qm.db.set_config("queue_enabled", "false")
        handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

        result = handler.handle_event(make_event("/admin/join", user_id="admin"))
        assert "開啟" in reply_texts(result)[0]

    def test_admin_join_invalid_arg(self, tmp_path):
        """/admin/join invalid arg → error."""
        db = DatabaseManager(str(tmp_path / "toggle4.db"))
        qm = QueueManager(db)
        handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

        result = handler.handle_event(make_event("/admin/join maybe", user_id="admin"))
        assert "on/off" in reply_texts(result)[0].lower()

    def test_admin_join_status(self, tmp_path):
        """/admin/join status → shows current state."""
        db = DatabaseManager(str(tmp_path / "toggle5.db"))
        qm = QueueManager(db)
        handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

        result = handler.handle_event(make_event("/admin/join status", user_id="admin"))
        assert "隊列狀態" in reply_texts(result)[0]

    def test_non_admin_reject(self, tmp_path):
        """Non-admin /admin/join off → denied."""
        db = DatabaseManager(str(tmp_path / "toggle6.db"))
        qm = QueueManager(db)
        handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

        result = handler.handle_event(make_event("/admin/join off", user_id="alice"))
        assert "未授權" in reply_texts(result)[0]

    def test_join_blocked_when_disabled(self, tmp_path):
        """When disabled, /join returns error."""
        db = DatabaseManager(str(tmp_path / "toggle7.db"))
        qm = QueueManager(db)
        qm.db.set_config("queue_enabled", "false")
        qm.register_name("alice", "Alice", location="A-1")
        handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

        result = handler.handle_event(make_event("/join", user_id="alice"))
        assert "隊列已關閉" in reply_texts(result)[0]

    def test_join_allowed_when_enabled(self, tmp_path):
        """When enabled, /join works normally."""
        db = DatabaseManager(str(tmp_path / "toggle8.db"))
        qm = QueueManager(db)
        qm.db.set_config("queue_enabled", "true")
        qm.register_name("alice", "Alice", location="A-1")
        handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

        result = handler.handle_event(make_event("/join", user_id="alice"))
        assert "加入隊列成功" in reply_texts(result)[0]

    def test_full_enable_disable_enable(self, tmp_path):
        """Off → on → back and check joins."""
        db = DatabaseManager(str(tmp_path / "toggle_e2e.db"))
        qm = QueueManager(db)
        handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

        # Turn off
        off = handler.handle_event(make_event("/admin/join off", user_id="admin"))
        assert "關閉" in reply_texts(off)[0]

        # Try to join -> should fail
        db2 = DatabaseManager(str(tmp_path / "toggle_e2e2.db"))
        qm2 = QueueManager(db2)
        qm2.register_name("alice", "Alice", location="A-1")
        handler2 = LineBotHandler(queue_manager=qm2, admin_ids=["admin"])
        handler2.queue_manager.db.set_config("queue_enabled", "false")
        blocked = handler2.handle_event(make_event("/join", user_id="alice"))
        assert "隊列已關閉" in reply_texts(blocked)[0]

        # Turn back on
        on = handler.handle_event(make_event("/admin/join on", user_id="admin"))
        assert "開啟" in reply_texts(on)[0]


# ----------------------------------------------------------------
# Helper functions
# ----------------------------------------------------------------

from types import SimpleNamespace


def make_event(text: str, user_id: str = "alice", reply_token: str = "reply-token"):
    return SimpleNamespace(
        message=SimpleNamespace(type="text", text=text),
        source=SimpleNamespace(userId=user_id),
        reply_token=reply_token,
    )


def reply_texts(result):
    return [item["text"] if isinstance(item, dict) else getattr(item, "text", "") for item in result]
