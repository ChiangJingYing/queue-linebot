"""LINE Bot Webhook Handler."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

from bot.handler_admin import HandlerAdminMixin
from bot.handler_commands import HandlerCommandsMixin
from bot.handler_registration import HandlerRegistrationMixin
from bot.handler_support import HandlerSupportMixin
from core.queue_manager import QueueManager
from core.validators import validate_command
from services.notifier import Notifier
from services.pending_state_store import MemoryPendingStateStore
from services.telegram_admin_notifications import TelegramAdminNotificationService
from services.vip_service import VipService


class LineBotHandler(
    HandlerAdminMixin,
    HandlerCommandsMixin,
    HandlerRegistrationMixin,
    HandlerSupportMixin,
):
    """Handles LINE Bot webhook events."""

    def __init__(
        self,
        channel_secret: str = "",
        channel_access_token: str = "",
        queue_manager: Optional[QueueManager] = None,
        vip_service: Optional[VipService] = None,
        admin_ids: list[str] | None = None,
        admin_rich_menu_id: str = "",
        admin_rich_menu_page2_id: str = "",
        user_rich_menu_id: str = "",
        location_options: dict[str, list[str]] | None = None,
        announcement_service: object | None = None,
        new_order_idle_seconds: int = 300,
        new_order_announcement_text: str = "您有新訂單",
        admin_serve_cooldown_seconds: int = 3,
        telegram_sender=None,
    ) -> None:
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token
        self.queue_manager = queue_manager or QueueManager()
        self.vip_service = vip_service or VipService(self.queue_manager.db)
        self.notifier = Notifier(
            channel_secret=self.channel_secret,
            channel_access_token=self.channel_access_token,
            admin_rich_menu_page2_id=admin_rich_menu_page2_id,
        )
        self.admin_ids = list(admin_ids) if admin_ids else []
        self.admin_rich_menu_id = admin_rich_menu_id
        self.admin_rich_menu_page2_id = admin_rich_menu_page2_id
        self.user_rich_menu_id = user_rich_menu_id
        self.location_options = location_options or {"A": ["1", "2"], "B": ["1", "2"]}
        self.announcement_service = announcement_service
        self.new_order_idle_seconds = max(int(new_order_idle_seconds), 0)
        self.new_order_announcement_text = (new_order_announcement_text or "您有新訂單").strip() or "您有新訂單"
        self._new_order_last_joined_at = datetime.now()
        self._announce_new_order_on_next_join = False
        self.pending_state_store = MemoryPendingStateStore()
        self._admin_serve_lock = threading.Lock()
        self._admin_serve_cooldown_seconds = max(int(admin_serve_cooldown_seconds), 0)
        self._admin_serve_cooldown_clock = time.monotonic
        self._last_admin_serve_at = 0.0
        self._last_admin_serve_label = ""
        self.notification_service = (
            TelegramAdminNotificationService(db=self.queue_manager.db, sender=telegram_sender)
            if telegram_sender is not None
            else None
        )

    def handle_event(self, event) -> list:
        user_id = getattr(getattr(event, "source", None), "userId", "")
        if user_id:
            self._sync_rich_menu(user_id)
        if hasattr(event, "message") and getattr(event.message, "type", None) == "text":
            return self._handle_message(event)
        return []

    def _handle_message(self, event) -> list:
        text = event.message.text
        user_id = event.source.userId
        reply_token = getattr(event, "reply_token", getattr(event, "replyToken", ""))

        if text == "switch_page2":
            return self._handle_admin_page_switch(user_id, "page2", reply_token)
        if text == "switch_page1":
            return self._handle_admin_page_switch(user_id, "page1", reply_token)

        command, args = validate_command(text)
        pending_action = self._get_pending_state(user_id)
        if pending_action and not text.strip().startswith("/"):
            if pending_action.get("type") == "register_name":
                return self._capture_register_name(user_id, text.strip(), reply_token)
            if pending_action.get("type") == "register_location_group":
                return self._capture_register_location_group(user_id, text.strip(), reply_token)
            if pending_action.get("type") == "register_location_item":
                return self._capture_register_location_item(user_id, text.strip(), reply_token)
            if pending_action.get("type") == "cancel_when_closed":
                return self._handle_cancel_confirmation(user_id, text.strip(), reply_token)

        admin_history_mode = False
        if command == "/history" and args and self._is_admin(user_id):
            command = "/admin/history"
            admin_history_mode = True

        if command == "/join":
            return self._handle_join(user_id, args, reply_token)
        elif command == "/cancel":
            return self._handle_cancel(user_id, reply_token)
        elif command == "/status":
            return self._handle_status(user_id, reply_token)
        elif command == "/history" and not admin_history_mode:
            return self._handle_user_history(user_id, reply_token)
        elif command == "/help":
            return self._handle_help(user_id, reply_token)
        elif command == "/register":
            return self._handle_register(user_id, args, reply_token)
        elif command == "/coffee":
            return self._handle_coffee(user_id, reply_token)
        elif command == "/admin/apply":
            return self._handle_admin_apply_command(user_id, args, reply_token)
        elif command.startswith("/admin/"):
            return self._handle_admin(user_id, command, args, reply_token)

        return self._reply(reply_token, "未知指令，請輸入 /help 查看可用功能。")

    def _get_pending_state(self, user_id: str, flow: str | None = None) -> dict:
        if flow is not None:
            return self.pending_state_store.get(user_id=user_id, flow=flow)

        for candidate_flow in ("register", "cancel"):
            if state := self.pending_state_store.get(user_id=user_id, flow=candidate_flow):
                return state
        return {}

    def _set_pending_state(self, user_id: str, flow: str, state: dict) -> None:
        self.pending_state_store.set(user_id=user_id, flow=flow, state=state)

    def _clear_pending_state(self, user_id: str, flow: str) -> None:
        self.pending_state_store.clear(user_id=user_id, flow=flow)
