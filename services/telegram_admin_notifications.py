"""Telegram admin 推播偏好與廣播 helper。"""

from __future__ import annotations

from collections.abc import Callable


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

    def __init__(self, *, db, sender: Callable[[str, str], None]) -> None:
        """初始化偏好資料來源與實際 sender。"""
        #: 用來查詢 admin 訂閱偏好與接收者清單的資料來源。
        self.db = db
        #: 實際執行 Telegram 私訊發送的 callable。
        self.sender = sender

    def broadcast(self, *, category: str, message: str) -> list[str]:
        """對啟用指定分類的 admin 廣播原始訊息。"""
        delivered: list[str] = []
        for user_id in self.db.get_admins_to_notify(category):
            self.sender(user_id, message)
            delivered.append(user_id)
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
        lines = [f"🔔 {title}"]
        if platform:
            lines.append(f"平台：{platform}")
        lines.extend([actor_label, target_label])
        if detail_lines:
            lines.extend(detail_lines)
        return self.broadcast(category=category, message="\n".join(lines))

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
        lines = ["🔔 管理叫號通知"]
        if platform:
            lines.append(f"平台：{platform}")
        lines.extend(
            [
                f"時間：{at_text}",
                f"管理員：{admin_display_name}（{admin_user_id}）",
                f"指令：{command_text}",
                f"叫號對象：{target_display_name}（{target_user_id}）",
            ]
        )
        return self.broadcast(category="serve", message="\n".join(lines))
