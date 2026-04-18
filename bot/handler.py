"""LINE Bot Webhook Handler."""

from __future__ import annotations

from typing import Optional

from core.queue_manager import QueueManager
from services.vip_service import VipService
from services.notifier import Notifier
from core.validators import validate_command


class LineBotHandler:
    """Handles LINE Bot webhook events."""

    def __init__(
        self,
        channel_secret: str = "",
        channel_access_token: str = "",
        queue_manager: Optional[QueueManager] = None,
        vip_service: Optional[VipService] = None,
        admin_ids: list[str] | None = None,
        admin_rich_menu_id: str = "",
        user_rich_menu_id: str = "",
    ) -> None:
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token
        self.queue_manager = queue_manager or QueueManager()
        self.vip_service = vip_service or VipService(self.queue_manager.db)
        self.notifier = Notifier(
            channel_secret=self.channel_secret,
            channel_access_token=self.channel_access_token,
        )
        self.admin_ids = admin_ids or []
        self.admin_rich_menu_id = admin_rich_menu_id
        self.user_rich_menu_id = user_rich_menu_id

    def handle_event(self, event) -> list:
        """Handle a LINE event. Returns list of reply actions."""
        user_id = getattr(getattr(event, "source", None), "userId", "")
        if user_id:
            self._sync_rich_menu(user_id)
        if hasattr(event, "message") and getattr(event.message, "type", None) == "text":
            return self._handle_message(event)
        return []

    def _handle_message(self, event) -> list:
        """Process text message."""
        text = event.message.text
        user_id = event.source.userId
        reply_token = getattr(event, "reply_token", getattr(event, "replyToken", ""))

        command, args = validate_command(text)
        admin_history_mode = False
        if command == "/history" and args and self._is_admin(user_id):
            command = "/admin/history"
            admin_history_mode = True

        if command == "/join":
            return self._handle_join(user_id, args, reply_token)
        elif command == "/cancel":
            return self._handle_cancel(user_id, reply_token)
        elif command == "/status":
            return self._handle_status(reply_token)
        elif command == "/history" and not admin_history_mode:
            return self._handle_user_history(user_id, reply_token)
        elif command == "/remind":
            return self._handle_remind(user_id, args, reply_token)
        elif command == "/help":
            return self._handle_help(reply_token)
        elif command == "/register":
            return self._handle_register(user_id, args, reply_token)
        elif command == "/coffee":
            return self._handle_coffee(user_id, reply_token)
        elif command == "done":
            return self._handle_done(user_id, reply_token)
        elif command.startswith("/admin/"):
            return self._handle_admin(user_id, command, args, reply_token)

        return self._reply(reply_token, "未知指令，請輸入 /help 查看可用功能。")

    def _handle_join(self, user_id: str, args: list, reply_token: str) -> list:
        """Handle /join command."""
        if not args:
            target_id = user_id
            queue_type = "regular"
        elif len(args) == 1 and args[0] in {"regular", "vip"}:
            target_id = user_id
            queue_type = args[0]
        else:
            target_id = args[0]
            queue_type = args[1] if len(args) > 1 else "regular"

        result = self.queue_manager.join(target_id, queue_type)

        if result["status"] == "success":
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
        """Handle /cancel command."""
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

    def _handle_status(self, reply_token: str) -> list:
        """Handle /status command."""
        status = self.queue_manager.get_status()
        msg = (
            f"📊 隊列狀態\n\n"
            f"一般隊列：{status['regular_count']} 人\n"
            f"VIP 隊列：{status['vip_count']} 人\n"
            f"VIP 啟用：{'是' if status['vip_enabled'] else '否'}"
        )
        return self._reply(reply_token, msg)

    def _handle_user_history(self, user_id: str, reply_token: str) -> list:
        """Handle /history command for the current user."""
        history = self.queue_manager.get_history(user_id)
        if not history:
            return self._reply(reply_token, "查無排隊歷史紀錄。")

        lines = ["排隊歷史紀錄"]
        for entry in history:
            lines.append(
                f"#{entry.queue_number} {entry.queue_type} - {entry.status} ({entry.time})"
            )
        return self._reply(reply_token, "\n".join(lines))

    def _handle_remind(self, user_id: str, args: list, reply_token: str) -> list:
        """Handle /remind command."""
        if len(args) < 1:
            return self._reply(reply_token, "用法：/remind N\n範例：/remind 3")

        try:
            n = int(args[0])
            if n <= 0:
                raise ValueError
            self.notifier.notify_queue_updated(user_id, n)
            return self._reply(reply_token, f"✅ 已設定順位提醒：到第 {n} 位時通知你")
        except ValueError:
            return self._reply(reply_token, "數字格式錯誤，請使用 /remind N")

    def _handle_coffee(self, user_id: str, reply_token: str) -> list:
        """Handle /coffee command."""
        msg = (
            "☕ 買杯咖啡即可取得 VIP 排隊資格！\n\n"
            f"[購買咖啡](https://buymeacoffee.com/yourname)\n\n"
            "完成購買後，輸入 /join vip 即可加入 VIP 隊列。"
        )
        return self._reply(reply_token, msg)

    def _handle_done(self, user_id: str, reply_token: str) -> list:
        """Handle done acknowledgement after being served."""
        served = self.queue_manager.db.serve_queue(user_id)
        if served is not None:
            self.queue_manager.db.log_event("done", user_id, served.queue_type, "使用者已確認完成")
            return self._reply(reply_token, "✅ 已收到，已標記完成。")
        else:
            return self._reply(
                reply_token,
                "❌ 找不到你的排隊記錄，請確認是否有正確的叫號。",
            )

    def _handle_help(self, reply_token: str) -> list:
        """Handle /help command."""
        msg = (
            "📋 隊列系統指令\n\n"
            "**一般使用者：**\n"
            "/register [名稱] - 註冊或更新顯示名稱\n"
            "/join - 以自己身分加入一般隊列\n"
            "/join vip - 以自己身分加入 VIP 隊列\n"
            "/join [id] [queue_type] - 指定使用者加入隊列\n"
            "/cancel - 取消排隊\n"
            "/status - 查看隊列狀態\n"
            "/history - 查看你的排隊歷史\n"
            "/remind N - 在順位到 N 時提醒\n"
            "/coffee - 取得 VIP 連結\n"
            "/help - 顯示說明\n\n"
            "**管理員指令（/admin/ 開頭）：**\n"
            "/admin/serve - 叫下一位\n"
            "/admin/serve [id] - 叫指定使用者\n"
            "/admin/skip - 跳過下一位\n"
            "/admin/skip [id] - 跳過指定使用者\n"
            "/admin/status - 完整狀態\n"
            "/admin/stats - 統計面板\n"
            "/admin/clear - 清空全部隊列\n"
            "/admin/verify [id] [on/off] - 設定身分驗證\n"
            "/admin/vip toggle [on/off] - 開關 VIP 隊列\n"
            "/admin/vip clear - 清空 VIP 隊列\n"
            "/admin/history [id] - 查詢使用者歷史\n"
            "/admin/export - 匯出 CSV 預覽\n"
            "/admin/config max [N] - 設定最大容量"
        )
        return self._reply(reply_token, msg)

    def _handle_register(self, user_id: str, args: list, reply_token: str) -> list:
        """Handle /register [display_name]."""
        if not args:
            return self._reply(reply_token, "用法：/register [名稱]")

        result = self.queue_manager.register_name(user_id, " ".join(args))
        if result["status"] != "success":
            return self._reply(reply_token, f"❌ 錯誤：{result['message']}")

        return self._reply(
            reply_token,
            f"✅ 已更新名稱：{result['display_name']}\n身分驗證：{'已通過' if result['verified'] else '待驗證'}",
        )


    def _handle_admin(self, user_id: str, command: str, args: list,
                      reply_token: str) -> list:
        """Handle admin commands."""
        if not self._is_admin(user_id):
            return self._reply(reply_token, "❌ 未授權，僅限管理員使用。")

        if command == "/admin/serve" and len(args) > 0:
            return self._admin_serve(user_id, args[0], reply_token)
        elif command == "/admin/serve":
            return self._admin_serve_next(reply_token)
        elif command == "/admin/skip" and len(args) > 0:
            return self._admin_skip(user_id, args[0], reply_token)
        elif command == "/admin/skip":
            return self._admin_skip_next(reply_token)
        elif command == "/admin/status":
            return self._admin_status(reply_token)
        elif command == "/admin/stats":
            return self._handle_stats(reply_token)
        elif command == "/admin/history":
            return self._handle_admin_history(args, reply_token)
        elif command == "/admin/export":
            return self._handle_export(reply_token)
        elif command == "/admin/clear":
            return self._handle_admin_clear(reply_token)
        elif command == "/admin/verify":
            return self._handle_admin_verify(args, reply_token)
        elif command == "/admin/vip":
            if len(args) >= 1 and args[0] == "status":
                return self._handle_vip_status(reply_token)
            if len(args) >= 2 and args[0] == "toggle":
                return self._handle_vip_toggle(args[1], reply_token)
            if len(args) >= 1 and args[0] == "clear":
                return self._handle_vip_clear(reply_token)
        elif command == "/admin/config":
            return self._admin_config(args, reply_token)

        return self._reply(reply_token, "未知管理員指令。")

    def _is_admin(self, user_id: str) -> bool:
        """Check if user is admin."""
        return user_id in self.admin_ids

    def _admin_serve_next(self, reply_token: str) -> list:
        """Serve next in queue."""
        result = self.queue_manager.serve_next()
        if result["status"] == "served":
            msg = f"✅ 已叫號：#{result['id']}（號碼 {result['queue_number']}）"
        else:
            msg = f"❌ 錯誤：{result['message']}"
        return self._reply(reply_token, msg)

    def _admin_serve(self, user_id: str, target_id: str, reply_token: str) -> list:
        """Serve specific user."""
        result = self.queue_manager.serve_specific(target_id)
        if result["status"] == "served":
            msg = f"✅ 已叫號：#{result['id']}（號碼 {result['queue_number']}）"
        else:
            msg = f"❌ 錯誤：{result['message']}"
        return self._reply(reply_token, msg)

    def _admin_skip_next(self, reply_token: str) -> list:
        """Skip next in queue."""
        result = self.queue_manager.skip_next()
        if result["status"] == "skipped":
            msg = f"⏭ 已跳過：#{result['id']}（號碼 {result['queue_number']}）"
        else:
            msg = f"❌ 錯誤：{result['message']}"
        return self._reply(reply_token, msg)

    def _admin_skip(self, user_id: str, target_id: str, reply_token: str) -> list:
        """Skip specific user."""
        result = self.queue_manager.skip_specific(target_id)
        if result["status"] == "skipped":
            msg = f"⏭ 已跳過：#{result['id']}（號碼 {result['queue_number']}）"
        else:
            msg = f"❌ 錯誤：{result['message']}"
        return self._reply(reply_token, msg)

    def _admin_status(self, reply_token: str) -> list:
        """Admin full status view with queue details."""
        status = self.queue_manager.get_status()
        entries = self.queue_manager.get_queue()

        regular_lines = []
        vip_lines = []

        regular_idx = 0
        vip_idx = 0
        for entry in entries:
            joined = str(entry.join_time).split("T")[1][:5] if entry.join_time and "T" in str(entry.join_time) else str(entry.join_time)
            name = self.queue_manager.db.get_display_name(entry.user_id)
            verified = self.queue_manager.db.get_user_profile(entry.user_id)
            badge = "✅" if verified and verified.verified else "🕓"
            label = f"{name}（{entry.user_id}） {badge}" if name != entry.user_id else f"{entry.user_id} {badge}"
            if entry.queue_type == "vip":
                vip_idx += 1
                vip_lines.append(f"#{vip_idx} {label} — {joined}")
            else:
                regular_idx += 1
                regular_lines.append(f"#{regular_idx} {label} — {joined}")

        regular_text = "\n".join(regular_lines) if regular_lines else "（空）"
        vip_text = "\n".join(vip_lines) if vip_lines else "（空）"

        msg = (
            "📋 完整隊列狀態\n\n"
            f"標準隊列 ({status['regular_count']}人):\n{regular_text}\n\n"
            f"VIP 隊列 ({status['vip_count']}人):\n{vip_text}\n\n"
            f"VIP 啟用: {'是' if status['vip_enabled'] else '否'}"
        )
        return self._reply(reply_token, msg)

    def _handle_stats(self, reply_token: str) -> list:
        """Handle /admin/stats."""
        stats = self.queue_manager.get_stats()
        msg = (
            "📈 統計面板\n\n"
            f"今日排隊人數: {stats['joined_today']}\n"
            f"被叫號人數: {stats['served_count']}\n"
            f"被跳過人數: {stats['skipped_count']}\n"
            f"平均等待時間: {stats['average_wait_minutes']:.1f} 分鐘\n\n"
            f"VIP 啟用: {'是' if stats['vip']['enabled'] else '否'}\n"
            f"VIP 目前排隊: {stats['vip']['active_count']}\n"
            f"VIP 今日排隊: {stats['vip']['joined_today']}\n"
            f"VIP 今日叫號: {stats['vip']['served_count']}"
        )
        return self._reply(reply_token, msg)

    def _handle_vip_status(self, reply_token: str) -> list:
        """Handle /admin/vip status."""
        status = self.vip_service.get_vip_status()
        msg = (
            "💎 VIP 隊列狀態\n"
            f"啟用: {'是' if status['enabled'] else '否'}\n"
            f"目前 VIP 排隊人數: {status['count']}"
        )
        return self._reply(reply_token, msg)

    def _handle_vip_toggle(self, value: str, reply_token: str) -> list:
        """Handle /admin/vip toggle [on/off]."""
        normalized = value.lower()
        if normalized not in {"on", "off"}:
            return self._reply(reply_token, "用法：/admin/vip toggle [on/off]")

        result = self.vip_service.toggle_vip(normalized == "on")
        return self._reply(reply_token, f"✅ {result['message']}")

    def _handle_vip_clear(self, reply_token: str) -> list:
        """Handle /admin/vip clear."""
        result = self.queue_manager.clear_vip_queue()
        return self._reply(reply_token, f"✅ 已清空 VIP 隊列，移除 {result['removed_count']} 筆")

    def _handle_admin_clear(self, reply_token: str) -> list:
        """Handle /admin/clear."""
        result = self.queue_manager.clear_all_queue()
        return self._reply(reply_token, f"✅ 已清空全部隊列，移除 {result['removed_count']} 筆")

    def _handle_admin_verify(self, args: list, reply_token: str) -> list:
        """Handle /admin/verify [user_id] [on/off]."""
        if len(args) < 2:
            return self._reply(reply_token, "用法：/admin/verify [ID] [on/off]")

        value = args[1].lower()
        if value not in {"on", "off"}:
            return self._reply(reply_token, "用法：/admin/verify [ID] [on/off]")

        result = self.queue_manager.verify_user(args[0], verified=(value == "on"))
        if result["status"] != "success":
            return self._reply(reply_token, f"❌ 錯誤：{result['message']}")

        return self._reply(
            reply_token,
            f"✅ 已更新 {result['display_name']}（{result['user_id']}）的身分驗證：{'通過' if result['verified'] else '未通過'}",
        )

    def _handle_admin_history(self, args: list, reply_token: str) -> list:
        """Handle /admin/history [ID]."""
        if not args:
            return self._reply(reply_token, "用法：/admin/history [ID]")

        user_id = args[0]
        history = self.queue_manager.get_user_history(user_id)
        if not history:
            return self._reply(reply_token, f"查無 {user_id} 的歷史紀錄")

        lines = [f"🧾 {user_id} 歷史紀錄"]
        for item in history[:10]:
            lines.append(
                f"- {item['created_at']}: {item['event_type']} ({item['queue_type'] or '-'})"
            )
        return self._reply(reply_token, "\n".join(lines))

    def _handle_export(self, reply_token: str) -> list:
        """Handle /admin/export."""
        csv_data = self.queue_manager.export_queue_csv(limit=200)
        lines = csv_data.splitlines()

        # LINE text length safety: send preview if too long.
        if len(csv_data) > 3500:
            preview = "\n".join(lines[:12])
            msg = (
                f"📤 CSV 匯出（總計 {max(len(lines) - 1, 0)} 筆，內容過長已預覽）\n"
                f"{preview}"
            )
            return self._reply(reply_token, msg)

        msg = f"📤 CSV 匯出（總計 {max(len(lines) - 1, 0)} 筆）\n{csv_data}"
        return self._reply(reply_token, msg)

    def _admin_config(self, args: list, reply_token: str) -> list:
        """Admin config update."""
        if len(args) < 2:
            return self._reply(reply_token, "用法：/admin/config max [N]")

        key = args[0]
        value = " ".join(args[1:])

        if key == "max":
            try:
                n = int(value)
                self.queue_manager.set_max_capacity(n)
                return self._reply(
                    reply_token,
                    f"✅ 已將最大容量設定為 {n}"
                )
            except ValueError:
                return self._reply(reply_token, "數字格式錯誤。")

        return self._reply(reply_token, "未知的設定鍵值。")

    def _reply(self, reply_token: str, message: str) -> list:
        """Create reply action."""
        return [{"replyToken": reply_token, "text": message}]

    def _sync_rich_menu(self, user_id: str) -> None:
        """Link different rich menus for admin vs normal users."""
        rich_menu_id = self.admin_rich_menu_id if self._is_admin(user_id) else self.user_rich_menu_id
        if rich_menu_id:
            self.notifier.link_rich_menu(user_id, rich_menu_id)

