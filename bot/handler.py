"""LINE Bot webhook 主處理器。

這個模組是 LINE Messaging API 事件的進入點，負責：
- 初始化 queue / notifier / rich menu / pending state 等依賴
- 將 webhook event 轉成文字命令
- 把命令分派到一般使用者、註冊、客服與管理員 mixin
- 維護跨訊息的暫存狀態，例如註冊流程與封隊取消確認
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Optional

from bot.handler_admin import HandlerAdminMixin
from bot.handler_commands import HandlerCommandsMixin
from bot.handler_homework import HandlerHomeworkMixin
from bot.handler_registration import HandlerRegistrationMixin
from bot.handler_support import HandlerSupportMixin
from core.queue_manager import QueueManager
from core.validators import validate_command
from services.homework_demo import HomeworkBookingService
from services.notifier import Notifier
from services.pending_state_store import MemoryPendingStateStore
from services.special_serve_rules import normalize_special_serve_rules
from services.telegram_admin_notifications import TelegramAdminNotificationService
from services.vip_service import VipService

RICH_MENU_SWITCH_DATA_PREFIXES = (
    "go-member-page",
    "go-admin-page",
)


class LineBotHandler(
    HandlerAdminMixin,
    HandlerCommandsMixin,
    HandlerHomeworkMixin,
    HandlerRegistrationMixin,
    HandlerSupportMixin,
):
    """處理 LINE webhook 事件並分派到對應子流程。"""

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
        user_rich_menu_page2_id: str = "",
        location_options: dict[str, list[str]] | None = None,
        announcement_service: object | None = None,
        new_order_idle_seconds: int = 300,
        new_order_announcement_text: str = "您有新訂單",
        admin_serve_cooldown_seconds: int = 3,
        telegram_sender=None,
        special_serve_rules: dict | None = None,
        homework_booking_service: HomeworkBookingService | None = None,
    ) -> None:
        """建立 LINE handler 與其所有共用依賴。"""
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token
        #: 共用隊列核心；實際 join/cancel/serve 等規則都委派給它。
        self.queue_manager = queue_manager or QueueManager()
        self.vip_service = vip_service or VipService(self.queue_manager.db)
        #: 對使用者發送私訊推播、切換 rich menu 等平台通知工具。
        self.notifier = Notifier(
            channel_secret=self.channel_secret,
            channel_access_token=self.channel_access_token,
            admin_rich_menu_page2_id=admin_rich_menu_page2_id,
        )
        self.admin_ids = list(admin_ids) if admin_ids else []
        self.admin_rich_menu_id = admin_rich_menu_id
        self.admin_rich_menu_page2_id = admin_rich_menu_page2_id
        self.user_rich_menu_id = user_rich_menu_id
        self.user_rich_menu_page2_id = user_rich_menu_page2_id
        self.location_options = location_options or {"A": ["1", "2"], "B": ["1", "2"]}
        #: 額外的 dashboard / 語音公告通道；不負責對被叫號者送私訊。
        self.announcement_service = announcement_service
        #: 隊列從長時間閒置恢復時，多久以上算需要播一次「新訂單」公告。
        self.new_order_idle_seconds = max(int(new_order_idle_seconds), 0)
        self.new_order_announcement_text = (new_order_announcement_text or "您有新訂單").strip() or "您有新訂單"
        #: 最近一次有人加入的時間，用來判斷是否已閒置夠久。
        self._new_order_last_joined_at = datetime.now()
        #: 管理員清空隊列後，強制下一次新加入時播一次新訂單公告。
        self._announce_new_order_on_next_join = False
        #: 暫存 register / cancel 等跨訊息多步驟流程狀態。
        self.pending_state_store = MemoryPendingStateStore()
        #: 避免管理員重複點擊導致 serve 併發執行。
        self._admin_serve_lock = threading.Lock()
        #: serve 成功後的冷卻秒數，避免短時間重複叫號同一位。
        self._admin_serve_cooldown_seconds = max(int(admin_serve_cooldown_seconds), 0)
        self._admin_serve_cooldown_clock = time.monotonic
        #: 最近一次成功叫號的 monotonic timestamp。
        self._last_admin_serve_at = 0.0
        #: 最近一次成功叫號對象名稱，用於冷卻提示文案。
        self._last_admin_serve_label = ""
        #: Config-driven special serve rules shared with Telegram admin serve flow.
        self.special_serve_rules = normalize_special_serve_rules(special_serve_rules)
        self.homework_booking_service = homework_booking_service
        #: 廣播給 Telegram admin 訂閱者的後台通知 service。
        self.notification_service = (
            TelegramAdminNotificationService(db=self.queue_manager.db, sender=telegram_sender)
            if telegram_sender is not None
            else None
        )

    def handle_event(self, event) -> list:
        """處理單一 LINE event。

        目前只對文字訊息事件做命令分派；其他事件型別直接忽略。
        若有 user id，會先同步 rich menu，確保目前角色對應的選單正確。
        """
        user_id = getattr(getattr(event, "source", None), "userId", "")
        if user_id:
            self._sync_rich_menu(user_id)
        if hasattr(event, "message") and getattr(event.message, "type", None) == "text":
            return self._handle_message(event)
        return []

    def _handle_message(self, event) -> list:
        """解析 LINE 文字訊息並路由到對應 handler。"""
        text = event.message.text
        user_id = event.source.userId
        reply_token = getattr(event, "reply_token", getattr(event, "replyToken", ""))

        if text.startswith("homework:") and self.homework_booking_service and self.homework_booking_service.is_enabled():
            return self._capture_homework_input(user_id, text.strip(), reply_token)

        if text.startswith(RICH_MENU_SWITCH_DATA_PREFIXES):
            return []

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
            if str(pending_action.get("type") or "").startswith("homework_"):
                return self._capture_homework_input(user_id, text.strip(), reply_token)

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
        elif command == "/homework":
            return self._handle_homework_register(user_id, reply_token)
        elif command == "/homework/register":
            return self._handle_homework_profile_update(user_id, reply_token)
        elif command == "/homework/cancel":
            return self._handle_homework_cancel(user_id, reply_token)
        elif command == "/homework/cancel/apply":
            return self._handle_homework_cancel_apply(user_id, reply_token)
        elif command == "/homework/list":
            return self._handle_homework_list(user_id, reply_token)
        elif command == "/coffee":
            return self._handle_coffee(user_id, reply_token)
        elif command == "/admin/apply":
            return self._handle_admin_apply_command(user_id, args, reply_token)
        elif command.startswith("/admin/"):
            return self._handle_admin(user_id, command, args, reply_token)

        return self._reply(reply_token, "未知指令，請輸入 /help 查看可用功能。")

    def _get_pending_state(self, user_id: str, flow: str | None = None) -> dict:
        """讀取指定使用者的暫存流程狀態。

        - 指定 ``flow`` 時，僅取該流程
        - 未指定時，依序嘗試 ``register`` 與 ``cancel``
        """
        if flow is not None:
            return self.pending_state_store.get(user_id=user_id, flow=flow)

        for candidate_flow in ("register", "cancel", "homework"):
            if state := self.pending_state_store.get(user_id=user_id, flow=candidate_flow):
                return state
        return {}

    def _set_pending_state(self, user_id: str, flow: str, state: dict) -> None:
        """寫入指定使用者的流程暫存狀態。"""
        self.pending_state_store.set(user_id=user_id, flow=flow, state=state)

    def _clear_pending_state(self, user_id: str, flow: str) -> None:
        """清除指定使用者的流程暫存狀態。"""
        self.pending_state_store.clear(user_id=user_id, flow=flow)
