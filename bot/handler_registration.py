"""LINE 註冊流程處理 mixin。

這個模組負責處理使用者透過 ``/register`` 進行的多步驟註冊流程，包含：
- 輸入學號 / 顯示名稱
- 選擇地點群組
- 選擇具體位置
- 寫回使用者基本資料

狀態推進由 ``services.register_flow`` 負責，資料落地則交給
``services.register_service``。
"""

from __future__ import annotations

from services.register_flow import advance_register_flow
from services.register_service import complete_registration


class HandlerRegistrationMixin:
    """封裝 LINE 註冊流程的互動步驟。"""

    def _handle_register(self, user_id: str, args: list, reply_token: str) -> list:
        """啟動註冊流程。

        ``/register`` 不接受額外參數；進入流程後第一步要求使用者輸入學號。
        """
        if args:
            return self._reply(reply_token, "❌ 錯誤：/register 不接受參數，請直接輸入 /register 後依提示完成註冊。")

        self._set_pending_state(user_id, "register", {"type": "register_name"})
        return self._reply(reply_token, "請輸入你的學號。")

    def _capture_register_name(self, user_id: str, display_name: str, reply_token: str) -> list:
        """接收註冊流程第一步輸入，並推進到地點群組選擇。"""
        outcome = advance_register_flow(
            state={"type": "register_name"},
            text=display_name,
            location_options=self.location_options,
        )
        if outcome["status"] == "error":
            return self._reply(reply_token, outcome["message"])

        self._set_pending_state(user_id, "register", outcome["state"])
        return self._reply(
            reply_token,
            outcome["message"],
            quick_options=outcome["options"],
        )

    def _capture_register_location_group(self, user_id: str, group: str, reply_token: str) -> list:
        """接收地點群組選擇，並推進到具體位置選擇。"""
        state = self._get_pending_state(user_id, "register")
        outcome = advance_register_flow(
            state=state,
            text=group,
            location_options=self.location_options,
        )
        if outcome["status"] == "error":
            return self._reply(
                reply_token,
                outcome["message"],
                quick_options=outcome["options"],
            )

        self._set_pending_state(user_id, "register", outcome["state"])
        return self._reply(
            reply_token,
            outcome["message"],
            quick_options=outcome["options"],
        )

    def _capture_register_location_item(self, user_id: str, item: str, reply_token: str) -> list:
        """接收具體位置選擇，並在完成後寫入使用者資料。"""
        state = self._get_pending_state(user_id, "register")
        outcome = advance_register_flow(
            state=state,
            text=item,
            location_options=self.location_options,
        )
        if outcome["status"] == "error":
            return self._reply(
                reply_token,
                outcome["message"],
                quick_options=outcome["options"],
            )

        self._clear_pending_state(user_id, "register")
        return self._complete_register(user_id, outcome["display_name"], outcome["location"], reply_token)

    def _complete_register(self, user_id: str, display_name: str, location: str, reply_token: str) -> list:
        """完成註冊並回覆最終結果訊息。"""
        outcome = complete_registration(
            queue_manager=self.queue_manager,
            user_id=user_id,
            display_name=display_name,
            location=location,
        )
        return self._reply(reply_token, outcome["message"])
