"""Telegram admin 推播偏好與廣播 helper。"""

from __future__ import annotations

from collections.abc import Callable
import logging
import re

from services.background_dispatcher import DEFAULT_DISPATCHER
from services.line_profile_lookup import is_probable_line_user_id


logger = logging.getLogger(__name__)


#: 可由 admin 自行開關的 Telegram 推播分類。
TELEGRAM_NOTIFICATION_CATEGORIES = [
    "register",
    "join",
    "cancel",
    "serve",
    "skip",
    "admin_action",
    "error",
]


class TelegramAdminNotificationService:
    """依 admin 偏好發送 Telegram 管理通知。"""

    _USER_REF_PATTERN = re.compile(r"^(?P<prefix>[^：]+)：(?P<display>.+)（(?P<user_id>[^（）]+)）$")
    _MANAGEMENT_TITLES = {"管理叫號通知", "管理操作通知", "Demo完成通知", "跳過通知"}

    def __init__(
        self,
        *,
        db,
        sender: Callable[[str, str], None],
        dispatcher: object | None = None,
        line_display_name_resolver: Callable[[str], str] | None = None,
    ) -> None:
        """初始化偏好資料來源與實際 sender。"""
        #: 用來查詢 admin 訂閱偏好與接收者清單的資料來源。
        self.db = db
        #: 實際執行 Telegram 私訊發送的 callable。
        self.sender = sender
        #: best-effort 背景派送器；測試預設同步執行。
        self.dispatcher = dispatcher or DEFAULT_DISPATCHER
        #: 可選 LINE profile display name resolver。
        self.line_display_name_resolver = line_display_name_resolver

    def broadcast(
        self,
        *,
        category: str,
        message: str | None = None,
        message_builder: Callable[[], str] | None = None,
    ) -> list[str]:
        """對啟用指定分類的 admin 廣播原始訊息。"""
        delivered = list(self.db.get_admins_to_notify(category))

        def _send_all() -> None:
            resolved_message = message_builder() if message_builder is not None else str(message or "")
            for user_id in delivered:
                try:
                    self.sender(user_id, resolved_message)
                except Exception:
                    logger.exception("Telegram admin notification failed user_id=%s category=%s", user_id, category)

        if delivered:
            self.dispatcher.dispatch(_send_all)
        return delivered

    def broadcast_event(
        self,
        *,
        category: str,
        title: str,
        actor_label: str,
        target_label: str,
        detail_lines: list[str] | None = None,
        platform: str | None = None,
    ) -> list[str]:
        """將一般事件組裝成一致格式後廣播。"""
        def _build_message() -> str:
            rendered_actor_label = self._normalize_management_label(title=title, label=actor_label)
            rendered_target_label = self._normalize_management_label(title=title, label=target_label)
            lines = [f"🔔 {title}"]
            if platform:
                lines.append(f"平台：{platform}")
            lines.extend([rendered_actor_label, rendered_target_label])
            if detail_lines:
                lines.extend(detail_lines)
            return "\n".join(lines)

        return self.broadcast(category=category, message_builder=_build_message)

    def broadcast_serve_event(
        self,
        *,
        admin_user_id: str,
        admin_display_name: str,
        target_user_id: str,
        target_display_name: str,
        command_text: str,
        at_text: str,
        platform: str | None = None,
    ) -> list[str]:
        """廣播叫號事件，保留時間、管理員與目標對象資訊。"""
        def _build_message() -> str:
            lines = ["🔔 管理叫號通知"]
            if platform:
                lines.append(f"平台：{platform}")
            lines.extend(
                [
                    f"時間：{at_text}",
                    f"管理員：{self._format_user_reference(user_id=admin_user_id, display_name=admin_display_name)}",
                    f"指令：{command_text}",
                    f"叫號對象：{self._format_user_reference(user_id=target_user_id, display_name=target_display_name)}",
                ]
            )
            return "\n".join(lines)

        return self.broadcast(category="serve", message_builder=_build_message)

    def _normalize_management_label(self, *, title: str, label: str) -> str:
        """Hide LINE user ids in management-related labels."""
        if title not in self._MANAGEMENT_TITLES:
            return label

        match = self._USER_REF_PATTERN.fullmatch(str(label or "").strip())
        if not match:
            return label

        prefix = match.group("prefix")
        display_name = match.group("display")
        user_id = match.group("user_id")
        return f"{prefix}：{self._format_user_reference(user_id=user_id, display_name=display_name)}"

    def _format_user_reference(self, *, user_id: str, display_name: str) -> str:
        """Render a user reference, hiding LINE ids when possible."""
        normalized_user_id = str(user_id or "").strip()
        fallback_name = str(display_name or "").strip() or normalized_user_id
        if is_probable_line_user_id(normalized_user_id):
            return self._resolve_line_display_name(normalized_user_id) or fallback_name
        return f"{fallback_name}（{normalized_user_id}）" if normalized_user_id else fallback_name

    def _resolve_line_display_name(self, user_id: str) -> str:
        if not callable(self.line_display_name_resolver):
            return ""
        try:
            return str(self.line_display_name_resolver(user_id) or "").strip()
        except Exception:
            logger.exception("LINE display name resolver failed user_id=%s", user_id)
            return ""
