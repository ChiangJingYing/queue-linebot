from __future__ import annotations

from datetime import datetime, timedelta


class HandlerCommandsMixin:
    def _handle_join(self, user_id: str, args: list, reply_token: str) -> list:
        if not args:
            target_id = user_id
            queue_type = "regular"
        elif len(args) == 1 and args[0] in {"regular", "vip"}:
            target_id = user_id
            queue_type = args[0]
        else:
            return self._reply(reply_token, "❌ 錯誤：不支援替其他使用者加入隊列，請使用 /join 或 /join vip。")

        profile = self.queue_manager.db.get_user_profile(target_id)
        if profile is None or not profile.display_name or not profile.location:
            return self._reply(
                reply_token,
                "❌ 錯誤：請先完成註冊（學號與座位）後再加入隊列。",
                quick_options=[{"label": "設定基本資料", "text": "/register"}],
            )

        result = self.queue_manager.join(target_id, queue_type)

        if result["status"] == "success":
            self._maybe_push_new_order_announcement(queue_size_after_join=result.get("total_in_queue", 0))
            self._new_order_last_joined_at = datetime.now()
            msg = (
                f"✅ 加入隊列成功！\n"
                f"   你的號碼：#{result['queue_number']}\n"
                f"   目前順位：{result['position']}\n"
                f"   隊列總人數：{result['total_in_queue']}"
            )
        else:
            msg = f"❌ 錯誤：{result['message']}"

        return self._reply(reply_token, msg)

    def _handle_cancel(self, user_id: str, reply_token: str) -> list:
        if not self.queue_manager.get_queue_enabled() and self.queue_manager.get_user_position(user_id) is not None:
            self.pending_actions[user_id] = {"type": "cancel_when_closed", "step": 1}
            return self._reply(
                reply_token,
                "當前隊列已關閉，確定要放棄嗎？\n若放棄無法再加入到隊列中！",
                quick_options=self._cancel_confirmation_quick_options(),
            )

        return self._perform_cancel(user_id, reply_token)

    def _handle_cancel_confirmation(self, user_id: str, text: str, reply_token: str) -> list:
        state = self.pending_actions.get(user_id, {})
        normalized = text.strip()

        if normalized == "取消放棄":
            self.pending_actions.pop(user_id, None)
            return self._reply(reply_token, "好的，已取消放棄")

        if normalized != "確認放棄":
            return self._reply(
                reply_token,
                "請點選 quick reply 進行操作。",
                quick_options=self._cancel_confirmation_quick_options(),
            )

        if self.queue_manager.get_user_position(user_id) is None:
            self.pending_actions.pop(user_id, None)
            return self._reply(reply_token, "❌ 錯誤：你目前不在隊列中。")

        if state.get("step") == 1:
            self.pending_actions[user_id] = {"type": "cancel_when_closed", "step": 2}
            return self._reply(
                reply_token,
                "您確定要放棄嗎？",
                quick_options=self._cancel_confirmation_quick_options(),
            )

        self.pending_actions.pop(user_id, None)
        return self._perform_cancel(user_id, reply_token)

    def _perform_cancel(self, user_id: str, reply_token: str) -> list:
        result = self.queue_manager.cancel(user_id)

        if result["status"] == "cancelled":
            msg = (
                f"✅ 已取消排隊！\n"
                f"   原始順位：#{result['removed_position']}\n"
                f"   目前隊列總人數：{result['new_total']}"
            )
        else:
            msg = f"❌ 錯誤：{result['message']}"

        return self._reply(reply_token, msg)

    def _cancel_confirmation_quick_options(self) -> list[dict]:
        return [
            {"label": "確認放棄", "text": "確認放棄"},
            {"label": "我在努力看看", "text": "取消放棄"},
        ]

    def _push_dashboard_announcement(self, user_id: str) -> None:
        if not self.announcement_service:
            return
        profile = self.queue_manager.db.get_user_profile(user_id)
        display_name = profile.display_name if profile and profile.display_name else user_id
        try:
            self.announcement_service.announce_called_guest(display_name=display_name)
        except Exception:
            return

    def _maybe_push_new_order_announcement(self, *, queue_size_after_join: int) -> None:
        if not self.announcement_service or queue_size_after_join != 1:
            return
        now = datetime.now()
        idle_long_enough = now - self._new_order_last_joined_at >= timedelta(seconds=self.new_order_idle_seconds)
        should_announce = self._announce_new_order_on_next_join or idle_long_enough
        self._announce_new_order_on_next_join = False
        if not should_announce:
            return
        try:
            self.announcement_service.announce_new_order(text=self.new_order_announcement_text)
        except Exception:
            return
