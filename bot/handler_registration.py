from __future__ import annotations


class HandlerRegistrationMixin:
    def _handle_register(self, user_id: str, args: list, reply_token: str) -> list:
        if args:
            return self._reply(reply_token, "❌ 錯誤：/register 不接受參數，請直接輸入 /register 後依提示完成註冊。")

        self.pending_actions[user_id] = {"type": "register_name"}
        return self._reply(reply_token, "請輸入你的學號。")

    def _capture_register_name(self, user_id: str, display_name: str, reply_token: str) -> list:
        normalized_name = display_name.strip()
        if not normalized_name:
            return self._reply(reply_token, "學號不可為空白，請重新輸入學號。")

        self.pending_actions[user_id] = {
            "type": "register_location_group",
            "display_name": normalized_name,
        }
        groups = list(self.location_options.keys())
        return self._reply(
            reply_token,
            f"請選擇您在第幾排座位：{'、'.join(groups)}",
            quick_options=groups,
        )

    def _capture_register_location_group(self, user_id: str, group: str, reply_token: str) -> list:
        state = self.pending_actions.get(user_id, {})
        normalized_group = group.strip().upper()
        if normalized_group not in self.location_options:
            groups = list(self.location_options.keys())
            return self._reply(
                reply_token,
                f"無效的位置，請從以下選擇：{'、'.join(groups)}",
                quick_options=groups,
            )

        self.pending_actions[user_id] = {
            "type": "register_location_item",
            "display_name": state.get("display_name", ""),
            "group": normalized_group,
        }
        options = self.location_options[normalized_group]
        return self._reply(
            reply_token,
            f"請選擇您的座位（{normalized_group}-?）：{'、'.join(options)}",
            quick_options=options,
        )

    def _capture_register_location_item(self, user_id: str, item: str, reply_token: str) -> list:
        state = self.pending_actions.get(user_id, {})
        group = state.get("group", "")
        display_name = state.get("display_name", "")
        normalized_item = item.strip().upper()
        options = self.location_options.get(group, [])
        if normalized_item not in options:
            return self._reply(
                reply_token,
                f"無效的位置，請從以下選擇：{'、'.join(options)}",
                quick_options=options,
            )

        self.pending_actions.pop(user_id, None)
        location = f"{group}-{normalized_item}"
        return self._complete_register(user_id, display_name, location, reply_token)

    def _complete_register(self, user_id: str, display_name: str, location: str, reply_token: str) -> list:
        result = self.queue_manager.register_name(user_id, display_name, location=location)
        if result["status"] != "success":
            return self._reply(reply_token, f"❌ 錯誤：{result['message']}")

        return self._reply(reply_token, f"✅ 已更新學號：{result['display_name']}\n位置：{result['location']}")
