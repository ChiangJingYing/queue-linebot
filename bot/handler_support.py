from __future__ import annotations

from core.time_utils import format_display_time


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
        position = self.queue_manager.get_user_position(user_id)
        if position is None:
            total_count = len(self.queue_manager.get_queue())
            msg = f"📊 目前有 {total_count} 人在排隊中"
        else:
            ahead_count = max(position - 1, 0)
            msg = f"📊 目前你前面還有 {ahead_count} 人"
        return self._reply(reply_token, msg)

    def _handle_user_history(self, user_id: str, reply_token: str) -> list:
        history = self.queue_manager.get_history(user_id)
        if not history:
            return self._reply(reply_token, "查無排隊歷史紀錄。")

        lines = ["排隊歷史紀錄"]
        for entry in history:
            lines.append(f"#{entry.queue_number} {entry.queue_type} - {entry.status} ({entry.time})")
        return self._reply(reply_token, "\n".join(lines))

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
        if not self._is_admin(user_id):
            return self._reply(reply_token, "❌ 未授權，僅限管理員使用。")

        msg = (
            "📋 隊列系統指令\n\n"
            "**一般使用者：**\n"
            "/register [名稱] - 註冊或更新顯示名稱\n"
            "/join - 以自己身分加入一般隊列\n"
            "/join vip - 以自己身分加入 VIP 隊列\n"
            "/cancel - 取消排隊\n"
            "/status - 查看隊列狀態\n"
            "/history - 查看你的排隊歷史\n"
            "/coffee - 取得 VIP 連結\n"
            "**管理員指令（/admin/ 開頭）：**\n"
            "/admin/serve - 叫下一位\n"
            "/admin/serve [id] - 叫指定使用者\n"
            "/admin/ping - 手動提醒下一位\n"
            "/admin/ping [id] - 手動提醒指定使用者\n"
            "/admin/status - 完整狀態\n"
            "/admin/stats - 統計面板\n"
            "/admin/clear - 清空全部隊列\n"
            "/admin/vip toggle [on/off] - 開關 VIP 隊列\n"
            "/admin/vip clear - 清空 VIP 隊列\n"
            "/admin/join [on/off] - 切換總隊列狀態\n"
            "/admin/join status - 查看總隊列狀態\n"
            "/admin/history [id] - 查詢使用者歷史\n"
            "/admin/export - 匯出 CSV 預覽\n"
            "/admin/config max [N] - 設定最大容量"
            "/help - 顯示說明\n\n"
        )
        return self._reply(reply_token, msg)
