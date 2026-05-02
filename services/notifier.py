"""Notification service for LINE push messaging."""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)


class Notifier:
    """Sends notifications via LINE Push API and platform-specific senders."""

    def __init__(
        self,
        channel_secret: str = "",
        channel_access_token: str = "",
        admin_rich_menu_page2_id: str = "",
        discord_sender: Callable[[str, str], None] | None = None,
        telegram_sender: Callable[[str, str], None] | None = None,
        db: object | None = None,
    ) -> None:
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token
        self.admin_rich_menu_page2_id = admin_rich_menu_page2_id
        self.discord_sender = discord_sender
        self.telegram_sender = telegram_sender
        self.db = db

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

    def _has_config_flag(self, key: str) -> bool:
        if self.db is None:
            return False
        try:
            return (self.db.get_config(key) or "").strip().lower() in {"1", "true", "yes", "discord", "telegram"}
        except Exception:
            return False

    def _is_discord_user(self, user_id: str) -> bool:
        return self._has_config_flag(f"discord_user:{user_id}")

    def _is_telegram_user(self, user_id: str) -> bool:
        return self._has_config_flag(f"telegram_user:{user_id}")

    def notify_user(self, user_id: str, message: str) -> str:
        """Send push notification to user."""
        if self.discord_sender is not None and self._is_discord_user(user_id):
            try:
                self.discord_sender(user_id, message)
                return f"已推送給 {user_id}：{message}"
            except Exception as exc:
                logger.exception("Discord 推播失敗 user_id=%s", user_id)
                return f"推播失敗給 {user_id}：{exc}"
        if self.telegram_sender is not None and self._is_telegram_user(user_id):
            try:
                self.telegram_sender(user_id, message)
                return f"已推送給 {user_id}：{message}"
            except Exception as exc:
                logger.exception("Telegram 推播失敗 user_id=%s", user_id)
                return f"推播失敗給 {user_id}：{exc}"
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

    def get_user_rich_menu(self, user_id: str) -> str:
        """取得 user 目前綁定的 rich menu ID。"""
        if not self.channel_access_token:
            return ""
        try:
            from linebot.v3.messaging import ApiClient, Configuration, MessagingApi
        except Exception as exc:
            logger.warning("LINE SDK 無法使用，無法取得 rich menu ID：%s", exc)
            return ""
        try:
            config = Configuration(access_token=self.channel_access_token)
            with ApiClient(config) as api_client:
                return MessagingApi(api_client).get_rich_menu_id_of_user(user_id)
        except Exception as exc:
            logger.exception("取得 rich menu ID 失敗 user_id=%s", user_id)
            return ""

    def switch_admin_page(self, user_id: str) -> str:
        """切換 admin rich menu page (1 ↔ 2)。"""
        if not self.admin_rich_menu_page2_id:
            logger.warning("admin_rich_menu_page2_id 未設定，跳過切換")
            return "rich menu page2 尚未設定"

        current_menu = self.get_user_rich_menu(user_id)
        target_menu = (
            self.admin_rich_menu_page2_id
            if current_menu == self.admin_rich_menu_page2_id
            else self.admin_rich_menu_id
        )
        return self.link_rich_menu(user_id, target_menu)



