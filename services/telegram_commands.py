"""Telegram 指令解析、互動式選單與 admin 自助流程。

這個 service 是 Telegram 平台的主要 command façade：
- 把文字/按鈕 callback 正規化成共用命令
- 接上 register/cancel/admin 等共用 flow helpers
- 產生 Telegram 專用 reply markup
- 視需要對 admin 廣播操作通知
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from core.database import DatabaseManager
from core.queue_manager import QueueManager
from core.time_utils import format_display_time, now_in_taipei
from core.validators import validate_command
from services.action_schema import (
    TELEGRAM_ADMIN_OPEN_NOTIFY_SETTINGS,
    TELEGRAM_ADMIN_SWITCH_PAGE1,
    TELEGRAM_ADMIN_SWITCH_PAGE2,
    TELEGRAM_CANCEL_ABORT,
    TELEGRAM_CANCEL_CONFIRM,
    TELEGRAM_NOTIFY_ALL_OFF,
    TELEGRAM_NOTIFY_ALL_ON,
    TELEGRAM_REGISTER_GROUP_PREFIX,
    TELEGRAM_REGISTER_ITEM_PREFIX,
    build_telegram_notify_toggle_action,
    build_telegram_register_group_action,
    build_telegram_register_item_action,
    build_telegram_simple_callback_button,
    is_telegram_register_choice_action,
    normalize_register_choice_action,
)
from services.notifier import Notifier
from services.telegram_admin_notifications import (
    TELEGRAM_NOTIFICATION_CATEGORIES,
    TelegramAdminNotificationService,
)
from services.admin_flow import (
    build_admin_export_preview,
    build_admin_history,
    build_admin_stats,
    build_admin_status,
    build_vip_status,
    clear_all_queue,
    clear_vip_queue,
    get_admin_join_status,
    ping_user,
    release_user,
    set_admin_join_enabled,
    toggle_admin_join,
    toggle_vip,
)
from services.cancel_flow import begin_closed_queue_cancel_flow, advance_closed_queue_cancel_flow
from services.interaction_presenters import (
    build_telegram_cancel_confirmation_markup,
    build_telegram_choice_markup,
    build_telegram_reply_keyboard_markup,
)
from services.line_profile_lookup import fetch_line_profile_display_name
from services.pending_state_store import ConfigPendingStateStore
from services.register_flow import advance_register_flow
from services.register_service import complete_registration
from services.serve_flow import serve_user
from services.special_serve_rules import normalize_special_serve_rules, resolve_special_serve_decision
from services.user_flow import build_help_message, build_history_message, cancel_user, get_user_status, join_user
from services.vip_service import VipService


class TelegramCommandService:
    """Telegram 平台的指令入口與 UI 組裝器。"""

    #: 一般使用者在 Telegram reply keyboard 上看到的固定選單。
    USER_REPLY_KEYBOARD = [
        [{"text": "舉手"}, {"text": "放棄"}, {"text": "看狀態"}],
        [{"text": "看紀錄"}, {"text": "設定資料"}, {"text": "排隊紀錄"}],
    ]
    #: admin 第一頁功能選單。
    ADMIN_REPLY_KEYBOARD_PAGE1 = [
        [{"text": "叫號"}, {"text": "提醒"}, {"text": "完整狀態"}],
        [{"text": "開關排隊"}, {"text": "更多功能"}],
    ]
    #: admin 第二頁功能選單。
    ADMIN_REPLY_KEYBOARD_PAGE2 = [
        [{"text": "清空隊列"}, {"text": "VIP 狀態"}, {"text": "推播設定"}],
        [{"text": "幫助"}, {"text": "返回主選單"}],
    ]

    #: 將 reply keyboard 文案映射成共用 slash command。
    USER_TEXT_ALIASES = {
        "舉手": "/join",
        "放棄": "/cancel",
        "看狀態": "/status",
        "看紀錄": "/hostory",
        "設定資料": "/register",
        "排隊紀錄": "/history",
    }
    #: admin reply keyboard 與 callback 的文字別名表。
    ADMIN_TEXT_ALIASES = {
        "叫號": "/admin/serve",
        "提醒": "/admin/ping",
        "完整狀態": "/admin/status",
        "開關排隊": "/admin/join",
        "更多功能": TELEGRAM_ADMIN_SWITCH_PAGE2,
        "清空隊列": "/admin/clear",
        "VIP 狀態": "/admin/vip status",
        "推播設定": TELEGRAM_ADMIN_OPEN_NOTIFY_SETTINGS,
        "幫助": "/help",
        "返回主選單": TELEGRAM_ADMIN_SWITCH_PAGE1,
    }

    def __init__(
        self,
        *,
        db,
        queue_manager: QueueManager | None = None,
        channel_access_token: str = "",
        telegram_sender=None,
        location_options: dict[str, list[str]] | None = None,
        announcement_service=None,
        special_serve_rules: dict | None = None,
    ) -> None:
        """建立 Telegram command service 與其依賴。

        會在可行時自動建立：
        - QueueManager
        - VIP service
        - Telegram admin notification service
        - QueueManager notifier（若尚未注入）
        """
        self.db = db
        self.channel_access_token = channel_access_token
        #: Telegram command 層共用的隊列核心；admin serve/join/cancel 皆會經過它。
        self.queue_manager = queue_manager or (QueueManager(db) if isinstance(db, DatabaseManager) else None)
        self.vip_service = VipService(db) if isinstance(db, DatabaseManager) else None
        self.location_options = location_options or {"A": ["1", "2"], "B": ["1", "2"]}
        self.special_serve_rules = normalize_special_serve_rules(special_serve_rules)
        #: 保存 Telegram register/cancel 多步驟互動的暫存狀態。
        self.pending_state_store = ConfigPendingStateStore(db, namespace="telegram")
        #: 廣播給 Telegram admin 訂閱者的後台通知 service。
        self.notification_service = None
        #: Dashboard / 語音公告通道。
        self.announcement_service = announcement_service
        if telegram_sender is not None:
            self.notification_service = TelegramAdminNotificationService(db=db, sender=telegram_sender)
            if self.queue_manager is not None and getattr(self.queue_manager, "notifier", None) is None:
                #: 真正送被叫號者私訊通知的 notifier 會掛在 queue_manager 上。
                self.queue_manager.notifier = Notifier(telegram_sender=telegram_sender, db=db)

    def handle_text(self, *, user_id: str, text: str) -> dict:
        """處理 Telegram 收到的文字或 callback payload。

        這裡是整個 Telegram flow 的總入口，會依序處理：
        - 使用者平台標記
        - pending register/cancel state
        - admin 頁面切換/通知 callback
        - 一般 slash command 與 admin command
        """
        self.db.set_config(f"telegram_user:{user_id}", "1")
        raw_text = text.strip()
        normalized_text = self._normalize_text_alias(user_id=user_id, text=raw_text)
        used_stale_user_reply_button = self.db.is_admin(user_id) and raw_text in self.USER_TEXT_ALIASES

        if raw_text in self.ADMIN_TEXT_ALIASES and not self.db.is_admin(user_id):
            return {
                "status": "error",
                "message": "❌ 未授權，已切回一般功能選單。",
                "reply_markup": self._reply_keyboard_markup(user_id),
            }

        if pending := self._get_pending_register_state(user_id):
            if normalized_text.startswith("/") and normalized_text != "/register":
                self._clear_pending_register_state(user_id)
            else:
                return self._handle_register_pending(user_id=user_id, text=raw_text, state=pending)

        if normalized_text == TELEGRAM_ADMIN_SWITCH_PAGE2:
            return self._handle_admin_page_switch(user_id=user_id, target_page="page2")
        if normalized_text == TELEGRAM_ADMIN_SWITCH_PAGE1:
            return self._handle_admin_page_switch(user_id=user_id, target_page="page1")
        if normalized_text == TELEGRAM_ADMIN_OPEN_NOTIFY_SETTINGS:
            return self._handle_admin_notify_menu(user_id=user_id)
        if normalized_text.startswith("notify:"):
            return self._handle_admin_notify_callback(user_id=user_id, payload=normalized_text)
        if normalized_text in {TELEGRAM_CANCEL_CONFIRM, TELEGRAM_CANCEL_ABORT}:
            return self._handle_cancel_confirmation(user_id=user_id, text=normalized_text)

        command, args = validate_command(normalized_text)
        if command == "/menu":
            result = self._handle_menu(user_id=user_id)
        elif command == "/hostory":
            result = self._handle_user_history(user_id=user_id)
        elif command == "/register":
            result = self._handle_register(user_id=user_id, args=args)
        elif command == "/join":
            result = self._handle_join(user_id=user_id, args=args, raw_text=raw_text)
        elif command == "/cancel":
            result = self._handle_cancel(user_id=user_id, raw_text=raw_text)
        elif command == "/status":
            result = self._handle_status(user_id=user_id)
        elif command == "/history":
            result = self._handle_user_history(user_id=user_id)
        elif command == "/help":
            result = self._handle_help(user_id=user_id)
        elif command == "/admin/apply":
            result = self._handle_admin_apply_command(user_id=user_id, args=args)
        elif command == "/admin/notify":
            result = self._handle_admin_notify(user_id=user_id, args=args)
        elif command == "/admin/join":
            result = self._handle_admin_join(user_id=user_id, args=args)
        elif command == "/admin/status":
            result = self._handle_admin_status(user_id=user_id)
        elif command == "/admin/stats":
            result = self._handle_admin_stats(user_id=user_id)
        elif command == "/admin/history":
            result = self._handle_admin_history(user_id=user_id, args=args)
        elif command == "/admin/export":
            result = self._handle_admin_export(user_id=user_id)
        elif command == "/admin/clear":
            result = self._handle_admin_clear(user_id=user_id, raw_text=raw_text)
        elif command == "/admin/ping":
            result = self._handle_admin_ping(user_id=user_id, args=args)
        elif command == "/admin/serve":
            result = self._handle_admin_serve(user_id=user_id, args=args, raw_text=raw_text)
        elif command == "/admin/release":
            result = self._handle_admin_release(user_id=user_id, args=args)
        elif command == "/admin/skip":
            result = self._handle_admin_skip(user_id=user_id, args=args, raw_text=raw_text)
        elif command == "/admin/vip":
            result = self._handle_admin_vip(user_id=user_id, args=args, raw_text=raw_text)
        else:
            result = {"status": "error", "message": "Unknown command."}

        if used_stale_user_reply_button and "reply_markup" not in result:
            result = {**result, "reply_markup": self._reply_keyboard_markup(user_id)}
        return result

    def _handle_menu(self, *, user_id: str) -> dict:
        return {
            "status": "success",
            "message": "請使用下方功能選單。",
            "reply_markup": self._reply_keyboard_markup(user_id),
        }

    def _handle_register(self, *, user_id: str, args: list[str]) -> dict:
        """啟動互動式註冊流程。"""
        if args:
            return {"status": "error", "message": "❌ 錯誤：/register 不接受參數，請直接輸入 /register 後依提示完成註冊。"}

        self._set_pending_register_state(user_id, {"type": "register_name"})
        return {"status": "pending", "message": "請輸入你的學號。"}

    def _handle_join(self, *, user_id: str, args: list[str], raw_text: str) -> dict:
        """處理一般/VIP 加入隊列，並在失敗時補上 Telegram UI。"""
        queue_type = args[0].lower() if args else "regular"
        outcome = join_user(queue_manager=self.queue_manager, user_id=user_id, queue_type=queue_type)
        if outcome["status"] == "needs_registration":
            return {
                "status": "error",
                "message": outcome["message"],
                "reply_markup": self._inline_keyboard_markup(
                    [[build_telegram_simple_callback_button("設定基本資料", "/register")]]
                ),
            }

        if outcome["status"] != "success":
            raw = outcome.get("raw_result", {})
            self._broadcast_error_event(user_id=user_id, command_text=raw_text, error_message=raw.get("message", outcome["message"]))
            return {"status": "error", "message": outcome["message"]}

        self._broadcast_simple_event(
            category="join",
            title="排隊通知",
            actor_label=f"使用者：{self._format_profile_label(user_id)}",
            target_label=f"隊列：{queue_type}",
            detail_lines=[
                f"號碼：#{outcome['queue_number']}",
                f"目前總人數：{outcome['total_in_queue']}",
            ],
        )
        return {
            "status": "success",
            "message": f"✅ 已加入隊列，號碼 #{outcome['queue_number']}（目前 {outcome['total_in_queue']} 人）",
        }

    def _handle_cancel(self, *, user_id: str, raw_text: str) -> dict:
        """處理取消排隊；若已封隊則改走雙重確認流程。"""
        if not self.queue_manager.get_queue_enabled() and self.queue_manager.get_user_position(user_id) is not None:
            outcome = begin_closed_queue_cancel_flow()
            self.pending_state_store.set(user_id=user_id, flow="cancel", state=outcome["state"])
            return {
                "status": "pending",
                "message": outcome["message"],
                "reply_markup": self._inline_keyboard_markup(self._cancel_confirmation_inline_keyboard()),
            }

        outcome = cancel_user(queue_manager=self.queue_manager, user_id=user_id)
        if outcome["status"] != "cancelled":
            raw = outcome.get("raw_result", {})
            self._broadcast_error_event(user_id=user_id, command_text=raw_text, error_message=raw.get("message", outcome["message"]))
            return {"status": "error", "message": outcome["message"]}

        self._broadcast_simple_event(
            category="cancel",
            title="取消通知",
            actor_label=f"使用者：{self._format_profile_label(user_id)}",
            target_label="動作：離開隊列",
        )
        return {"status": "success", "message": "✅ 已取消排隊"}

    def _handle_admin_apply(self, *, user_id: str, args: list[str]) -> dict:
        display_name = " ".join(args).strip()
        if not display_name:
            return {"status": "error", "message": "用法：/admin/apply [顯示名稱]"}

        result = self.db.add_admin_application(user_id, display_name)
        if result["status"] == "success":
            return {"status": "success", "message": "✅ 已提交管理員申請，請等待審核。"}
        if result["status"] == "duplicate":
            return {"status": "error", "message": "⚠️ 你已提交過申請，請勿重複送出。"}
        return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}

    def _handle_admin_apply_command(self, *, user_id: str, args: list[str]) -> dict:
        if not args:
            return self._handle_admin_apply(user_id=user_id, args=args)

        sub_cmd = args[0].lower()
        if sub_cmd == "list":
            return self._handle_admin_apply_list(user_id=user_id)
        if sub_cmd == "approve":
            if len(args) < 2:
                return {"status": "error", "message": "用法：/admin/apply approve [user_id]"}
            return self._handle_admin_apply_approve(user_id=user_id, target_id=args[1])
        if sub_cmd == "reject":
            if len(args) < 2:
                return {"status": "error", "message": "用法：/admin/apply reject [user_id]"}
            return self._handle_admin_apply_reject(user_id=user_id, target_id=args[1])
        return self._handle_admin_apply(user_id=user_id, args=args)

    def _handle_admin_apply_list(self, *, user_id: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        pending = self.db.get_pending_applications_for_review(self._resolve_line_display_name_for_review)
        if not pending:
            return {"status": "success", "message": "📋 Admin 申請列表\n─────────────\n目前沒有待審核的申請。"}

        lines = ["📋 Admin 申請列表", "─────────────"]
        for index, app in enumerate(pending, start=1):
            lines.append(f"{index}. {app['user_id']} ({app['resolved_display_name']})")
        return {"status": "success", "message": "\n".join(lines)}

    def _handle_admin_apply_approve(self, *, user_id: str, target_id: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        result = self.db.approve_admin_application(target_id, user_id)
        if result["status"] == "success":
            return {"status": "success", "message": f"✅ 已批准 {target_id} 的 admin 申請。"}
        return {"status": "error", "message": f"❌ 找不到 {target_id} 的待審核申請。"}

    def _handle_admin_apply_reject(self, *, user_id: str, target_id: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        result = self.db.reject_admin_application(target_id, user_id)
        if result["status"] == "success":
            return {"status": "success", "message": f"✅ 已拒絕 {target_id} 的 admin 申請。"}
        return {"status": "error", "message": f"❌ 找不到 {target_id} 的待審核申請（已處理或不存在）。"}

    def _handle_admin_notify(self, *, user_id: str, args: list[str]) -> dict:
        """處理 Telegram admin 推播偏好查詢與開關。"""
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        if not args:
            return self._handle_admin_notify_menu(user_id=user_id)

        subject = args[0].lower()
        if subject == "status":
            prefs = self.db.get_admin_notification_preferences(user_id)
            lines = ["🔔 Telegram 推播設定"]
            for category in TELEGRAM_NOTIFICATION_CATEGORIES:
                lines.append(f"- {category}: {'on' if prefs[category] else 'off'}")
            return {"status": "success", "message": "\n".join(lines)}

        if len(args) < 2:
            return {"status": "error", "message": "用法：/admin/notify [category|all] [on/off]"}

        toggle = args[1].lower()
        if toggle not in {"on", "off"}:
            return {"status": "error", "message": "用法：/admin/notify [category|all] [on/off]"}
        enabled = toggle == "on"

        if subject == "all":
            self.db.set_all_admin_notification_preferences(user_id, enabled)
            return {"status": "success", "message": f"✅ 已將所有 Telegram 推播設為 {toggle}"}

        if subject not in TELEGRAM_NOTIFICATION_CATEGORIES:
            return {"status": "error", "message": f"❌ 未知的推播類別：{subject}"}

        self.db.set_admin_notification_preference(user_id, subject, enabled)
        return {"status": "success", "message": f"✅ 已將 {subject} 推播設為 {toggle}"}

    def _handle_admin_notify_menu(self, *, user_id: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        prefs = self.db.get_admin_notification_preferences(user_id)
        return {
            "status": "success",
            "message": "🔔 請選擇要設定的 Telegram 推播項目",
            "reply_markup": self._inline_keyboard_markup(self._admin_notify_inline_keyboard(prefs)),
        }

    def _handle_admin_notify_callback(self, *, user_id: str, payload: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        parts = payload.split(":")
        if len(parts) != 3:
            return {"status": "error", "message": "❌ 無效的推播設定操作。"}

        _, subject, action = parts
        if subject == "all" and action in {"on", "off"}:
            self.db.set_all_admin_notification_preferences(user_id, action == "on")
            return self._handle_admin_notify_menu(user_id=user_id)

        if subject not in TELEGRAM_NOTIFICATION_CATEGORIES or action != "toggle":
            return {"status": "error", "message": "❌ 無效的推播設定操作。"}

        current = self.db.get_admin_notification_preferences(user_id)
        self.db.set_admin_notification_preference(user_id, subject, not current[subject])
        return self._handle_admin_notify_menu(user_id=user_id)

    def _handle_admin_join(self, *, user_id: str, args: list[str]) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        if not args:
            result = toggle_admin_join(queue_manager=self.queue_manager)
            return {"status": "success", "message": f"✅ 隊列已{'開啟' if result['enabled'] else '關閉'}"}

        sub_cmd = args[0].lower()
        if sub_cmd == "on":
            result = set_admin_join_enabled(queue_manager=self.queue_manager, enabled=True)
            return {"status": "success", "message": f"✅ 隊列已{'開啟' if result['enabled'] else '關閉'}"}
        if sub_cmd == "off":
            result = set_admin_join_enabled(queue_manager=self.queue_manager, enabled=False)
            return {"status": "success", "message": f"✅ 隊列已{'開啟' if result['enabled'] else '關閉'}"}
        if sub_cmd == "status":
            result = get_admin_join_status(queue_manager=self.queue_manager)
            return {"status": "success", "message": f"📋 隊列狀態：{'已開啟' if result['enabled'] else '已關閉'}"}

        return {"status": "error", "message": "用法：/admin/join [on/off] 切換狀態 或 /admin/join status 查看狀態"}

    def _handle_admin_status(self, *, user_id: str) -> dict:
        """渲染 Telegram 版完整隊列狀態。"""
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        status = build_admin_status(queue_manager=self.queue_manager)
        regular_lines = [
            f"#{idx} {entry['display_name']} {'✅' if entry['verified'] else '🕓'} — {format_display_time(entry['join_time'], include_date=False)}"
            for idx, entry in enumerate(status["regular_entries"], start=1)
        ]
        vip_lines = [
            f"#{idx} {entry['display_name']} {'✅' if entry['verified'] else '🕓'} — {format_display_time(entry['join_time'], include_date=False)}"
            for idx, entry in enumerate(status["vip_entries"], start=1)
        ]
        regular_text = "\n".join(regular_lines) if regular_lines else "（空）"
        vip_text = "\n".join(vip_lines) if vip_lines else "（空）"
        return {
            "status": "success",
            "message": (
                "📋 完整隊列狀態\n\n"
                f"標準隊列 ({status['regular_count']}人):\n{regular_text}\n\n"
                f"VIP 隊列 ({status['vip_count']}人):\n{vip_text}\n\n"
                f"VIP 啟用: {'是' if status['vip_enabled'] else '否'}"
            ),
        }

    def _handle_admin_stats(self, *, user_id: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        stats = build_admin_stats(queue_manager=self.queue_manager)
        return {
            "status": "success",
            "message": (
                "📈 統計面板\n\n"
                f"今日排隊人數: {stats['joined_today']}\n"
                f"被叫號人數: {stats['served_count']}\n"
                f"被跳過人數: {stats['skipped_count']}\n"
                f"平均等待時間: {stats['average_wait_minutes']:.1f} 分鐘\n\n"
                f"VIP 啟用: {'是' if stats['vip']['enabled'] else '否'}\n"
                f"VIP 目前排隊: {stats['vip']['active_count']}\n"
                f"VIP 今日排隊: {stats['vip']['joined_today']}\n"
                f"VIP 今日叫號: {stats['vip']['served_count']}"
            ),
        }

    def _handle_admin_vip(self, *, user_id: str, args: list[str], raw_text: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        if not args:
            return {"status": "error", "message": "用法：/admin/vip [status|toggle|clear]"}

        sub_cmd = args[0].lower()
        if sub_cmd == "status":
            status = build_vip_status(vip_service=self.vip_service)
            return {
                "status": "success",
                "message": (
                    "💎 VIP 隊列狀態\n"
                    f"啟用: {'是' if status['enabled'] else '否'}\n"
                    f"目前 VIP 排隊人數: {status['count']}"
                ),
            }

        if sub_cmd == "toggle":
            if len(args) < 2 or args[1].lower() not in {"on", "off"}:
                return {"status": "error", "message": "用法：/admin/vip toggle [on/off]"}
            enabled = args[1].lower() == "on"
            result = toggle_vip(vip_service=self.vip_service, enabled=enabled)
            rendered = f"✅ {result['message']}"
            self._broadcast_simple_event(
                category="admin_action",
                title="管理操作通知",
                actor_label=f"管理員：{self._format_profile_label(user_id)}（{user_id}）",
                target_label=f"指令：{raw_text}",
                detail_lines=[f"結果：{result['message']}"],
            )
            return {"status": "success", "message": rendered}

        if sub_cmd == "clear":
            result = clear_vip_queue(queue_manager=self.queue_manager)
            rendered = f"✅ 已清空 VIP 隊列，移除 {result['removed_count']} 筆"
            self._broadcast_simple_event(
                category="admin_action",
                title="管理操作通知",
                actor_label=f"管理員：{self._format_profile_label(user_id)}（{user_id}）",
                target_label=f"指令：{raw_text}",
                detail_lines=[f"結果：移除 {result['removed_count']} 筆 VIP 隊列"],
            )
            return {"status": "success", "message": rendered}

        return {"status": "error", "message": "用法：/admin/vip [status|toggle|clear]"}

    def _handle_admin_history(self, *, user_id: str, args: list[str]) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}
        if not args:
            return {"status": "error", "message": "用法：/admin/history [ID]"}

        target_id = args[0]
        payload = build_admin_history(queue_manager=self.queue_manager, user_id=target_id)
        if payload is None:
            return {"status": "error", "message": f"查無 {target_id} 的歷史紀錄"}

        lines = [f"🧾 {payload['user_id']} 歷史紀錄"]
        for item in payload["history"]:
            lines.append(
                f"- {format_display_time(item['created_at'])}: {item['event_type']} ({item['queue_type'] or '-'})"
            )
        return {"status": "success", "message": "\n".join(lines)}

    def _handle_admin_export(self, *, user_id: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        payload = build_admin_export_preview(queue_manager=self.queue_manager)
        if payload["is_preview"]:
            message = f"📤 CSV 匯出（總計 {payload['total']} 筆，內容過長已預覽）\n{payload['preview']}"
        else:
            message = f"📤 CSV 匯出（總計 {payload['total']} 筆）\n{payload['csv_data']}"
        return {"status": "success", "message": message}

    def _handle_admin_clear(self, *, user_id: str, raw_text: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        result = clear_all_queue(queue_manager=self.queue_manager, keep_admin_user_ids=set())
        self._broadcast_simple_event(
            category="admin_action",
            title="管理操作通知",
            actor_label=f"管理員：{self._format_profile_label(user_id)}（{user_id}）",
            target_label=f"指令：{raw_text}",
            detail_lines=[
                f"結果：移除 {result['removed_count']} 筆隊列，清除 {result['cleared_profiles']} 筆使用者資料"
            ],
        )
        return {
            "status": "success",
            "message": (
                f"✅ 已清空全部隊列，移除 {result['removed_count']} 筆，並清除 {result['cleared_profiles']} 筆使用者資料、保留 {result['kept_admin_profiles']} 筆 admin 資料"
            ),
        }

    def _handle_admin_ping(self, *, user_id: str, args: list[str]) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        target_id = args[0] if args else None
        result = ping_user(queue_manager=self.queue_manager, target_id=target_id)
        if result["status"] != "success":
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}
        return {"status": "success", "message": f"✅ 已提醒 {result['display_name']}（{result['user_id']}）"}

    def _handle_status(self, *, user_id: str) -> dict:
        outcome = get_user_status(queue_manager=self.queue_manager, user_id=user_id)
        if outcome["status"] == "not_in_queue":
            return {"status": "success", "message": f"📊 目前有 {outcome['total_count']} 人在排隊中"}

        return {
            "status": "success",
            "message": f"📊 目前排在第 {outcome['position']} 位\n前面還有 {outcome['ahead_count']} 人",
        }

    def _handle_user_history(self, *, user_id: str) -> dict:
        history = self.queue_manager.get_user_history(user_id)
        return {
            "status": "success",
            "message": build_history_message(
                history,
                formatter=lambda item: f"- {format_display_time(item['created_at'])}: {item['event_type']} ({item['queue_type'] or '-'})",
            ),
        }

    def _handle_help(self, *, user_id: str) -> dict:
        return build_help_message(
            is_admin=self.db.is_admin(user_id),
            admin_only=True,
            include_admin_commands=True,
            include_vip_join=True,
            include_coffee=True,
        )

    def _normalize_text_alias(self, *, user_id: str, text: str) -> str:
        alias_map = dict(self.USER_TEXT_ALIASES)
        if self.db.is_admin(user_id):
            alias_map.update(self.ADMIN_TEXT_ALIASES)
        return alias_map.get(text, text)

    def _normalize_register_pending_text(self, *, text: str, state: dict) -> str:
        if not is_telegram_register_choice_action(text):
            return text

        if state.get("type") == "register_location_group":
            return normalize_register_choice_action(text, expected_prefix=TELEGRAM_REGISTER_GROUP_PREFIX)
        if state.get("type") == "register_location_item":
            return normalize_register_choice_action(text, expected_prefix=TELEGRAM_REGISTER_ITEM_PREFIX)
        return text

    def _handle_register_pending(self, *, user_id: str, text: str, state: dict) -> dict:
        """推進註冊 pending state，並補上 Telegram inline keyboard。"""
        normalized_pending_text = self._normalize_register_pending_text(text=text, state=state)
        outcome = advance_register_flow(
            state=state,
            text=normalized_pending_text,
            location_options=self.location_options,
        )

        if outcome["status"] == "pending":
            self._set_pending_register_state(user_id, outcome["state"])
            keyboard_prefix = None
            if outcome["state"]["type"] == "register_location_group":
                keyboard_prefix = TELEGRAM_REGISTER_GROUP_PREFIX
            elif outcome["state"]["type"] == "register_location_item":
                keyboard_prefix = TELEGRAM_REGISTER_ITEM_PREFIX
            return {
                "status": "pending",
                "message": outcome["message"],
                "reply_markup": build_telegram_choice_markup(options=outcome["options"], prefix=keyboard_prefix),
            }

        if outcome["status"] == "error":
            response = {"status": "error", "message": outcome["message"]}
            if "options" in outcome:
                keyboard_prefix = None
                if state.get("type") == "register_location_group":
                    keyboard_prefix = TELEGRAM_REGISTER_GROUP_PREFIX
                elif state.get("type") == "register_location_item":
                    keyboard_prefix = TELEGRAM_REGISTER_ITEM_PREFIX
                response["reply_markup"] = build_telegram_choice_markup(options=outcome["options"], prefix=keyboard_prefix)
            return response

        if outcome["status"] == "complete":
            self._clear_pending_register_state(user_id)
            return self._complete_register(
                user_id=user_id,
                display_name=outcome["display_name"],
                location=outcome["location"],
            )

        self._clear_pending_register_state(user_id)
        return {"status": "error", "message": outcome["message"]}

    def _complete_register(self, *, user_id: str, display_name: str, location: str) -> dict:
        """將註冊流程結果落地，並廣播成功/失敗事件。"""
        if self.queue_manager is None:
            return {"status": "error", "message": "Queue manager unavailable."}

        outcome = complete_registration(
            queue_manager=self.queue_manager,
            user_id=user_id,
            display_name=display_name,
            location=location,
        )
        if outcome["status"] != "success":
            raw = outcome.get("raw_result", {})
            self._broadcast_error_event(user_id=user_id, command_text="/register", error_message=raw.get("message", outcome["message"]))
            return {"status": "error", "message": outcome["message"]}

        self._broadcast_simple_event(
            category="register",
            title="註冊通知",
            actor_label=f"使用者：{self._format_profile_label(user_id)}",
            target_label="動作：完成註冊",
        )
        return {
            "status": "success",
            "message": outcome["message"],
        }

    def _handle_admin_page_switch(self, *, user_id: str, target_page: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        page_num = 2 if target_page == "page2" else 1
        keyboard = self.ADMIN_REPLY_KEYBOARD_PAGE2 if target_page == "page2" else self.ADMIN_REPLY_KEYBOARD_PAGE1
        return {
            "status": "success",
            "message": f"✅ 已切換至第 {page_num} 頁",
            "reply_markup": build_telegram_reply_keyboard_markup(keyboard),
        }

    def _handle_cancel_confirmation(self, *, user_id: str, text: str) -> dict:
        """處理封隊狀態下的取消二次確認互動。"""
        state = self._get_pending_cancel_state(user_id)
        outcome = advance_closed_queue_cancel_flow(
            state=state,
            action=text,
            still_in_queue=self.queue_manager.get_user_position(user_id) is not None,
            expired_message="請點選 quick reply 進行操作。",
        )

        if outcome["status"] == "aborted":
            self._clear_pending_cancel_state(user_id)
            return {"status": "success", "message": outcome["message"]}

        if outcome["status"] == "expired":
            return {
                "status": "pending",
                "message": outcome["message"],
                "reply_markup": self._inline_keyboard_markup(self._cancel_confirmation_inline_keyboard()),
            }

        if outcome["status"] == "not_in_queue":
            self._clear_pending_cancel_state(user_id)
            return {"status": "error", "message": outcome["message"]}

        if outcome["status"] == "pending":
            self.pending_state_store.set(user_id=user_id, flow="cancel", state=outcome["state"])
            return {
                "status": "pending",
                "message": outcome["message"],
                "reply_markup": self._inline_keyboard_markup(self._cancel_confirmation_inline_keyboard()),
            }

        self._clear_pending_cancel_state(user_id)
        result = self.queue_manager.cancel(user_id)
        if result["status"] != "cancelled":
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}
        self._broadcast_simple_event(
            category="cancel",
            title="取消通知",
            actor_label=f"使用者：{self._format_profile_label(user_id)}",
            target_label="動作：離開隊列",
        )
        return {"status": "success", "message": "✅ 已取消排隊"}

    def _reply_keyboard_markup(self, user_id: str, keyboard: list[list[dict]] | None = None) -> dict:
        selected_keyboard = keyboard
        if selected_keyboard is None:
            selected_keyboard = self.ADMIN_REPLY_KEYBOARD_PAGE1 if self.db.is_admin(user_id) else self.USER_REPLY_KEYBOARD
        return build_telegram_reply_keyboard_markup(selected_keyboard)

    def _inline_keyboard_markup(self, keyboard: list[list[dict]]) -> dict:
        return {"inline_keyboard": keyboard}

    def _build_inline_keyboard(self, options: list[str], *, columns: int = 2, prefix: str | None = None) -> list[list[dict]]:
        rows: list[list[dict]] = []
        current: list[dict] = []
        for option in options:
            callback_data = str(option)
            if prefix == TELEGRAM_REGISTER_GROUP_PREFIX:
                callback_data = build_telegram_register_group_action(str(option))
            elif prefix == TELEGRAM_REGISTER_ITEM_PREFIX:
                callback_data = build_telegram_register_item_action(str(option))
            current.append(build_telegram_simple_callback_button(str(option), callback_data))
            if len(current) >= columns:
                rows.append(current)
                current = []
        if current:
            rows.append(current)
        return rows

    def _cancel_confirmation_inline_keyboard(self) -> list[list[dict]]:
        return build_telegram_cancel_confirmation_markup()["inline_keyboard"]

    def _admin_notify_inline_keyboard(self, prefs: dict[str, bool]) -> list[list[dict]]:
        rows: list[list[dict]] = [
            [
                build_telegram_simple_callback_button("全部開啟", TELEGRAM_NOTIFY_ALL_ON),
                build_telegram_simple_callback_button("全部關閉", TELEGRAM_NOTIFY_ALL_OFF),
            ]
        ]
        for category in TELEGRAM_NOTIFICATION_CATEGORIES:
            status = "✅" if prefs.get(category) else "⬜️"
            rows.append([
                build_telegram_simple_callback_button(f"{status} {category}", build_telegram_notify_toggle_action(category))
            ])
        return rows

    def _get_pending_register_state(self, user_id: str) -> dict:
        return self.pending_state_store.get(user_id=user_id, flow="register")

    def _set_pending_register_state(self, user_id: str, state: dict) -> None:
        self.pending_state_store.set(user_id=user_id, flow="register", state=state)

    def _clear_pending_register_state(self, user_id: str) -> None:
        self.pending_state_store.clear(user_id=user_id, flow="register")

    def _get_pending_cancel_state(self, user_id: str) -> dict:
        return self.pending_state_store.get(user_id=user_id, flow="cancel")

    def _clear_pending_cancel_state(self, user_id: str) -> None:
        self.pending_state_store.clear(user_id=user_id, flow="cancel")

    def _handle_admin_serve(self, *, user_id: str, args: list[str], raw_text: str) -> dict:
        """處理 Telegram admin 叫號，並同步 admin 廣播通知。

        ``serve_user()`` 會幫忙把現場公告（dashboard/語音）與 queue manager 的
        私訊推播路徑串起來；這裡再補上 Telegram admin 後台事件廣播。
        """
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        admin_profile = self.db.get_user_profile(user_id)
        admin_display_name = (
            admin_profile.display_name if admin_profile and admin_profile.display_name else user_id
        )

        decision = {"status": "disabled", "target_user_id": None, "admin_message": None}
        if not args:
            decision = resolve_special_serve_decision(
                rules=self.special_serve_rules,
                queue_manager=self.queue_manager,
                admin_user_id=user_id,
            )
            if decision["status"] == "block":
                auto_released_display_name = self.queue_manager.auto_release_previous_for_admin(user_id)
                auto_note = (
                    f"\n（已自動解除 {auto_released_display_name} 的鎖定）"
                    if auto_released_display_name
                    else ""
                )
                return {"status": "error", "message": f"⚠️ {decision['admin_message']}{auto_note}"}

        result = serve_user(
            queue_manager=self.queue_manager,
            target_user_id=args[0] if args else decision["target_user_id"],
            announcement_service=self.announcement_service,
            admin_user_id=user_id,
        )

        if result["status"] != "served":
            self._broadcast_error_event(user_id=user_id, command_text=raw_text, error_message=result["message"])
            auto_note = f"\n（已自動解除 {result['auto_released_display_name']} 的鎖定）" if result.get("auto_released_display_name") else ""
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}{auto_note if auto_note else ''}"}

        target_user_id = result["target_user_id"]
        target_display_name = result["display_name"]
        release_key = result.get("location") or target_user_id
        auto_note = f"\n（已自動解除 {result['auto_released_display_name']} 的鎖定）" if result.get("auto_released_display_name") else ""
        if decision["status"] == "skip_to_next" and decision["admin_message"] and getattr(self.queue_manager, "notifier", None) is not None:
            self.queue_manager.notifier.notify_user(user_id, decision["admin_message"])
        if self.notification_service is not None:
            self.notification_service.broadcast_serve_event(
                admin_user_id=user_id,
                admin_display_name=admin_display_name,
                target_user_id=target_user_id,
                target_display_name=target_display_name,
                command_text=raw_text,
                at_text=now_in_taipei().strftime("%Y-%m-%d %H:%M:%S"),
                platform="Telegram",
            )
        return {
            "status": "success",
            "message": f"✅ 已叫號：{target_display_name}{auto_note}",
            "reply_markup": {
                "inline_keyboard": [
                    [{"text": "解除鎖定", "callback_data": f"/admin/release {release_key}"}]
                ]
            }
        }

    def _handle_admin_release(self, *, user_id: str, args: list[str]) -> dict:
        """處理 Telegram admin 解除叫號鎖定（依位置編號）。"""
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        if not args:
            return {"status": "error", "message": "用法：/admin/release [位置編號]"}

        location = args[0]
        result = release_user(queue_manager=self.queue_manager, location=location)
        if result["status"] != "released":
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}

        target_id = result["user_id"]
        target_display_name = result["display_name"]
        self._broadcast_simple_event(
            category="admin_action",
            title="Demo完成通知",
            actor_label=f"管理員：{self._format_profile_label(user_id)}（{user_id}）",
            target_label=f"對象：{target_display_name}（{target_id}）",
            detail_lines=[f"號碼：#{result['queue_number']}"],
        )
        return {"status": "success", "message": f"✅ 已解除 {target_display_name} 的叫號鎖定"}

    def _handle_admin_skip(self, *, user_id: str, args: list[str], raw_text: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        if args:
            result = self.queue_manager.skip_specific(args[0])
        else:
            result = self.queue_manager.skip_next()

        if result["status"] != "skipped":
            self._broadcast_error_event(user_id=user_id, command_text=raw_text, error_message=result["message"])
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}

        target_user_id = result["id"]
        self._broadcast_simple_event(
            category="skip",
            title="跳過通知",
            actor_label=f"管理員：{self._format_profile_label(user_id)}（{user_id}）",
            target_label=f"對象：{self.db.get_display_name(target_user_id)}（{target_user_id}）",
            detail_lines=[f"指令：{raw_text}"],
        )
        return {"status": "success", "message": f"✅ 已跳過：{self.db.get_display_name(target_user_id)}"}

    def _push_dashboard_announcement(self, user_id: str) -> None:
        if not self.announcement_service:
            return

        profile = self.queue_manager.db.get_user_profile(user_id)
        display_name = profile.display_name if profile and profile.display_name else user_id
        try:
            self.announcement_service.announce_called_guest(display_name=display_name)
        except Exception:
            return

    def _broadcast_simple_event(
        self,
        *,
        category: str,
        title: str,
        actor_label: str,
        target_label: str,
        detail_lines: list[str] | None = None,
    ) -> None:
        """以統一格式廣播一般 Telegram admin 事件。"""
        if self.notification_service is None:
            return
        self.notification_service.broadcast_event(
            category=category,
            title=title,
            actor_label=actor_label,
            target_label=target_label,
            detail_lines=detail_lines,
            platform="Telegram",
        )

    def _broadcast_error_event(self, *, user_id: str, command_text: str, error_message: str) -> None:
        """廣播 Telegram 指令失敗事件給有訂閱的 admin。"""
        if self.notification_service is None:
            return
        self.notification_service.broadcast_event(
            category="error",
            title="失敗通知",
            actor_label=f"使用者：{self._format_profile_label(user_id)}",
            target_label=f"指令：{command_text}",
            detail_lines=[f"原因：{error_message}"],
            platform="Telegram",
        )

    def _format_profile_label(self, user_id: str) -> str:
        return self.db.get_display_name(user_id)

    def _resolve_line_display_name_for_review(self, user_id: str) -> str:
        return fetch_line_profile_display_name(
            channel_access_token=self.channel_access_token,
            user_id=user_id,
        )
