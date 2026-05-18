"""LINE/Discord/Telegram 共用通知出口。

雖然歷史上以 LINE push 為主，但這個 notifier 現在也負責在測試或多平台流程裡，
把通知導到 Discord / Telegram sender，讓 queue manager 不需要知道平台細節。
"""

from __future__ import annotations

import logging
import json
from typing import Callable
from urllib import error as urllib_error
from urllib import request as urllib_request

logger = logging.getLogger(__name__)


class Notifier:
    """將 queue 事件送到對應平台的通知通道。

    ``QueueManager`` 只依賴這個物件提供的少數方法（例如 ``notify_served``、
    ``notify_skip``、``notify_user``），不需要知道底層到底是 LINE push、
    Telegram sender、Discord sender，還是測試用 spy/stub。

    ``line_push_on_served`` 只控制 LINE 使用者在「被叫號」時是否額外收到 push；
    不影響一般 webhook reply、admin ping、或 rich menu 綁定。
    """

    def __init__(
        self,
        channel_secret: str = "",
        channel_access_token: str = "",
        admin_rich_menu_page2_id: str = "",
        discord_sender: Callable[[str, str], None] | None = None,
        telegram_sender: Callable[[str, str], None] | None = None,
        db: object | None = None,
        line_push_on_served: bool = True,
    ) -> None:
        """保存可用的 sender、LINE rich menu 設定與 served push 開關。"""
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token
        self.admin_rich_menu_page2_id = admin_rich_menu_page2_id
        self.discord_sender = discord_sender
        self.telegram_sender = telegram_sender
        self.db = db
        self.line_push_on_served = bool(line_push_on_served)

    def push(self, user_id: str, message: str) -> str:
        """直接透過 LINE Push API 傳送訊息。

        若 access token 或 LINE SDK 不可用，會退回可測試的 fallback 字串，
        讓上層流程不必因本機環境缺 SDK 而中斷。
        """
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

    def push_flex(self, user_id: str, message: dict) -> str:
        """Send one Flex message via LINE Push API."""
        alt_text = str((message or {}).get("altText") or "通知").strip() or "通知"
        if not self.channel_access_token:
            logger.info("LINE access token 缺失，無法實際推送 Flex 給 %s", user_id)
            return f"已推送 Flex 給 {user_id}：{alt_text}"
        payload = {
            "to": user_id,
            "messages": [json.loads(json.dumps(message or {}))],
        }
        request = urllib_request.Request(
            "https://api.line.me/v2/bot/message/push",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.channel_access_token}",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=10) as response:
                response.read()
        except urllib_error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            logger.exception("LINE Flex 推播失敗 user_id=%s response=%s", user_id, body)
            return f"推播 Flex 失敗給 {user_id}：LINE API 暫時不可用"
        except Exception as exc:
            logger.exception("LINE Flex 推播失敗 user_id=%s", user_id)
            return f"推播 Flex 失敗給 {user_id}：通知服務暫時不可用"

        return f"已推送 Flex 給 {user_id}：{alt_text}"

    def link_rich_menu(self, user_id: str, rich_menu_id: str) -> str:
        """把指定 rich menu 綁到 LINE 使用者。"""
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
        """檢查 config flag 是否被視為啟用。"""
        if self.db is None:
            return False
        try:
            return (self.db.get_config(key) or "").strip().lower() in {"1", "true", "yes", "discord", "telegram"}
        except Exception:
            return False

    def _is_discord_user(self, user_id: str) -> bool:
        """判斷使用者是否偏好走 Discord sender。"""
        return self._has_config_flag(f"discord_user:{user_id}")

    def _is_telegram_user(self, user_id: str) -> bool:
        """判斷使用者是否偏好走 Telegram sender。"""
        return self._has_config_flag(f"telegram_user:{user_id}")

    def _notify_line_user(self, user_id: str, message: str) -> str:
        """對 LINE 使用者送出主動 push。"""
        return self.push(user_id, message)

    def notify_user(self, user_id: str, message: str) -> str:
        """依使用者平台旗標選擇 Discord / Telegram / LINE 送出。

        平台判斷依賴資料庫中的 config flag，例如：
        - ``discord_user:<user_id>``
        - ``telegram_user:<user_id>``

        都沒有命中時，會退回 LINE push / fallback 行為。
        這條一般通知路徑不受 ``line_push_on_served`` 影響，
        因為 admin ping 等功能仍需要對 LINE 使用者主動送訊息。
        """
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
        return self._notify_line_user(user_id, message)

    def notify_served(self, user_id: str, queue_number: int) -> str:
        """送出「輪到你了」叫號通知。

        這是 ``QueueManager.serve_next()`` / ``serve_specific()`` 成功後最常用的通知入口。
        若目標是 LINE 使用者且 ``line_push_on_served`` 關閉，則只略過這條主動 push；
        Telegram / Discord 仍照常送出，admin ping 也不受影響。
        """
        msg = (
            f"🎉 輪到你了，號碼 #{queue_number}！\n"
            "請做好準備，若沒有助教前往，請舉手或找助教反應。"
        )
        if not self._is_discord_user(user_id) and not self._is_telegram_user(user_id) and not self.line_push_on_served:
            logger.info("LINE served push 已停用，略過 user_id=%s", user_id)
            return f"已略過 LINE 被叫號推播給 {user_id}：{msg}"
        return self.notify_user(user_id, msg)

    def notify_skip(self, user_id: str) -> str:
        """送出被跳過通知。"""
        msg = "⏭ 你已被跳過，隊列順位已更新。"
        return self.notify_user(user_id, msg)

    def notify_queue_updated(self, user_id: str, position: int) -> str:
        """送出前方順位變動通知。"""
        msg = f"前方有人離開，目前你的順位：{position}"
        return self.notify_user(user_id, msg)

    def notify_join_success(self, user_id: str, queue_number: int) -> str:
        """送出加入隊列成功通知。"""
        msg = f"✅ 已成功加入隊列！你的號碼是：#{queue_number}"
        return self.notify_user(user_id, msg)

    def get_user_rich_menu(self, user_id: str) -> str:
        """取得 LINE 使用者目前綁定的 rich menu ID。"""
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
        """在 LINE admin 的兩頁 rich menu 之間切換。"""
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
