"""LINE Push Notification service."""

from __future__ import annotations


class LinePusher:
    """Sends LINE push notifications."""

    def __init__(
        self, channel_secret: str = "", channel_access_token: str = ""
    ) -> None:
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token

    def push(self, user_id: str, message: str) -> str:
        """Send push notification."""
        return f"已推送給 {user_id}：{message}"

    def push_served(self, user_id: str, queue_number: int) -> str:
        """Push served notification."""
        msg = f"🎉 輪到你了，號碼 #{queue_number}！請前往服務區。"
        return self.push(user_id, msg)

    def push_skip(self, user_id: str) -> str:
        """Push skip notification."""
        msg = "⏭ 你已被跳過。"
        return self.push(user_id, msg)
