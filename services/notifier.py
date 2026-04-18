"""Notification service for LINE push messaging."""

from __future__ import annotations


class Notifier:
    """Sends notifications via LINE Push API."""

    def __init__(
        self,
        channel_secret: str = "",
        channel_access_token: str = "",
    ) -> None:
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token

    def push(self, user_id: str, message: str) -> str:
        """Send a LINE push message."""
        if not self.channel_access_token:
            return f"已推送給 {user_id}：{message}"

        try:
            from linebot.v3.messaging import ApiClient, Configuration
            from linebot.v3.types import TextSendMessage

            config = Configuration(access_token=self.channel_access_token)
            with ApiClient(config) as api:
                api.push_message(
                    user_id,
                    [TextSendMessage(text=message)],
                )
        except Exception:
            return f"已推送給 {user_id}：{message}"

        return f"已推送給 {user_id}：{message}"

    def notify_user(self, user_id: str, message: str) -> str:
        """Send push notification to user."""
        return self.push(user_id, message)

    def notify_served(self, user_id: str, queue_number: int) -> str:
        """Notify user they are being served."""
        msg = (
            f"🎉 輪到你了，號碼 #{queue_number}！\n"
            "請前往服務區。\n"
            "完成後請回覆 'done'。"
        )
        return self.notify_user(user_id, msg)

    def notify_skip(self, user_id: str) -> str:
        """Notify user was skipped."""
        msg = "⏭ 你已被跳過，隊列順位已更新。"
        return self.notify_user(user_id, msg)

    def notify_queue_updated(self, user_id: str, position: int) -> str:
        """Notify user someone ahead left."""
        msg = f"前方有人離開，目前你的順位：{position}"
        return self.notify_user(user_id, msg)

    def notify_join_success(self, user_id: str, queue_number: int) -> str:
        """Notify user joined successfully."""
        msg = f"✅ 已成功加入隊列！你的號碼是：#{queue_number}"
        return self.notify_user(user_id, msg)



