"""Notification service for LINE push messaging."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


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
            logger.info("LINE access token 缺失，無法實際推送給 %s", user_id)
            return f"已推送給 {user_id}：{message}"

        try:
            from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, PushMessageRequest, TextMessage
        except Exception as exc:
            logger.warning("LINE SDK 無法使用，改用 fallback 回傳：%s", exc)
            return f"已推送給 {user_id}：{message}"

        try:
            config = Configuration(access_token=self.channel_access_token)
            with ApiClient(config) as api_client:
                MessagingApi(api_client).push_message(
                    PushMessageRequest(
                        to=user_id,
                        messages=[TextMessage(text=message)],
                    )
                )
        except Exception as exc:
            logger.exception("LINE 推播失敗 user_id=%s", user_id)
            return f"推播失敗給 {user_id}：{exc}"

        return f"已推送給 {user_id}：{message}"

    def link_rich_menu(self, user_id: str, rich_menu_id: str) -> str:
        """Link a specific rich menu to a user."""
        if not rich_menu_id:
            return "未設定 Rich Menu ID，略過同步。"
        if not self.channel_access_token:
            logger.info("LINE access token 缺失，無法綁定 Rich Menu 給 %s", user_id)
            return f"已為 {user_id} 指定 Rich Menu：{rich_menu_id}"

        try:
            from linebot.v3.messaging import ApiClient, Configuration, MessagingApi
        except Exception as exc:
            logger.warning("LINE SDK 無法使用，略過 Rich Menu 綁定：%s", exc)
            return f"已為 {user_id} 指定 Rich Menu：{rich_menu_id}"

        try:
            config = Configuration(access_token=self.channel_access_token)
            with ApiClient(config) as api_client:
                MessagingApi(api_client).link_rich_menu_id_to_user(user_id, rich_menu_id)
        except Exception as exc:
            logger.exception("LINE Rich Menu 綁定失敗 user_id=%s rich_menu_id=%s", user_id, rich_menu_id)
            return f"Rich Menu 綁定失敗：{exc}"

        return f"已為 {user_id} 指定 Rich Menu：{rich_menu_id}"

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



