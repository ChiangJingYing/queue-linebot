"""Telegram command parsing and admin self-service flows."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from core.database import DatabaseManager
from core.queue_manager import QueueManager
from core.time_utils import format_display_time, now_in_taipei
from core.validators import validate_command
from services.telegram_admin_notifications import (
    TELEGRAM_NOTIFICATION_CATEGORIES,
    TelegramAdminNotificationService,
)
from services.vip_service import VipService


class TelegramCommandService:
    USER_REPLY_KEYBOARD = [
        [{"text": "舉手"}, {"text": "放棄"}, {"text": "看狀態"}],
        [{"text": "看紀錄"}, {"text": "設定資料"}, {"text": "排隊紀錄"}],
    ]
    ADMIN_REPLY_KEYBOARD_PAGE1 = [
        [{"text": "叫號"}, {"text": "提醒"}, {"text": "完整狀態"}],
        [{"text": "開關排隊"}, {"text": "更多功能"}],
    ]
    ADMIN_REPLY_KEYBOARD_PAGE2 = [
        [{"text": "清空隊列"}, {"text": "VIP 狀態"}, {"text": "推播設定"}],
        [{"text": "幫助"}, {"text": "返回主選單"}],
    ]

    USER_TEXT_ALIASES = {
        "舉手": "/join",
        "放棄": "/cancel",
        "看狀態": "/status",
        "看紀錄": "/hostory",
        "設定資料": "/register",
        "排隊紀錄": "/history",
    }
    ADMIN_TEXT_ALIASES = {
        "叫號": "/admin/serve",
        "提醒": "/admin/ping",
        "完整狀態": "/admin/status",
        "開關排隊": "/admin/join",
        "更多功能": "switch_page2",
        "清空隊列": "/admin/clear",
        "VIP 狀態": "/admin/vip status",
        "推播設定": "open_notify_settings",
        "幫助": "/help",
        "返回主選單": "switch_page1",
    }

    def __init__(self, *, db, telegram_sender=None, location_options: dict[str, list[str]] | None = None) -> None:
        self.db = db
        self.queue_manager = QueueManager(db) if isinstance(db, DatabaseManager) else None
        self.vip_service = VipService(db) if isinstance(db, DatabaseManager) else None
        self.location_options = location_options or {"A": ["1", "2"], "B": ["1", "2"]}
        self.notification_service = None
        if telegram_sender is not None:
            self.notification_service = TelegramAdminNotificationService(db=db, sender=telegram_sender)

    def handle_text(self, *, user_id: str, text: str) -> dict:
        raw_text = text.strip()
        normalized_text = self._normalize_text_alias(user_id=user_id, text=raw_text)

        if pending := self._get_pending_register_state(user_id):
            if normalized_text.startswith("/") and normalized_text != "/register":
                self._clear_pending_register_state(user_id)
            else:
                return self._handle_register_pending(user_id=user_id, text=raw_text, state=pending)

        if normalized_text == "switch_page2":
            return self._handle_admin_page_switch(user_id=user_id, target_page="page2")
        if normalized_text == "switch_page1":
            return self._handle_admin_page_switch(user_id=user_id, target_page="page1")
        if normalized_text == "open_notify_settings":
            return self._handle_admin_notify_menu(user_id=user_id)
        if normalized_text.startswith("notify:"):
            return self._handle_admin_notify_callback(user_id=user_id, payload=normalized_text)
        if normalized_text in {"確認放棄", "取消放棄"}:
            return self._handle_cancel_confirmation(user_id=user_id, text=normalized_text)

        command, args = validate_command(normalized_text)
        if command == "/menu":
            return self._handle_menu(user_id=user_id)
        if command == "/hostory":
            return self._handle_user_history(user_id=user_id)
        if command == "/register":
            return self._handle_register(user_id=user_id, args=args)
        if command == "/join":
            return self._handle_join(user_id=user_id, args=args, raw_text=raw_text)
        if command == "/cancel":
            return self._handle_cancel(user_id=user_id, raw_text=raw_text)
        if command == "/status":
            return self._handle_status(user_id=user_id)
        if command == "/history":
            return self._handle_user_history(user_id=user_id)
        if command == "/help":
            return self._handle_help(user_id=user_id)
        if command == "/admin/apply":
            return self._handle_admin_apply(user_id=user_id, args=args)
        if command == "/admin/notify":
            return self._handle_admin_notify(user_id=user_id, args=args)
        if command == "/admin/join":
            return self._handle_admin_join(user_id=user_id, args=args)
        if command == "/admin/status":
            return self._handle_admin_status(user_id=user_id)
        if command == "/admin/stats":
            return self._handle_admin_stats(user_id=user_id)
        if command == "/admin/history":
            return self._handle_admin_history(user_id=user_id, args=args)
        if command == "/admin/export":
            return self._handle_admin_export(user_id=user_id)
        if command == "/admin/clear":
            return self._handle_admin_clear(user_id=user_id, raw_text=raw_text)
        if command == "/admin/ping":
            return self._handle_admin_ping(user_id=user_id, args=args)
        if command == "/admin/serve":
            return self._handle_admin_serve(user_id=user_id, args=args, raw_text=raw_text)
        if command == "/admin/skip":
            return self._handle_admin_skip(user_id=user_id, args=args, raw_text=raw_text)
        if command == "/admin/vip":
            return self._handle_admin_vip(user_id=user_id, args=args, raw_text=raw_text)
        return {"status": "error", "message": "Unknown command."}

    def _handle_menu(self, *, user_id: str) -> dict:
        return {
            "status": "success",
            "message": "請使用下方功能選單。",
            "reply_markup": self._reply_keyboard_markup(user_id),
        }

    def _handle_register(self, *, user_id: str, args: list[str]) -> dict:
        if args:
            return {"status": "error", "message": "❌ 錯誤：/register 不接受參數，請直接輸入 /register 後依提示完成註冊。"}

        self._set_pending_register_state(user_id, {"type": "register_name"})
        return {"status": "pending", "message": "請輸入你的學號。"}

    def _handle_join(self, *, user_id: str, args: list[str], raw_text: str) -> dict:
        queue_type = args[0].lower() if args else "regular"
        profile = self.db.get_user_profile(user_id)
        if profile is None or not profile.display_name or not profile.location:
            return {
                "status": "error",
                "message": "❌ 錯誤：請先完成註冊（學號與座位）後再加入隊列。",
                "reply_markup": self._inline_keyboard_markup(
                    [[{"text": "設定基本資料", "callback_data": "/register"}]]
                ),
            }

        result = self.queue_manager.join(user_id, queue_type)
        if result["status"] != "success":
            self._broadcast_error_event(user_id=user_id, command_text=raw_text, error_message=result["message"])
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}

        self._broadcast_simple_event(
            category="join",
            title="排隊通知",
            actor_label=f"使用者：{self._format_profile_label(user_id)}",
            target_label=f"隊列：{queue_type}",
            detail_lines=[
                f"號碼：#{result['queue_number']}",
                f"目前總人數：{result['total_in_queue']}",
            ],
        )
        return {
            "status": "success",
            "message": f"✅ 已加入隊列，號碼 #{result['queue_number']}（目前 {result['total_in_queue']} 人）",
        }

    def _handle_cancel(self, *, user_id: str, raw_text: str) -> dict:
        if not self.queue_manager.get_queue_enabled() and self.queue_manager.get_user_position(user_id) is not None:
            self.db.set_config(f"telegram_pending_cancel:{user_id}", json.dumps({"type": "cancel_when_closed", "step": 1}))
            return {
                "status": "pending",
                "message": "當前隊列已關閉，確定要放棄嗎？\n若放棄無法再加入到隊列中！",
                "reply_markup": self._inline_keyboard_markup(self._cancel_confirmation_inline_keyboard()),
            }

        result = self.queue_manager.cancel(user_id)
        if result["status"] != "cancelled":
            self._broadcast_error_event(user_id=user_id, command_text=raw_text, error_message=result["message"])
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}

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

    def _handle_admin_notify(self, *, user_id: str, args: list[str]) -> dict:
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
            enabled = not self.queue_manager.get_queue_enabled()
            self.queue_manager.set_queue_enabled(enabled)
            return {"status": "success", "message": f"✅ 隊列已{'開啟' if enabled else '關閉'}"}

        sub_cmd = args[0].lower()
        if sub_cmd == "on":
            self.queue_manager.set_queue_enabled(True)
            return {"status": "success", "message": "✅ 隊列已開啟"}
        if sub_cmd == "off":
            self.queue_manager.set_queue_enabled(False)
            return {"status": "success", "message": "✅ 隊列已關閉"}
        if sub_cmd == "status":
            enabled = self.queue_manager.get_queue_enabled()
            return {"status": "success", "message": f"📋 隊列狀態：{'已開啟' if enabled else '已關閉'}"}

        return {"status": "error", "message": "用法：/admin/join [on/off] 切換狀態 或 /admin/join status 查看狀態"}

    def _handle_admin_status(self, *, user_id: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        status = self.queue_manager.get_status()
        entries = self.queue_manager.get_queue()
        regular_lines: list[str] = []
        vip_lines: list[str] = []
        regular_idx = 0
        vip_idx = 0

        for entry in entries:
            profile = self.db.get_user_profile(entry.user_id)
            badge = "✅" if profile and profile.verified else "🕓"
            label = self.db.get_display_name(entry.user_id)
            joined = format_display_time(entry.join_time, include_date=False)
            line = f"{label} {badge} — {joined}"
            if entry.queue_type == "vip":
                vip_idx += 1
                vip_lines.append(f"#{vip_idx} {line}")
            else:
                regular_idx += 1
                regular_lines.append(f"#{regular_idx} {line}")

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

        stats = self.queue_manager.get_stats()
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
            status = self.vip_service.get_vip_status()
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
            result = self.vip_service.toggle_vip(enabled)
            self._broadcast_simple_event(
                category="admin_action",
                title="管理操作通知",
                actor_label=f"管理員：{self._format_profile_label(user_id)}（{user_id}）",
                target_label=f"指令：{raw_text}",
                detail_lines=[f"結果：{result['message']}"],
            )
            return {"status": "success", "message": f"✅ {result['message']}"}

        if sub_cmd == "clear":
            result = self.queue_manager.clear_vip_queue()
            self._broadcast_simple_event(
                category="admin_action",
                title="管理操作通知",
                actor_label=f"管理員：{self._format_profile_label(user_id)}（{user_id}）",
                target_label=f"指令：{raw_text}",
                detail_lines=[f"結果：移除 {result['removed_count']} 筆 VIP 隊列"],
            )
            return {"status": "success", "message": f"✅ 已清空 VIP 隊列，移除 {result['removed_count']} 筆"}

        return {"status": "error", "message": "用法：/admin/vip [status|toggle|clear]"}

    def _handle_admin_history(self, *, user_id: str, args: list[str]) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}
        if not args:
            return {"status": "error", "message": "用法：/admin/history [ID]"}

        target_id = args[0]
        history = self.queue_manager.get_user_history(target_id)
        if not history:
            return {"status": "error", "message": f"查無 {target_id} 的歷史紀錄"}

        lines = [f"🧾 {target_id} 歷史紀錄"]
        for item in history[:10]:
            lines.append(
                f"- {format_display_time(item['created_at'])}: {item['event_type']} ({item['queue_type'] or '-'})"
            )
        return {"status": "success", "message": "\n".join(lines)}

    def _handle_admin_export(self, *, user_id: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        csv_data = self.queue_manager.export_queue_csv(limit=200)
        lines = csv_data.splitlines()
        if len(csv_data) > 3500:
            preview = "\n".join(lines[:12])
            return {
                "status": "success",
                "message": f"📤 CSV 匯出（總計 {max(len(lines) - 1, 0)} 筆，內容過長已預覽）\n{preview}",
            }
        return {
            "status": "success",
            "message": f"📤 CSV 匯出（總計 {max(len(lines) - 1, 0)} 筆）\n{csv_data}",
        }

    def _handle_admin_clear(self, *, user_id: str, raw_text: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        result = self.queue_manager.clear_all_queue(keep_admin_user_ids=set())
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
        result = self.queue_manager.ping_user(target_id)
        if result["status"] != "success":
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}
        return {"status": "success", "message": f"✅ 已提醒 {result['display_name']}（{result['user_id']}）"}

    def _handle_status(self, *, user_id: str) -> dict:
        position = self.queue_manager.get_user_position(user_id)
        if position is None:
            total_count = len(self.queue_manager.get_queue())
            return {"status": "success", "message": f"📊 目前有 {total_count} 人在排隊中"}

        ahead_count = max(position - 1, 0)
        return {
            "status": "success",
            "message": f"📊 目前排在第 {position} 位\n前面還有 {ahead_count} 人",
        }

    def _handle_user_history(self, *, user_id: str) -> dict:
        history = self.queue_manager.get_user_history(user_id)
        if not history:
            return {"status": "success", "message": "查無排隊歷史紀錄。"}

        lines = ["排隊歷史紀錄"]
        for item in history[:10]:
            lines.append(
                f"- {format_display_time(item['created_at'])}: {item['event_type']} ({item['queue_type'] or '-'})"
            )
        return {"status": "success", "message": "\n".join(lines)}

    def _handle_help(self, *, user_id: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        msg = (
            "📋 隊列系統指令\n\n"
            "**一般使用者：**\n"
            "/register - 依提示完成學號與座位註冊\n"
            "/join - 以自己身分加入一般隊列\n"
            "/join vip - 以自己身分加入 VIP 隊列\n"
            "/cancel - 取消排隊\n"
            "/status - 查看隊列狀態\n"
            "/history - 查看你的排隊歷史\n"
            "/coffee - 取得 VIP 連結\n"
            "**管理員指令（/admin/ 開頭）：**\n"
            "/admin/serve - 叫下一位\n"
            "/admin/serve [id] - 叫指定使用者\n"
            "/admin/ping - 手動提醒下一位\n"
            "/admin/ping [id] - 手動提醒指定使用者\n"
            "/admin/status - 完整狀態\n"
            "/admin/stats - 統計面板\n"
            "/admin/clear - 清空全部隊列\n"
            "/admin/vip toggle [on/off] - 開關 VIP 隊列\n"
            "/admin/vip clear - 清空 VIP 隊列\n"
            "/admin/join [on/off] - 切換總隊列狀態\n"
            "/admin/join status - 查看總隊列狀態\n"
            "/admin/history [id] - 查詢使用者歷史\n"
            "/admin/export - 匯出 CSV 預覽\n"
            "/help - 顯示說明\n"
        )
        return {"status": "success", "message": msg}

    def _normalize_text_alias(self, *, user_id: str, text: str) -> str:
        alias_map = dict(self.USER_TEXT_ALIASES)
        if self.db.is_admin(user_id):
            alias_map.update(self.ADMIN_TEXT_ALIASES)
        return alias_map.get(text, text)

    def _handle_register_pending(self, *, user_id: str, text: str, state: dict) -> dict:
        step_type = state.get("type")
        raw_text = text.strip()

        if step_type == "register_name":
            if not raw_text:
                return {"status": "error", "message": "學號不可為空白，請重新輸入學號。"}
            self._set_pending_register_state(
                user_id,
                {"type": "register_location_group", "display_name": raw_text},
            )
            groups = list(self.location_options.keys())
            return {
                "status": "pending",
                "message": f"請選擇您在第幾排座位：{'、'.join(groups)}",
                "reply_markup": self._inline_keyboard_markup(self._build_inline_keyboard(groups, columns=4)),
            }

        if step_type == "register_location_group":
            normalized_group = raw_text.upper()
            groups = list(self.location_options.keys())
            if normalized_group not in self.location_options:
                return {
                    "status": "error",
                    "message": f"無效的位置，請從以下選擇：{'、'.join(groups)}",
                    "reply_markup": self._inline_keyboard_markup(self._build_inline_keyboard(groups, columns=4)),
                }
            self._set_pending_register_state(
                user_id,
                {
                    "type": "register_location_item",
                    "display_name": str(state.get("display_name") or ""),
                    "group": normalized_group,
                },
            )
            options = self.location_options[normalized_group]
            return {
                "status": "pending",
                "message": f"請選擇您的座位（{normalized_group}-?）：{'、'.join(options)}",
                "reply_markup": self._inline_keyboard_markup(self._build_inline_keyboard(options, columns=4)),
            }

        if step_type == "register_location_item":
            group = str(state.get("group") or "")
            display_name = str(state.get("display_name") or "")
            normalized_item = raw_text.upper()
            options = self.location_options.get(group, [])
            if normalized_item not in options:
                return {
                    "status": "error",
                    "message": f"無效的位置，請從以下選擇：{'、'.join(options)}",
                    "reply_markup": self._inline_keyboard_markup(self._build_inline_keyboard(options, columns=4)),
                }
            self._clear_pending_register_state(user_id)
            return self._complete_register(user_id=user_id, display_name=display_name, location=f"{group}-{normalized_item}")

        self._clear_pending_register_state(user_id)
        return {"status": "error", "message": "❌ 註冊流程已失效，請重新輸入 /register。"}

    def _complete_register(self, *, user_id: str, display_name: str, location: str) -> dict:
        if self.queue_manager is None:
            return {"status": "error", "message": "Queue manager unavailable."}

        result = self.queue_manager.register_name(user_id, display_name, location=location)
        if result["status"] != "success":
            self._broadcast_error_event(user_id=user_id, command_text="/register", error_message=result["message"])
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}

        self._broadcast_simple_event(
            category="register",
            title="註冊通知",
            actor_label=f"使用者：{self._format_profile_label(user_id)}",
            target_label="動作：完成註冊",
        )
        return {
            "status": "success",
            "message": f"✅ 已更新學號：{result['display_name']}\n位置：{result['location']}",
        }

    def _handle_admin_page_switch(self, *, user_id: str, target_page: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        page_num = 2 if target_page == "page2" else 1
        keyboard = self.ADMIN_REPLY_KEYBOARD_PAGE2 if target_page == "page2" else self.ADMIN_REPLY_KEYBOARD_PAGE1
        return {
            "status": "success",
            "message": f"✅ 已切換至第 {page_num} 頁",
            "reply_markup": self._reply_keyboard_markup(user_id, keyboard=keyboard),
        }

    def _handle_cancel_confirmation(self, *, user_id: str, text: str) -> dict:
        state = self._get_pending_cancel_state(user_id)
        normalized = text.strip()

        if normalized == "取消放棄":
            self._clear_pending_cancel_state(user_id)
            return {"status": "success", "message": "好的，已取消放棄"}

        if normalized != "確認放棄":
            return {
                "status": "pending",
                "message": "請點選 quick reply 進行操作。",
                "reply_markup": self._inline_keyboard_markup(self._cancel_confirmation_inline_keyboard()),
            }

        if self.queue_manager.get_user_position(user_id) is None:
            self._clear_pending_cancel_state(user_id)
            return {"status": "error", "message": "❌ 錯誤：你目前不在隊列中。"}

        if state.get("step") == 1:
            self.db.set_config(f"telegram_pending_cancel:{user_id}", json.dumps({"type": "cancel_when_closed", "step": 2}))
            return {
                "status": "pending",
                "message": "您確定要放棄嗎？",
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
        return {
            "keyboard": selected_keyboard,
            "resize_keyboard": True,
            "is_persistent": True,
        }

    def _inline_keyboard_markup(self, keyboard: list[list[dict]]) -> dict:
        return {"inline_keyboard": keyboard}

    def _build_inline_keyboard(self, options: list[str], *, columns: int = 2) -> list[list[dict]]:
        rows: list[list[dict]] = []
        current: list[dict] = []
        for option in options:
            current.append({"text": str(option), "callback_data": str(option)})
            if len(current) >= columns:
                rows.append(current)
                current = []
        if current:
            rows.append(current)
        return rows

    def _cancel_confirmation_inline_keyboard(self) -> list[list[dict]]:
        return [[
            {"text": "確認放棄", "callback_data": "確認放棄"},
            {"text": "取消放棄", "callback_data": "取消放棄"},
        ]]

    def _admin_notify_inline_keyboard(self, prefs: dict[str, bool]) -> list[list[dict]]:
        rows: list[list[dict]] = [
            [
                {"text": "全部開啟", "callback_data": "notify:all:on"},
                {"text": "全部關閉", "callback_data": "notify:all:off"},
            ]
        ]
        for category in TELEGRAM_NOTIFICATION_CATEGORIES:
            status = "✅" if prefs.get(category) else "⬜️"
            rows.append([
                {"text": f"{status} {category}", "callback_data": f"notify:{category}:toggle"}
            ])
        return rows

    def _get_pending_register_state(self, user_id: str) -> dict:
        raw = self.db.get_config(f"telegram_pending_register:{user_id}")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _set_pending_register_state(self, user_id: str, state: dict) -> None:
        self.db.set_config(f"telegram_pending_register:{user_id}", json.dumps(state, ensure_ascii=False))

    def _clear_pending_register_state(self, user_id: str) -> None:
        self.db.set_config(f"telegram_pending_register:{user_id}", "")

    def _get_pending_cancel_state(self, user_id: str) -> dict:
        raw = self.db.get_config(f"telegram_pending_cancel:{user_id}")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _clear_pending_cancel_state(self, user_id: str) -> None:
        self.db.set_config(f"telegram_pending_cancel:{user_id}", "")

    def _handle_admin_serve(self, *, user_id: str, args: list[str], raw_text: str) -> dict:
        if not self.db.is_admin(user_id):
            return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

        admin_profile = self.db.get_user_profile(user_id)
        admin_display_name = (
            admin_profile.display_name if admin_profile and admin_profile.display_name else user_id
        )

        if args:
            target_id = args[0]
            result = self.queue_manager.serve_specific(target_id)
        else:
            result = self.queue_manager.serve_next()

        if result["status"] != "served":
            self._broadcast_error_event(user_id=user_id, command_text=raw_text, error_message=result["message"])
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}

        target_user_id = result["id"]
        target_display_name = self.db.get_display_name(target_user_id)
        if self.notification_service is not None:
            self.notification_service.broadcast_serve_event(
                admin_user_id=user_id,
                admin_display_name=admin_display_name,
                target_user_id=target_user_id,
                target_display_name=target_display_name,
                command_text=raw_text,
                at_text=now_in_taipei().strftime("%Y-%m-%d %H:%M:%S"),
            )
        return {"status": "success", "message": f"✅ 已叫號：{target_display_name}"}

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

    def _broadcast_simple_event(
        self,
        *,
        category: str,
        title: str,
        actor_label: str,
        target_label: str,
        detail_lines: list[str] | None = None,
    ) -> None:
        if self.notification_service is None:
            return
        self.notification_service.broadcast_event(
            category=category,
            title=title,
            actor_label=actor_label,
            target_label=target_label,
            detail_lines=detail_lines,
        )

    def _broadcast_error_event(self, *, user_id: str, command_text: str, error_message: str) -> None:
        if self.notification_service is None:
            return
        self.notification_service.broadcast_event(
            category="error",
            title="失敗通知",
            actor_label=f"使用者：{self._format_profile_label(user_id)}",
            target_label=f"指令：{command_text}",
            detail_lines=[f"原因：{error_message}"],
        )

    def _format_profile_label(self, user_id: str) -> str:
        return self.db.get_display_name(user_id)
