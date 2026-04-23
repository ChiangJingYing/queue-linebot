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
        admin_rich_menu_page2_id: str = "",
        user_rich_menu_id: str = "",
        location_options: dict[str, list[str]] | None = None,
    ) -> None:
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token
        self.queue_manager = queue_manager or QueueManager()
        self.vip_service = vip_service or VipService(self.queue_manager.db)
        self.notifier = Notifier(
            channel_secret=self.channel_secret,
            channel_access_token=self.channel_access_token,
            admin_rich_menu_page2_id=admin_rich_menu_page2_id,
        )
        self.admin_ids = list(admin_ids) if admin_ids else []
        self.admin_rich_menu_id = admin_rich_menu_id
        self.admin_rich_menu_page2_id = admin_rich_menu_page2_id
        self.user_rich_menu_id = user_rich_menu_id
        self.location_options = location_options or {"A": ["1", "2"], "B": ["1", "2"]}
        self.pending_actions: dict[str, dict] = {}

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

        # --- Rich Menu page switch buttons ---
        if text == "switch_page2":
            return self._handle_admin_page_switch(user_id, "page2", reply_token)
        if text == "switch_page1":
            return self._handle_admin_page_switch(user_id, "page1", reply_token)

        command, args = validate_command(text)
        pending_action = self.pending_actions.get(user_id)
        if pending_action and not text.strip().startswith("/"):
            if pending_action.get("type") == "register_name":
                return self._capture_register_name(user_id, text.strip(), reply_token)
            if pending_action.get("type") == "register_location_group":
                return self._capture_register_location_group(user_id, text.strip(), reply_token)
            if pending_action.get("type") == "register_location_item":
                return self._capture_register_location_item(user_id, text.strip(), reply_token)

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
            return self._handle_help(user_id, reply_token)
        elif command == "/register":
            return self._handle_register(user_id, args, reply_token)
        elif command == "/coffee":
            return self._handle_coffee(user_id, reply_token)
        elif command == "done":
            return self._handle_done(user_id, reply_token)
        elif command == "/admin/apply":
            # /admin/apply must bypass admin auth check (users apply to become admins)
            return self._handle_admin_apply_command(user_id, args, reply_token)
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

        profile = self.queue_manager.db.get_user_profile(target_id)
        if profile is None or not profile.display_name or not profile.location:
            return self._reply(
                reply_token,
                "❌ 錯誤：請先完成註冊（名稱與位置）後再加入隊列。",
                quick_options=[{"label": "設定基本資料", "text": "/register"}],
            )

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

    def _handle_help(self, user_id: str, reply_token: str) -> list:
        """Handle /help command."""
        if not self._is_admin(user_id):
            return self._reply(reply_token, "❌ 未授權，僅限管理員使用。")

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
            "/admin/ping - 手動提醒下一位\n"
            "/admin/ping [id] - 手動提醒指定使用者\n"
            "/admin/skip - 跳過下一位\n"
            "/admin/skip [id] - 跳過指定使用者\n"
            "/admin/status - 完整狀態\n"
            "/admin/stats - 統計面板\n"
            "/admin/clear - 清空全部隊列\n"
            "/admin/verify [id] [on/off] - 設定身分驗證\n"
            "/admin/vip toggle [on/off] - 開關 VIP 隊列\n"
            "/admin/vip clear - 清空 VIP 隊列\n"
            "/admin/join [on/off] - 切換總隊列狀態\n"
            "/admin/join status - 查看總隊列狀態\n"
            "/admin/history [id] - 查詢使用者歷史\n"
            "/admin/export - 匯出 CSV 預覽\n"
            "/admin/config max [N] - 設定最大容量"
        )
        return self._reply(reply_token, msg)

    def _handle_register(self, user_id: str, args: list, reply_token: str) -> list:
        """Handle /register by entering pending input mode."""
        if args:
            return self._complete_register(user_id, " ".join(args), reply_token)

        self.pending_actions[user_id] = {"type": "register_name"}
        return self._reply(reply_token, "請輸入你要註冊的名稱。")

    def _capture_register_name(self, user_id: str, display_name: str, reply_token: str) -> list:
        """Capture register display name and ask for location group."""
        normalized_name = display_name.strip()
        if not normalized_name:
            return self._reply(reply_token, "名稱不可為空白，請重新輸入名稱。")

        self.pending_actions[user_id] = {
            "type": "register_location_group",
            "display_name": normalized_name,
        }
        groups = list(self.location_options.keys())
        return self._reply(
            reply_token,
            f"請選擇位置第一段：{'、'.join(groups)}",
            quick_options=groups,
        )

    def _capture_register_location_group(self, user_id: str, group: str, reply_token: str) -> list:
        """Capture location group and ask for location item."""
        state = self.pending_actions.get(user_id, {})
        normalized_group = group.strip().upper()
        if normalized_group not in self.location_options:
            groups = list(self.location_options.keys())
            return self._reply(
                reply_token,
                f"無效的位置第一段，請從以下選擇：{'、'.join(groups)}",
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
            f"請選擇位置第二段（{normalized_group}-?）：{'、'.join(options)}",
            quick_options=options,
        )

    def _capture_register_location_item(self, user_id: str, item: str, reply_token: str) -> list:
        """Capture location item and complete registration."""
        state = self.pending_actions.get(user_id, {})
        group = state.get("group", "")
        display_name = state.get("display_name", "")
        normalized_item = item.strip().upper()
        options = self.location_options.get(group, [])
        if normalized_item not in options:
            return self._reply(
                reply_token,
                f"無效的位置第二段，請從以下選擇：{'、'.join(options)}",
                quick_options=options,
            )

        self.pending_actions.pop(user_id, None)
        location = f"{group}-{normalized_item}"
        return self._complete_register(user_id, display_name, location, reply_token)

    def _complete_register(self, user_id: str, display_name: str, location: str, reply_token: str) -> list:
        """Complete pending register action."""
        result = self.queue_manager.register_name(user_id, display_name, location=location)
        if result["status"] != "success":
            return self._reply(reply_token, f"❌ 錯誤：{result['message']}")

        return self._reply(reply_token, f"✅ 已更新名稱：{result['display_name']}\n位置：{result['location']}")


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
        elif command == "/admin/ping":
            return self._handle_admin_ping(args, reply_token)
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
        elif command == "/admin/join":
            return self._admin_join(args, reply_token)

        return self._reply(reply_token, "未知管理員指令。")

    def _handle_admin_apply_command(self, user_id: str, args: list, reply_token: str) -> list:
        """Handle /admin/apply with subcommands (list, approve, reject).

        This is the public-facing entry point for admin application management.
        - No args → submit application (anyone can apply)
        - list → show pending applications (admin only)
        - approve [id] → approve application (admin only)
        - reject [id] → reject application (admin only)
        """
        if not args:
            # Submit admin application (anyone can apply)
            return self._handle_admin_apply(user_id, reply_token)

        sub = args[0].lower()

        if sub == "list":
            # Admin only: view pending applications
            page_str = args[1] if len(args) > 1 else "1"
            try:
                page = int(page_str.replace("page+", "").replace("page-", ""))
            except ValueError:
                page = 1
            return self._handle_admin_apply_list(reply_token=reply_token, page=page)

        if sub == "approve":
            # Admin only: approve application
            if len(args) > 1:
                return self._handle_admin_apply_approve(user_id=user_id, target_id=args[1], reply_token=reply_token)
            return self._reply(reply_token, "用法：/admin/apply approve [user_id]")

        if sub == "reject":
            # Admin only: reject application
            if len(args) > 1:
                return self._handle_admin_apply_reject(user_id=user_id, target_id=args[1], reply_token=reply_token)
            return self._reply(reply_token, "用法：/admin/apply reject [user_id]")

        return self._reply(reply_token, "用法：/admin/apply [list|approve|reject]")

    def _handle_admin_apply(self, user_id: str, reply_token: str) -> list:
        """Handle /admin/apply – user submits admin application."""
        if self._is_admin(user_id):
            return self._reply(reply_token, "❌ 你已經是管理員了，無需再次申請。")

        profile = self.queue_manager.db.get_user_profile(user_id)
        display_name = profile.display_name if profile else user_id
        result = self.queue_manager.db.add_admin_application(user_id, display_name)

        if result["status"] == "success":
            return self._reply(
                reply_token,
                f"✅ 已提交 admin 申請\n─────────────\n您的 user_id: {user_id}\n\n管理員將審核您的申請。",
            )
        if result["status"] == "duplicate":
            return self._reply(
                reply_token,
                f"❌ 重複申請：你已經有待審核的 admin 申請了。\n   user_id: {user_id}",
            )
        return self._reply(reply_token, f"❌ 錯誤：{result.get('message', 'Unknown error')}")

    def _handle_admin_apply_list(self, reply_token: str = "", user_id: str | None = None, page: int = 1) -> list:
        """Handle /admin/apply list – show pending applications with pagination."""
        # Auth already checked by _handle_admin routing

        pending = self.queue_manager.db.get_pending_applications()
        if not pending:
            return self._reply(reply_token, "📋 Admin 申請列表\n─────────────\n目前沒有待審核的申請。")

        PAGE_SIZE = 12
        total_pages = max(1, (len(pending) + PAGE_SIZE - 1) // PAGE_SIZE)

        if page < -1:
            page = total_pages
        elif page == -1:
            page = total_pages
        elif page < 1:
            page = total_pages

        start = (page - 1) * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(pending))
        page_apps = pending[start:end]

        items = []
        for app in page_apps:
            label = f"{app['user_id']} ({app['display_name']})"
            items.append({
                "type": "action",
                "action": {
                    "type": "message",
                    "label": label,
                    "text": f"/admin/apply approve {app['user_id']}",
                },
            })

        if page > 1:
            items.append({"type": "action", "action": {"type": "message", "label": "←上一頁", "text": "/admin/apply list page-1"}})
        if page < total_pages:
            items.append({"type": "action", "action": {"type": "message", "label": "→下一頁", "text": f"/admin/apply list page+{page}"}})
        if page == total_pages:
            items.append({"type": "action", "action": {"type": "message", "label": "←返回", "text": "/admin/apply list"}})

        msg = f"📋 Admin 申請列表（第 {page}/{total_pages} 頁）\n─────────────\n"
        for i, app in enumerate(page_apps, 1):
            msg += f"{i}. {app['user_id']} ({app['display_name']})\n"

        return self._reply(reply_token, msg, quick_options=items)

    def _handle_admin_apply_approve(self, user_id: str | None = None, target_id: str = "", reply_token: str = "") -> list:
        """Handle /admin/apply approve [target_id]."""
        # Auth already checked by _handle_admin routing

        result = self.queue_manager.db.approve_admin_application(target_id, user_id or "")
        if result["status"] == "success":
            return self._reply(reply_token, f"✅ 已批准 {target_id} 的 admin 申請。")
        return self._reply(reply_token, f"❌ 找不到 {target_id} 的待審核申請。")

    def _handle_admin_apply_reject(self, user_id: str | None = None, target_id: str = "", reply_token: str = "") -> list:
        """Handle /admin/apply reject [target_id]."""
        # Auth already checked by _handle_admin routing

        result = self.queue_manager.db.reject_admin_application(target_id, user_id or "")
        if result["status"] == "success":
            return self._reply(reply_token, f"✅ 已拒絕 {target_id} 的 admin 申請。")
        return self._reply(reply_token, f"❌ 找不到 {target_id} 的待審核申請（已處理或不存在）。")

    def _is_admin(self, user_id: str) -> bool:
        """Check if user is admin."""
        if user_id in self.admin_ids:
            return True

        # Dynamic admin role from DB (e.g. approved /admin/apply users)
        try:
            return self.queue_manager.db.is_admin(user_id)
        except Exception:
            return False

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
            label = f"{name} {badge}"
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
        return self._reply(
            reply_token,
            f"✅ 已清空全部隊列，移除 {result['removed_count']} 筆，並清除 {result['cleared_profiles']} 筆註冊資料"
        )

    def _handle_admin_ping(self, args: list, reply_token: str) -> list:
        """Handle /admin/ping [ID]."""
        target_id = args[0] if args else None
        result = self.queue_manager.ping_user(target_id)
        if result["status"] != "success":
            return self._reply(reply_token, f"❌ 錯誤：{result['message']}")
        return self._reply(reply_token, f"✅ 已提醒 {result['display_name']}（{result['user_id']}）")

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

    def _admin_join(self, args: list, reply_token: str) -> list:
        """Admin: /admin/join - toggle | /admin/join on | /admin/join off | /admin/join status"""

        if not args:
            # No args: toggle (NOT logic)
            enabled = not self.queue_manager.db.is_queue_enabled()
            self.queue_manager.db.set_config("queue_enabled", "true" if enabled else "false")
            status = "開啟" if enabled else "關閉"
            return self._reply(reply_token, f"✅ 隊列已{status}")

        sub_cmd = args[0].lower()

        if sub_cmd == "on":
            self.queue_manager.db.set_config("queue_enabled", "true")
            return self._reply(reply_token, "✅ 隊列已開啟")

        if sub_cmd == "off":
            self.queue_manager.db.set_config("queue_enabled", "false")
            return self._reply(reply_token, "✅ 隊列已關閉")

        if sub_cmd == "status":
            enabled = self.queue_manager.db.is_queue_enabled()
            return self._reply(
                reply_token,
                f"📋 隊列狀態：{'已開啟' if enabled else '已關閉'}"
            )

        return self._reply(
            reply_token,
            "用法：/admin/join [on/off] 切換狀態 或 /admin/join status 查看狀態"
        )

    def _reply(self, reply_token: str, message: str, quick_options: list | None = None) -> list:
        """Create reply action with optional quick reply buttons."""

        if quick_options:
            items = []
            for item in quick_options:
                # Support both formats: {"type": "action", "action": {...}} and plain dict
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
            # Detect current menu first
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
        result = self.notifier.link_rich_menu(user_id, target_id)
        page_num = 2 if target_page == "page2" else 1
        return self._reply(reply_token, f"✅ 已切換至第 {page_num} 頁")

