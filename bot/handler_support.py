from __future__ import annotations

from core.time_utils import format_display_time
from services.user_flow import build_help_message, build_history_message, get_user_status


class HandlerSupportMixin:
    def _reply(self, reply_token: str, message: str, quick_options: list | None = None) -> list:
        """Create reply action with optional quick reply buttons."""

        if quick_options:
            items = []
            for item in quick_options:
                if isinstance(item, dict):
                    action_dict = item.get("action", item)
                    items.append({"type": "action", "action": action_dict})
                else:
                    items.append({"type": "action", "action": {
                        "type": "message",
                        "label": str(item),
                        "text": str(item),
                    }})
            return [{"replyToken": reply_token, "text": message, "quickReply": {"items": items}}]

        return [{"replyToken": reply_token, "text": message}]

    def _sync_rich_menu(self, user_id: str) -> None:
        """Sync rich menu based on admin status.

        - Admins: if they don't have a valid menu, link page1.
        - Users: link user menu.
        """
        is_admin = self._is_admin(user_id)
        if is_admin:
            current = self.notifier.get_user_rich_menu(user_id)
            valid = current in (self.admin_rich_menu_id, self.admin_rich_menu_page2_id)
            if not valid and self.admin_rich_menu_id:
                self.notifier.link_rich_menu(user_id, self.admin_rich_menu_id)
        else:
            if self.user_rich_menu_id:
                self.notifier.link_rich_menu(user_id, self.user_rich_menu_id)

    def _handle_admin_page_switch(self, user_id: str, target_page: str, reply_token: str) -> list:
        """Handle admin rich menu page switch."""
        if not self._is_admin(user_id):
            return self._reply(reply_token, "❌ 未授權，僅限管理員使用。")

        target_id = (
            self.admin_rich_menu_page2_id if target_page == "page2"
            else self.admin_rich_menu_id
        )
        self.notifier.link_rich_menu(user_id, target_id)
        page_num = 2 if target_page == "page2" else 1
        return self._reply(reply_token, f"✅ 已切換至第 {page_num} 頁")

    def _handle_status(self, user_id: str, reply_token: str) -> list:
        outcome = get_user_status(queue_manager=self.queue_manager, user_id=user_id)
        if outcome["status"] == "not_in_queue":
            msg = f"📊 目前有 {outcome['total_count']} 人在排隊中"
        else:
            msg = f"📊 目前你前面還有 {outcome['ahead_count']} 人"
        return self._reply(reply_token, msg)

    def _handle_user_history(self, user_id: str, reply_token: str) -> list:
        history = self.queue_manager.get_history(user_id)
        msg = build_history_message(
            history,
            formatter=lambda entry: f"#{entry.queue_number} {entry.queue_type} - {entry.status} ({entry.time})",
        )
        return self._reply(reply_token, msg)

    def _handle_coffee(self, user_id: str, reply_token: str) -> list:
        msg = (
            "☕ 買杯咖啡即可取得 VIP 排隊資格！\n\n"
            f"[購買咖啡](https://buymeacoffee.com/yourname)\n\n"
            "完成購買後，輸入 /join vip 即可加入 VIP 隊列。"
        )
        return self._reply(reply_token, msg)

    def _handle_done(self, user_id: str, reply_token: str) -> list:
        served = self.queue_manager.db.serve_queue(user_id)
        if served is not None:
            self.queue_manager.db.log_event("done", user_id, served.queue_type, "使用者已確認完成")
            return self._reply(reply_token, "✅ 已收到，已標記完成。")
        return self._reply(reply_token, "❌ 找不到你的排隊記錄，請確認是否有正確的叫號。")

    def _handle_help(self, user_id: str, reply_token: str) -> list:
        outcome = build_help_message(
            is_admin=self._is_admin(user_id),
            admin_only=True,
            include_admin_commands=True,
            include_vip_join=True,
            include_coffee=True,
        )
        return self._reply(reply_token, outcome["message"])
