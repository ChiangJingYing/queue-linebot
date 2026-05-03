from core.database import DatabaseManager
from services.telegram_admin_notifications import (
    TELEGRAM_NOTIFICATION_CATEGORIES,
    TelegramAdminNotificationService,
)


class TestTelegramAdminNotificationPreferencesDB:
    def test_default_preferences_are_all_disabled(self, db_manager: DatabaseManager):
        prefs = db_manager.get_admin_notification_preferences("tg_admin_1")

        assert set(prefs.keys()) == set(TELEGRAM_NOTIFICATION_CATEGORIES)
        assert all(value is False for value in prefs.values())

    def test_set_single_category_preference(self, db_manager: DatabaseManager):
        db_manager.set_admin_notification_preference("tg_admin_1", "join", True)

        prefs = db_manager.get_admin_notification_preferences("tg_admin_1")
        assert prefs["join"] is True
        assert prefs["register"] is False

    def test_set_all_preferences_on(self, db_manager: DatabaseManager):
        db_manager.set_all_admin_notification_preferences("tg_admin_1", True)

        prefs = db_manager.get_admin_notification_preferences("tg_admin_1")
        assert all(value is True for value in prefs.values())

    def test_set_all_preferences_off(self, db_manager: DatabaseManager):
        db_manager.set_all_admin_notification_preferences("tg_admin_1", True)
        db_manager.set_all_admin_notification_preferences("tg_admin_1", False)

        prefs = db_manager.get_admin_notification_preferences("tg_admin_1")
        assert all(value is False for value in prefs.values())

    def test_get_admins_to_notify_filters_by_category_and_admin_role(self, db_manager: DatabaseManager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        db_manager.upsert_user_profile("admin_b", "Admin B", verified=True, role="admin")
        db_manager.upsert_user_profile("user_c", "User C", verified=True, role="user")

        db_manager.set_admin_notification_preference("admin_a", "join", True)
        db_manager.set_admin_notification_preference("admin_b", "register", True)
        db_manager.set_admin_notification_preference("user_c", "join", True)

        targets = db_manager.get_admins_to_notify("join")
        assert targets == ["admin_a"]


class TestTelegramAdminNotificationService:
    def test_broadcast_only_reaches_admins_with_enabled_category(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "telegram-notify.db"))
        db.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        db.upsert_user_profile("admin_b", "Admin B", verified=True, role="admin")
        db.set_admin_notification_preference("admin_a", "join", True)
        db.set_admin_notification_preference("admin_b", "register", True)

        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramAdminNotificationService(db=db, sender=sender)
        delivered = service.broadcast(category="join", message="Alice joined")

        assert delivered == ["admin_a"]
        assert sent == [("admin_a", "Alice joined")]

    def test_serve_broadcast_message_includes_operator_target_and_platform(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "telegram-serve.db"))
        db.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db.set_admin_notification_preference("admin_a", "serve", True)

        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramAdminNotificationService(db=db, sender=sender)
        delivered = service.broadcast_serve_event(
            admin_user_id="admin_operator",
            admin_display_name="管理員乙",
            target_user_id="alice",
            target_display_name="B12345678（A-1）",
            command_text="/admin/serve",
            at_text="2026-04-30 00:30:00",
            platform="Line",
        )

        assert delivered == ["admin_a"]
        assert len(sent) == 1
        _, message = sent[0]
        assert "平台：Line" in message
        assert "管理員乙" in message
        assert "/admin/serve" in message
        assert "B12345678（A-1）" in message
        assert "2026-04-30 00:30:00" in message

    def test_simple_event_broadcast_includes_actor_target_and_platform(self, tmp_path):
        db = DatabaseManager(str(tmp_path / "telegram-event.db"))
        db.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db.set_admin_notification_preference("admin_a", "join", True)

        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramAdminNotificationService(db=db, sender=sender)
        delivered = service.broadcast_event(
            category="join",
            title="排隊通知",
            actor_label="使用者：B12345678（A-1）",
            target_label="隊列：regular",
            detail_lines=["時間：2026-04-30 00:55:00"],
            platform="Discord",
        )

        assert delivered == ["admin_a"]
        assert len(sent) == 1
        _, message = sent[0]
        assert "排隊通知" in message
        assert "平台：Discord" in message
        assert "使用者：B12345678（A-1）" in message
        assert "隊列：regular" in message
        assert "時間：2026-04-30 00:55:00" in message
