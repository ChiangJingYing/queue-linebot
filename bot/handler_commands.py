from __future__ import annotations

from datetime import datetime, timedelta

from services.cancel_flow import begin_closed_queue_cancel_flow, advance_closed_queue_cancel_flow
from services.interaction_presenters import build_line_cancel_confirmation_quick_options
from services.user_flow import cancel_user, join_user


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

        outcome = join_user(queue_manager=self.queue_manager, user_id=target_id, queue_type=queue_type)
        if outcome["status"] == "needs_registration":
            return self._reply(
                reply_token,
                outcome["message"],
                quick_options=[{"label": "設定基本資料", "text": "/register"}],
            )

        if outcome["status"] == "success":
            self._maybe_push_new_order_announcement(queue_size_after_join=outcome.get("total_in_queue", 0))
            self._new_order_last_joined_at = datetime.now()
            msg = (
                f"✅ 加入隊列成功！\n"
                f"   你的號碼：#{outcome['queue_number']}\n"
                f"   目前順位：{outcome['position']}\n"
                f"   隊列總人數：{outcome['total_in_queue']}"
            )
        else:
            msg = outcome["message"]

        return self._reply(reply_token, msg)

    def _handle_cancel(self, user_id: str, reply_token: str) -> list:
        if not self.queue_manager.get_queue_enabled() and self.queue_manager.get_user_position(user_id) is not None:
            outcome = begin_closed_queue_cancel_flow()
            self._set_pending_state(user_id, "cancel", outcome["state"])
            return self._reply(
                reply_token,
                outcome["message"],
                quick_options=self._cancel_confirmation_quick_options(),
            )

        return self._perform_cancel(user_id, reply_token)

    def _handle_cancel_confirmation(self, user_id: str, text: str, reply_token: str) -> list:
        state = self._get_pending_state(user_id, "cancel")
        outcome = advance_closed_queue_cancel_flow(
            state=state,
            action=text,
            still_in_queue=self.queue_manager.get_user_position(user_id) is not None,
            expired_message="請點選 quick reply 進行操作。",
        )

        if outcome["status"] == "aborted":
            self._clear_pending_state(user_id, "cancel")
            return self._reply(reply_token, outcome["message"])

        if outcome["status"] == "not_in_queue":
            self._clear_pending_state(user_id, "cancel")
            return self._reply(reply_token, outcome["message"])

        if outcome["status"] == "pending":
            self._set_pending_state(user_id, "cancel", outcome["state"])
            return self._reply(
                reply_token,
                outcome["message"],
                quick_options=self._cancel_confirmation_quick_options(),
            )

        self._clear_pending_state(user_id, "cancel")
        return self._perform_cancel(user_id, reply_token)

    def _perform_cancel(self, user_id: str, reply_token: str) -> list:
        outcome = cancel_user(queue_manager=self.queue_manager, user_id=user_id)

        if outcome["status"] == "cancelled":
            msg = (
                f"✅ 已取消排隊！\n"
                f"   原始順位：#{outcome['removed_position']}\n"
                f"   目前隊列總人數：{outcome['new_total']}"
            )
        else:
            msg = outcome["message"]

        return self._reply(reply_token, msg)

    def _cancel_confirmation_quick_options(self) -> list[dict]:
        return build_line_cancel_confirmation_quick_options()

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
