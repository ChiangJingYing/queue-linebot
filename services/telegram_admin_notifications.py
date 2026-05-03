"""Telegram admin notification preferences and broadcast helpers."""

from __future__ import annotations

from collections.abc import Callable


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
    def __init__(self, *, db, sender: Callable[[str, str], None]) -> None:
        self.db = db
        self.sender = sender

    def broadcast(self, *, category: str, message: str) -> list[str]:
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
