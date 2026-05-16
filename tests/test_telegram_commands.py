from services.telegram_admin_notifications import TELEGRAM_NOTIFICATION_CATEGORIES
from services.telegram_commands import TelegramCommandService
import services.telegram_commands as telegram_commands_module
from unittest.mock import patch


class TestTelegramCommandService:
    def test_user_reply_keyboard_matches_rich_menu(self, db_manager):
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="tg_user_1", text="/menu")

        assert result["status"] == "success"
        keyboard = result["reply_markup"]["keyboard"]
        assert keyboard == [
            [{"text": "舉手"}, {"text": "放棄"}, {"text": "看狀態"}],
            [{"text": "看紀錄"}, {"text": "設定資料"}, {"text": "排隊紀錄"}],
        ]
        assert result["reply_markup"]["resize_keyboard"] is True
        assert result["reply_markup"]["is_persistent"] is True

    def test_admin_reply_keyboard_matches_rich_menu_page1(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/menu")

        assert result["status"] == "success"
        assert result["reply_markup"]["keyboard"] == [
            [{"text": "叫號"}, {"text": "提醒"}, {"text": "完整狀態"}],
            [{"text": "開關排隊"}, {"text": "更多功能"}],
        ]

    def test_admin_notification_menu_is_exposed_on_admin_reply_keyboard_page2(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="更多功能")

        assert result["status"] == "success"
        assert result["reply_markup"]["keyboard"] == [
            [{"text": "清空隊列"}, {"text": "VIP 狀態"}, {"text": "推播設定"}],
            [{"text": "幫助"}, {"text": "返回主選單"}],
        ]

    def test_non_admin_pressing_stale_admin_reply_button_refreshes_user_menu(self, db_manager):
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="user_a", text="推播設定")

        assert result["status"] == "error"
        assert "已切回一般功能選單" in result["message"]
        assert result["reply_markup"]["keyboard"] == [
            [{"text": "舉手"}, {"text": "放棄"}, {"text": "看狀態"}],
            [{"text": "看紀錄"}, {"text": "設定資料"}, {"text": "排隊紀錄"}],
        ]

    def test_admin_notification_menu_opens_inline_keyboard_for_all_categories(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="推播設定")

        assert result["status"] == "success"
        assert result["message"] == "🔔 請選擇要設定的 Telegram 推播項目"
        inline_rows = result["reply_markup"]["inline_keyboard"]
        flat = [button["callback_data"] for row in inline_rows for button in row]
        assert "notify:all:on" in flat
        assert "notify:all:off" in flat
        for category in TELEGRAM_NOTIFICATION_CATEGORIES:
            assert f"notify:{category}:toggle" in flat


    def test_join_requires_registration_before_queueing_with_inline_keyboard(self, db_manager):
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="tg_user_1", text="/join")

        assert result["status"] == "error"
        assert result["message"] == "❌ 錯誤：請先完成註冊（學號與座位）後再加入隊列。"
        assert result["reply_markup"]["inline_keyboard"] == [
            [{"text": "設定基本資料", "callback_data": "/register"}]
        ]

    def test_cancel_when_queue_closed_requires_double_confirmation_and_can_abort(self, db_manager):
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)
        service.handle_text(user_id="alice", text="/join")
        db_manager.set_config("queue_enabled", "false")

        first = service.handle_text(user_id="alice", text="/cancel")

        assert first["status"] == "pending"
        assert first["message"] == "當前隊列已關閉，確定要放棄嗎？\n若放棄無法再加入到隊列中！"
        assert first["reply_markup"]["inline_keyboard"] == [
            [
                {"text": "確認放棄", "callback_data": "確認放棄"},
                {"text": "取消放棄", "callback_data": "取消放棄"},
            ]
        ]

        second = service.handle_text(user_id="alice", text="確認放棄")

        assert second["status"] == "pending"
        assert second["message"] == "您確定要放棄嗎？"
        assert service.queue_manager.get_user_position("alice") == 1

        abort_result = service.handle_text(user_id="alice", text="取消放棄")

        assert abort_result["status"] == "success"
        assert abort_result["message"] == "好的，已取消放棄"
        assert service.queue_manager.get_user_position("alice") == 1

    def test_cancel_when_queue_closed_second_confirmation_cancels_queue_entry(self, db_manager):
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)
        service.handle_text(user_id="alice", text="/join")
        db_manager.set_config("queue_enabled", "false")

        service.handle_text(user_id="alice", text="/cancel")
        service.handle_text(user_id="alice", text="確認放棄")
        final = service.handle_text(user_id="alice", text="確認放棄")

        assert final["status"] == "success"
        assert final["message"] == "✅ 已取消排隊"
        assert service.queue_manager.get_user_position("alice") is None

    def test_callback_text_register_opens_interactive_registration(self, db_manager):
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="tg_user_1", text="/register")

        assert result["status"] == "pending"
        assert result["message"] == "請輸入你的學號。"

    def test_status_reports_current_position(self, db_manager):
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        db_manager.upsert_user_profile("bob", "B23456789", location="A-2", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)
        service.handle_text(user_id="alice", text="/join")
        service.handle_text(user_id="bob", text="/join")

        result = service.handle_text(user_id="bob", text="/status")

        assert result["status"] == "success"
        assert "目前排在第 2 位" in result["message"]
        assert "前面還有 1 人" in result["message"]

    def test_history_returns_recent_user_events(self, db_manager):
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)
        service.handle_text(user_id="alice", text="/join")
        service.handle_text(user_id="alice", text="/cancel")

        result = service.handle_text(user_id="alice", text="/history")

        assert result["status"] == "success"
        assert "歷史紀錄" in result["message"]
        assert "join" in result["message"]
        assert "cancel" in result["message"]

    def test_status_reports_total_count_when_user_not_in_queue(self, db_manager):
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)
        service.handle_text(user_id="alice", text="/join")

        result = service.handle_text(user_id="bob", text="/status")

        assert result["status"] == "success"
        assert result["message"] == "📊 目前有 1 人在排隊中"

    def test_history_returns_empty_shared_message_when_no_history(self, db_manager):
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="alice", text="/history")

        assert result["status"] == "success"
        assert result["message"] == "查無排隊歷史紀錄。"

    def test_help_is_admin_only(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        service = TelegramCommandService(db=db_manager)

        denied = service.handle_text(user_id="alice", text="/help")
        allowed = service.handle_text(user_id="admin_a", text="/help")

        assert denied == {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}
        assert allowed["status"] == "success"
        assert "/admin/serve - 叫下一位" in allowed["message"]
        assert "/admin/ping - 手動提醒下一位" in allowed["message"]
        assert "/admin/status - 完整狀態" in allowed["message"]

    def test_help_uses_shared_register_wording(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/help")

        assert "/register - 依提示完成學號與座位註冊" in result["message"]

    def test_register_enters_interactive_flow_and_completes_with_inline_keyboards(self, db_manager):
        service = TelegramCommandService(db=db_manager, location_options={"A": ["1", "2"], "B": ["1"]})

        step1 = service.handle_text(user_id="tg_user_1", text="/register")
        assert step1["status"] == "pending"
        assert step1["message"] == "請輸入你的學號。"

        step2 = service.handle_text(user_id="tg_user_1", text="B12345678")
        assert step2["status"] == "pending"
        assert "請選擇您在第幾排座位" in step2["message"]
        assert step2["reply_markup"]["inline_keyboard"] == [
            [{"text": "A", "callback_data": "register:group:A"}, {"text": "B", "callback_data": "register:group:B"}]
        ]

        step3 = service.handle_text(user_id="tg_user_1", text="register:group:A")
        assert step3["status"] == "pending"
        assert "請選擇您的座位（A-?）" in step3["message"]
        assert step3["reply_markup"]["inline_keyboard"] == [
            [{"text": "1", "callback_data": "register:item:1"}, {"text": "2", "callback_data": "register:item:2"}]
        ]

        step4 = service.handle_text(user_id="tg_user_1", text="register:item:1")
        assert step4["status"] == "success"
        assert step4["message"] == "✅ 已更新學號：B12345678\n位置：A-1"
        profile = db_manager.get_user_profile("tg_user_1")
        assert profile is not None
        assert profile.display_name == "B12345678"
        assert profile.location == "A-1"

    def test_register_rejects_inline_args_and_requires_interactive_flow(self, db_manager):
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="tg_user_1", text="/register B12345678 A-1")

        assert result["status"] == "error"
        assert "/register 不接受參數" in result["message"]

    def test_admin_apply_submits_application(self, db_manager):
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(
            user_id="tg_admin_candidate",
            text="/admin/apply 王小明",
        )

        assert result["status"] == "success"
        assert "已提交" in result["message"]
        pending = db_manager.get_pending_applications()
        assert any(row["user_id"] == "tg_admin_candidate" for row in pending)

    def test_admin_apply_requires_display_name(self, db_manager):
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="tg_admin_candidate", text="/admin/apply")

        assert result["status"] == "error"
        assert "用法" in result["message"]

    def test_admin_apply_list_routes_to_admin_subcommand(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        db_manager.upsert_user_profile("tg_user_1", "B12345678", verified=True, role="user")
        db_manager.add_admin_application("tg_user_1", "王小明")
        service = TelegramCommandService(db=db_manager, channel_access_token="line-token")

        with patch.object(telegram_commands_module, "fetch_line_profile_display_name", return_value="LINE Alice"):
            result = service.handle_text(user_id="admin_a", text="/admin/apply list")

        assert result["status"] == "success"
        assert "Admin 申請列表" in result["message"]
        assert "LINE Alice" in result["message"]
        assert "B12345678" not in result["message"]
        assert "王小明" not in result["message"]

    def test_admin_apply_list_rejects_non_admin(self, db_manager):
        db_manager.add_admin_application("tg_user_1", "王小明")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="tg_user_2", text="/admin/apply list")

        assert result["status"] == "error"
        assert "未授權" in result["message"]

    def test_admin_apply_approve_routes_to_admin_subcommand(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        db_manager.add_admin_application("tg_user_1", "王小明")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/admin/apply approve tg_user_1")

        assert result["status"] == "success"
        assert "已批准" in result["message"]
        assert db_manager.is_admin("tg_user_1") is True

    def test_admin_apply_reject_routes_to_admin_subcommand(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        db_manager.add_admin_application("tg_user_1", "王小明")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/admin/apply reject tg_user_1")

        assert result["status"] == "success"
        assert "已拒絕" in result["message"]

    def test_admin_notify_single_category_on(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/admin/notify join on")

        assert result["status"] == "success"
        assert "join" in result["message"].lower()
        prefs = db_manager.get_admin_notification_preferences("admin_a")
        assert prefs["join"] is True

    def test_admin_notify_single_category_off(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        db_manager.set_admin_notification_preference("admin_a", "join", True)
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/admin/notify join off")

        assert result["status"] == "success"
        prefs = db_manager.get_admin_notification_preferences("admin_a")
        assert prefs["join"] is False

    def test_admin_notify_all_on(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/admin/notify all on")

        assert result["status"] == "success"
        prefs = db_manager.get_admin_notification_preferences("admin_a")
        assert all(prefs[category] is True for category in TELEGRAM_NOTIFICATION_CATEGORIES)

    def test_admin_notify_all_off(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        db_manager.set_all_admin_notification_preferences("admin_a", True)
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/admin/notify all off")

        assert result["status"] == "success"
        prefs = db_manager.get_admin_notification_preferences("admin_a")
        assert all(prefs[category] is False for category in TELEGRAM_NOTIFICATION_CATEGORIES)

    def test_admin_notify_status_lists_current_preferences(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        db_manager.set_admin_notification_preference("admin_a", "join", True)
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/admin/notify status")

        assert result["status"] == "success"
        assert "join: on" in result["message"].lower()
        assert "register: off" in result["message"].lower()

    def test_non_admin_cannot_change_notify_preferences(self, db_manager):
        db_manager.upsert_user_profile("user_a", "User A", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="user_a", text="/admin/notify join on")

        assert result["status"] == "error"
        assert "未授權" in result["message"]

    def test_admin_notify_rejects_unknown_category(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/admin/notify mystery on")

        assert result["status"] == "error"
        assert "未知" in result["message"]

    def test_admin_join_status_reports_current_state(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/admin/join status")

        assert result["status"] == "success"
        assert "隊列狀態" in result["message"]

    def test_admin_join_off_disables_queue(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/admin/join off")

        assert result["status"] == "success"
        assert db_manager.is_queue_enabled() is False

    def test_admin_ping_notifies_head_user(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "Admin A", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)
        service.queue_manager.join("alice", "regular")

        result = service.handle_text(user_id="admin_a", text="/admin/ping")

        assert result["status"] == "success"
        assert "已提醒" in result["message"]
        assert "B12345678（A-1）" in result["message"]

    def test_admin_serve_next_broadcasts_called_user_with_platform_label(self, db_manager, monkeypatch):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("admin_b", "管理員乙", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        db_manager.set_admin_notification_preference("admin_b", "serve", True)

        sent = []

        class _FakeNow:
            def strftime(self, fmt: str) -> str:
                return "2026-04-30 03:30:00"

        monkeypatch.setattr(telegram_commands_module, "now_in_taipei", lambda: _FakeNow())

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(db=db_manager, telegram_sender=sender)
        service.queue_manager.join("alice", "regular")

        result = service.handle_text(user_id="admin_a", text="/admin/serve")

        assert result["status"] == "success"
        assert "已叫號" in result["message"]
        assert "B12345678（A-1）" in result["message"]
        assert sent == [("admin_b", sent[0][1])]
        assert "平台：Telegram" in sent[0][1]
        assert "管理員甲" in sent[0][1]
        assert "B12345678（A-1）" in sent[0][1]
        assert "時間：2026-04-30 03:30:00" in sent[0][1]

    def test_admin_serve_next_sends_discord_dm_to_called_user(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("discord_user_1", "B12345678", location="A-1", verified=True, role="user")
        db_manager.set_config("discord_user:discord_user_1", "1")

        sent = []

        def discord_sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        from services.notifier import Notifier

        service = TelegramCommandService(db=db_manager)
        service.queue_manager.notifier = Notifier(discord_sender=discord_sender, db=db_manager)
        service.queue_manager.join("discord_user_1", "regular")

        result = service.handle_text(user_id="admin_a", text="/admin/serve")

        assert result["status"] == "success"
        assert result["message"] == "✅ 已叫號：B12345678（A-1）"
        assert sent == [("discord_user_1", sent[0][1])]
        assert "輪到你了" in sent[0][1]
        assert "#1" in sent[0][1]
        assert "請做好準備" in sent[0][1]
        assert "助教" in sent[0][1]


    def test_admin_serve_next_sends_telegram_message_to_called_user(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("tg_user_1", "B12345678", location="A-1", verified=True, role="user")
        db_manager.set_config("telegram_user:tg_user_1", "1")

        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(db=db_manager, telegram_sender=sender)
        service.queue_manager.join("tg_user_1", "regular")

        result = service.handle_text(user_id="admin_a", text="/admin/serve")

        assert result["status"] == "success"
        assert result["message"] == "✅ 已叫號：B12345678（A-1）"
        assert sent == [("tg_user_1", sent[0][1])]
        assert "輪到你了" in sent[0][1]
        assert "#1" in sent[0][1]
        assert "請做好準備" in sent[0][1]
        assert "助教" in sent[0][1]

    def test_admin_serve_next_triggers_dashboard_announcement(self, db_manager):
        class FakeAnnouncementService:
            def __init__(self):
                self.calls = []

            def announce_called_guest(self, *, display_name: str):
                self.calls.append(display_name)
                return {"ok": True}

        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        announcement_service = FakeAnnouncementService()
        service = TelegramCommandService(db=db_manager, announcement_service=announcement_service)
        service.queue_manager.join("alice", "regular")

        result = service.handle_text(user_id="admin_a", text="/admin/serve")

        assert result["status"] == "success"
        assert announcement_service.calls == ["B12345678"]

    def test_admin_serve_next_uses_special_rule_to_skip_target_and_notify_admin(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("target_user", "114106135", location="A-1", verified=True, role="user")
        db_manager.upsert_user_profile("next_user", "114106999", location="A-2", verified=True, role="user")
        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(
            db=db_manager,
            telegram_sender=sender,
            special_serve_rules={
                "enabled": True,
                "skip_message": "skip-msg",
                "admins": {"admin_a": {"targets": ["114106135"]}},
            },
        )
        service.queue_manager.join("target_user", "regular")
        service.queue_manager.join("next_user", "regular")

        result = service.handle_text(user_id="admin_a", text="/admin/serve")

        assert result["status"] == "success"
        assert result["message"] == "✅ 已叫號：114106999（A-2）"
        assert ("admin_a", "skip-msg") in sent
        assert service.queue_manager.get_user_position("target_user") == 1
        assert service.queue_manager.get_user_position("next_user") is None

    def test_admin_serve_next_only_target_replies_without_serving_and_auto_releases_previous(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("first_user", "114106999", location="A-1", verified=True, role="user")
        db_manager.upsert_user_profile("target_user", "114106135", location="A-2", verified=True, role="user")
        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(
            db=db_manager,
            telegram_sender=sender,
            special_serve_rules={
                "enabled": True,
                "no_next_reply": "busy-msg",
                "admins": {"admin_a": {"targets": ["114106135"]}},
            },
        )
        service.queue_manager.join("first_user", "regular")
        service.queue_manager.join("target_user", "regular")

        first = service.handle_text(user_id="admin_a", text="/admin/serve")
        sent.clear()
        second = service.handle_text(user_id="admin_a", text="/admin/serve")

        assert first["status"] == "success"
        assert second["status"] == "error"
        assert second["message"] == "⚠️ busy-msg\n（已自動解除 114106999（A-1） 的鎖定）"
        assert sent == []
        assert service.queue_manager.get_called_entry("first_user") is None
        assert service.queue_manager.get_user_position("target_user") == 1

    def test_admin_serve_specific_bypasses_special_rule_skip_and_calls_requested_user(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("target_user", "114106135", location="A-1", verified=True, role="user")
        db_manager.upsert_user_profile("next_user", "114106999", location="A-2", verified=True, role="user")
        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(
            db=db_manager,
            telegram_sender=sender,
            special_serve_rules={
                "enabled": True,
                "skip_message": "skip-msg",
                "admins": {"admin_a": {"targets": ["114106135"]}},
            },
        )
        service.queue_manager.join("target_user", "regular")
        service.queue_manager.join("next_user", "regular")

        result = service.handle_text(user_id="admin_a", text="/admin/serve next_user")

        assert result["status"] == "success"
        assert result["message"] == "✅ 已叫號：114106999（A-2）"
        assert ("admin_a", "skip-msg") not in sent
        assert service.queue_manager.get_user_position("target_user") == 1
        assert service.queue_manager.get_user_position("next_user") is None

    def test_admin_serve_specific_bypasses_special_rule_block_when_only_target_waits(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("target_user", "114106135", location="A-1", verified=True, role="user")

        service = TelegramCommandService(
            db=db_manager,
            special_serve_rules={
                "enabled": True,
                "no_next_reply": "busy-msg",
                "admins": {"admin_a": {"targets": ["114106135"]}},
            },
        )
        service.queue_manager.join("target_user", "regular")

        result = service.handle_text(user_id="admin_a", text="/admin/serve target_user")

        assert result["status"] == "success"
        assert result["message"] == "✅ 已叫號：114106135（A-1）"
        assert service.queue_manager.get_user_position("target_user") is None

    def test_admin_serve_specific_broadcasts_called_user(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("admin_b", "管理員乙", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        db_manager.upsert_user_profile("bob", "B23456789", location="A-2", verified=True, role="user")
        db_manager.set_admin_notification_preference("admin_b", "serve", True)

        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(db=db_manager, telegram_sender=sender)
        service.queue_manager.join("alice", "regular")
        service.queue_manager.join("bob", "regular")

        result = service.handle_text(user_id="admin_a", text="/admin/serve bob")

        assert result["status"] == "success"
        assert "B23456789（A-2）" in result["message"]
        assert sent == [("admin_b", sent[0][1])]
        assert "/admin/serve bob" in sent[0][1]
        assert "B23456789（A-2）" in sent[0][1]

    def test_admin_status_lists_regular_and_vip_queues(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        db_manager.upsert_user_profile("bob", "B23456789", location="A-2", verified=False, role="user")
        db_manager.add_vip_purchase("bob", platform="line", coffee_id="coffee_1", verified=True)

        service = TelegramCommandService(db=db_manager)
        service.queue_manager.join("alice", "regular")
        service.queue_manager.join("bob", "vip")

        result = service.handle_text(user_id="admin_a", text="/admin/status")

        assert result["status"] == "success"
        assert "完整隊列狀態" in result["message"]
        assert "標準隊列" in result["message"]
        assert "VIP 隊列" in result["message"]
        assert "B12345678（A-1） ✅" in result["message"]
        assert "B23456789（A-2） 🕓" in result["message"]

    def test_register_broadcasts_to_admins_with_register_pref(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.set_admin_notification_preference("admin_a", "register", True)
        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(db=db_manager, telegram_sender=sender)
        step1 = service.handle_text(user_id="alice", text="/register")
        step2 = service.handle_text(user_id="alice", text="B12345678")
        step3 = service.handle_text(user_id="alice", text="A")
        result = service.handle_text(user_id="alice", text="1")

        assert step1["status"] == "pending"
        assert step2["status"] == "pending"
        assert step3["status"] == "pending"
        assert result["status"] == "success"
        assert sent == [("admin_a", sent[0][1])]
        assert "註冊通知" in sent[0][1]
        assert "B12345678（A-1）" in sent[0][1]

    def test_join_broadcasts_to_admins_with_join_pref(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        db_manager.set_admin_notification_preference("admin_a", "join", True)
        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(db=db_manager, telegram_sender=sender)
        result = service.handle_text(user_id="alice", text="/join")

        assert result["status"] == "success"
        assert sent == [("admin_a", sent[0][1])]
        assert "排隊通知" in sent[0][1]
        assert "平台：Telegram" in sent[0][1]
        assert "B12345678（A-1）" in sent[0][1]

    def test_cancel_broadcasts_to_admins_with_cancel_pref(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        db_manager.set_admin_notification_preference("admin_a", "cancel", True)
        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(db=db_manager, telegram_sender=sender)
        service.handle_text(user_id="alice", text="/join")
        sent.clear()

        result = service.handle_text(user_id="alice", text="/cancel")

        assert result["status"] == "success"
        assert sent == [("admin_a", sent[0][1])]
        assert "取消通知" in sent[0][1]
        assert "B12345678（A-1）" in sent[0][1]

    def test_failed_join_broadcasts_to_admins_with_error_pref(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        db_manager.set_admin_notification_preference("admin_a", "error", True)
        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(db=db_manager, telegram_sender=sender)
        first = service.handle_text(user_id="alice", text="/join")
        assert first["status"] == "success"
        sent.clear()

        result = service.handle_text(user_id="alice", text="/join")

        assert result["status"] == "error"
        assert sent == [("admin_a", sent[0][1])]
        assert "失敗通知" in sent[0][1]
        assert "/join" in sent[0][1]
        assert "請勿重複加入" in sent[0][1]

    def test_admin_stats_reports_summary(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)
        service.handle_text(user_id="alice", text="/join")
        service.handle_text(user_id="admin_a", text="/admin/serve")

        result = service.handle_text(user_id="admin_a", text="/admin/stats")

        assert result["status"] == "success"
        assert "今日排隊人數" in result["message"]
        assert "被叫號人數" in result["message"]
        assert "平均等待時間" in result["message"]

    def test_admin_vip_status_reports_enabled_and_count(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("vip_alice", "B34567890", location="A-3", verified=True, role="user")
        db_manager.add_vip_purchase("vip_alice", platform="line", coffee_id="coffee_1", verified=True)
        service = TelegramCommandService(db=db_manager)
        service.handle_text(user_id="vip_alice", text="/join vip")

        result = service.handle_text(user_id="admin_a", text="/admin/vip status")

        assert result["status"] == "success"
        assert "VIP 隊列狀態" in result["message"]
        assert "啟用" in result["message"]
        assert "1" in result["message"]

    def test_admin_vip_toggle_broadcasts_admin_action(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("admin_b", "管理員乙", verified=True, role="admin")
        db_manager.set_admin_notification_preference("admin_b", "admin_action", True)
        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(db=db_manager, telegram_sender=sender)
        result = service.handle_text(user_id="admin_a", text="/admin/vip toggle off")

        assert result["status"] == "success"
        assert db_manager.is_vip_enabled() is False
        assert sent == [("admin_b", sent[0][1])]
        assert "管理操作通知" in sent[0][1]
        assert "/admin/vip toggle off" in sent[0][1]

    def test_admin_vip_clear_broadcasts_admin_action(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("admin_b", "管理員乙", verified=True, role="admin")
        db_manager.upsert_user_profile("vip_alice", "B34567890", location="A-3", verified=True, role="user")
        db_manager.set_admin_notification_preference("admin_b", "admin_action", True)
        db_manager.add_vip_purchase("vip_alice", platform="line", coffee_id="coffee_1", verified=True)
        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(db=db_manager, telegram_sender=sender)
        service.handle_text(user_id="vip_alice", text="/join vip")
        sent.clear()

        result = service.handle_text(user_id="admin_a", text="/admin/vip clear")

        assert result["status"] == "success"
        assert "移除 1 筆" in result["message"]
        assert len(db_manager.get_vip_queue()) == 0
        assert sent == [("admin_b", sent[0][1])]
        assert "管理操作通知" in sent[0][1]
        assert "/admin/vip clear" in sent[0][1]

    def test_admin_skip_broadcasts_skip_category(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("admin_b", "管理員乙", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        db_manager.set_admin_notification_preference("admin_b", "skip", True)
        sent = []

        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))

        service = TelegramCommandService(db=db_manager, telegram_sender=sender)
        service.handle_text(user_id="alice", text="/join")

        result = service.handle_text(user_id="admin_a", text="/admin/skip")

        assert result["status"] == "success"
        assert "已跳過" in result["message"]
        assert len(sent) == 2
        assert sent[0] == ("alice", sent[0][1])
        assert "你已被跳過" in sent[0][1]
        assert sent[1] == ("admin_b", sent[1][1])
        assert "跳過通知" in sent[1][1]
        assert "B12345678（A-1）" in sent[1][1]

    def test_admin_history_returns_user_events(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)
        service.handle_text(user_id="alice", text="/join")
        service.handle_text(user_id="alice", text="/cancel")

        result = service.handle_text(user_id="admin_a", text="/admin/history alice")

        assert result["status"] == "success"
        assert "alice 歷史紀錄" in result["message"]
        assert "join" in result["message"]
        assert "cancel" in result["message"]

    def test_admin_export_returns_csv_preview(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)
        service.handle_text(user_id="alice", text="/join")

        result = service.handle_text(user_id="admin_a", text="/admin/export")

        assert result["status"] == "success"
        assert "CSV 匯出" in result["message"]
        assert "user_id,queue_type" in result["message"]
        assert "alice" in result["message"]

    def test_admin_clear_keeps_admin_profile_and_notification_preferences(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", location="A-9", verified=True, role="admin")
        db_manager.upsert_user_profile("admin_b", "管理員乙", location="B-9", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        db_manager.set_admin_notification_preference("admin_a", "join", True)
        service = TelegramCommandService(db=db_manager)
        service.handle_text(user_id="alice", text="/join")

        result = service.handle_text(user_id="admin_a", text="/admin/clear")

        assert result["status"] == "success"
        assert db_manager.get_user_profile("alice") is None
        kept_admin = db_manager.get_user_profile("admin_a")
        assert kept_admin is not None
        assert kept_admin.role == "admin"
        assert kept_admin.display_name == ""
        assert kept_admin.location == ""
        assert db_manager.get_admin_notification_preferences("admin_a")["join"] is True

    def test_re_register_after_admin_approval_preserves_admin_role(self, db_manager):
        db_manager.add_admin_application("admin_a", "管理員甲")
        db_manager.approve_admin_application("admin_a", "reviewer_1")
        service = TelegramCommandService(db=db_manager, location_options={"A": ["1", "2"]})

        step1 = service.handle_text(user_id="admin_a", text="/register")
        step2 = service.handle_text(user_id="admin_a", text="B12345678")
        step3 = service.handle_text(user_id="admin_a", text="A")
        step4 = service.handle_text(user_id="admin_a", text="1")

        assert step1["status"] == "pending"
        assert step2["status"] == "pending"
        assert step3["status"] == "pending"
        assert step4["status"] == "success"
        profile = db_manager.get_user_profile("admin_a")
        assert profile is not None
        assert profile.role == "admin"
        assert profile.display_name == "B12345678"
        assert profile.location == "A-1"

    def test_promoted_admin_using_stale_user_reply_keyboard_refreshes_admin_menu(self, db_manager):
        db_manager.upsert_user_profile("tg_user_1", "User 1", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)

        first_menu = service.handle_text(user_id="tg_user_1", text="/menu")
        assert first_menu["reply_markup"]["keyboard"] == [
            [{"text": "舉手"}, {"text": "放棄"}, {"text": "看狀態"}],
            [{"text": "看紀錄"}, {"text": "設定資料"}, {"text": "排隊紀錄"}],
        ]

        db_manager.upsert_user_profile("tg_user_1", "User 1", verified=True, role="admin")

        result = service.handle_text(user_id="tg_user_1", text="看狀態")

        assert result["status"] == "success"
        assert "reply_markup" in result
        assert result["reply_markup"]["keyboard"] == [
            [{"text": "叫號"}, {"text": "提醒"}, {"text": "完整狀態"}],
            [{"text": "開關排隊"}, {"text": "更多功能"}],
        ]


    def test_non_admin_cannot_use_admin_vip(self, db_manager):
        db_manager.upsert_user_profile("user_a", "User A", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="user_a", text="/admin/vip status")

        assert result["status"] == "error"
        assert "未授權" in result["message"]

    def test_non_admin_cannot_serve(self, db_manager):
        db_manager.upsert_user_profile("user_a", "User A", verified=True, role="user")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="user_a", text="/admin/serve")

        assert result["status"] == "error"
        assert "未授權" in result["message"]

    def test_admin_release_immediately_releases_user_and_broadcasts(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        db_manager.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
        db_manager.set_admin_notification_preference("admin_a", "admin_action", True)
        
        sent = []
        def sender(user_id: str, text: str) -> None:
            sent.append((user_id, text))
            
        service = TelegramCommandService(db=db_manager, telegram_sender=sender)
        service.queue_manager.join("alice", "regular")
        service.queue_manager.serve_next()
        
        result = service.handle_text(user_id="admin_a", text="/admin/release A-1")
        
        assert result["status"] == "success"
        assert "已解除" in result["message"]
        assert service.queue_manager.get_user_position("alice") is None
        assert any("Demo完成通知" in text for uid, text in sent)

    def test_admin_release_unknown_location_returns_error_message(self, db_manager):
        db_manager.upsert_user_profile("admin_a", "管理員甲", verified=True, role="admin")
        service = TelegramCommandService(db=db_manager)

        result = service.handle_text(user_id="admin_a", text="/admin/release Z-9")

        assert result["status"] == "error"
        assert "Z-9" in result["message"]
