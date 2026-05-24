"""LINE 使用者命令處理 mixin。

這個模組負責 LINE 一般使用者在文字指令層的共用流程，包含：
- 加入隊列
- 取消排隊與封隊時的二次確認
- 新訂單語音廣播
- 叫號後的儀表板公告

它本身不直接管理 webhook 事件，而是由 ``LineBotHandler`` 在完成
文字解析後委派進來。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from services.cancel_flow import begin_closed_queue_cancel_flow, advance_closed_queue_cancel_flow
from services.interaction_presenters import build_line_cancel_confirmation_quick_options
from services.user_flow import cancel_user, join_user


class HandlerCommandsMixin:
    """封裝 LINE 一般使用者命令的處理流程。"""

    #: 用於管理通知廣播中的平台名稱標記。
    LINE_NOTIFICATION_PLATFORM = "Line"

    def _handle_join(self, user_id: str, args: list, reply_token: str) -> list:
        """處理使用者加入隊列指令。

        支援：
        - ``/join`` → 加入一般隊列
        - ``/join regular`` → 明確加入一般隊列
        - ``/join vip`` → 加入 VIP 隊列

        不支援替其他使用者代排；若參數格式不合法，直接回覆錯誤訊息。
        """
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
            if getattr(self, "notification_service", None) is not None:
                self.notification_service.broadcast_event(
                    category="join",
                    title="排隊通知",
                    actor_label=f"使用者：{self.queue_manager.db.get_display_name(target_id)}",
                    target_label=f"隊列：{queue_type}",
                    detail_lines=[
                        f"號碼：#{outcome['queue_number']}",
                        f"目前總人數：{outcome['total_in_queue']}",
                    ],
                    platform=self.LINE_NOTIFICATION_PLATFORM,
                )
            msg = (
                f"✅ 加入隊列成功！\n"
                f"   你的號碼：#{outcome['queue_number']}\n"
                f"   目前順位：{outcome['position']}\n"
                f"   隊列總人數：{outcome['total_in_queue']}"
            )
        else:
            raw = outcome.get("raw_result", {})
            if raw.get("message") == "目前隊列已關閉，請稍後再試。":
                self._broadcast_join_error_event(
                    user_id=target_id,
                    command_text="/join" if queue_type == "regular" else f"/join {queue_type}",
                    error_message=raw["message"],
                )
            msg = outcome["message"]

        return self._reply(reply_token, msg)

    def _broadcast_join_error_event(self, *, user_id: str, command_text: str, error_message: str) -> None:
        """Broadcast join failures that should be visible to Telegram admins."""
        if getattr(self, "notification_service", None) is None:
            return
        self.notification_service.broadcast_event(
            category="error",
            title="失敗通知",
            actor_label=f"使用者：{self.queue_manager.db.get_display_name(user_id)}",
            target_label=f"指令：{command_text}",
            detail_lines=[f"原因：{error_message}"],
            platform=self.LINE_NOTIFICATION_PLATFORM,
        )

    def _handle_cancel(self, user_id: str, reply_token: str) -> list:
        """處理取消排隊指令。

        當系統已封隊但使用者仍在隊列中時，不直接取消，而是先進入
        二次確認流程，避免誤觸 quick reply 造成資料異動。
        """
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
        """推進封隊取消流程中的二次確認狀態機。"""
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
        """實際執行取消排隊，並在成功時發送管理通知。"""
        outcome = cancel_user(queue_manager=self.queue_manager, user_id=user_id)

        if outcome["status"] == "cancelled":
            if self.notification_service is not None:
                self.notification_service.broadcast_event(
                    category="cancel",
                    title="取消通知",
                    actor_label=f"使用者：{self.queue_manager.db.get_display_name(user_id)}",
                    target_label="動作：離開隊列",
                    platform=self.LINE_NOTIFICATION_PLATFORM,
                )
            msg = (
                f"✅ 已取消排隊！\n"
                f"   原始順位：#{outcome['removed_position']}\n"
                f"   目前隊列總人數：{outcome['new_total']}"
            )
        else:
            msg = outcome["message"]

        return self._reply(reply_token, msg)

    def _cancel_confirmation_quick_options(self) -> list[dict]:
        """建立 LINE 專用的取消確認 quick reply 選項。"""
        return build_line_cancel_confirmation_quick_options()

    def _push_dashboard_announcement(self, user_id: str) -> None:
        """將被叫號使用者名稱送到 dashboard/語音公告服務。

        這個 helper 只更新現場公告，不會直接對使用者送 push 通知；
        私訊通知應由 ``Notifier.notify_served()`` 等路徑負責。
        """
        if not self.announcement_service:
            return
        profile = self.queue_manager.db.get_user_profile(user_id)
        display_name = profile.display_name if profile and profile.display_name else user_id
        try:
            self.announcement_service.announce_called_guest(display_name=display_name)
        except Exception:
            return

    def _maybe_push_new_order_announcement(self, *, queue_size_after_join: int) -> None:
        """在符合條件時語音播報「您有新訂單」。

        只有當加入後總人數為 1，且符合以下任一條件時才會播報：
        - 被標記為下一次加入要播報
        - 距離上次加入已超過閒置門檻
        """
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
