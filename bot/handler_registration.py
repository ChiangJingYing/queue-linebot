from __future__ import annotations

from services.register_flow import advance_register_flow
from services.register_service import complete_registration


class HandlerRegistrationMixin:
    def _handle_register(self, user_id: str, args: list, reply_token: str) -> list:
        if args:
            return self._reply(reply_token, "❌ 錯誤：/register 不接受參數，請直接輸入 /register 後依提示完成註冊。")

        self._set_pending_state(user_id, "register", {"type": "register_name"})
        return self._reply(reply_token, "請輸入你的學號。")

    def _capture_register_name(self, user_id: str, display_name: str, reply_token: str) -> list:
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
        outcome = complete_registration(
            queue_manager=self.queue_manager,
            user_id=user_id,
            display_name=display_name,
            location=location,
        )
        return self._reply(reply_token, outcome["message"])
