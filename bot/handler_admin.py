from __future__ import annotations

from core.time_utils import format_display_time, now_in_taipei
from services.admin_flow import (
    build_admin_export_preview,
    build_admin_history,
    build_admin_stats,
    build_admin_status,
    build_vip_status,
    clear_all_queue,
    clear_vip_queue,
    get_admin_join_status,
    ping_user,
    set_admin_join_enabled,
    toggle_admin_join,
    toggle_vip,
)
from services.serve_flow import serve_user


class HandlerAdminMixin:
    LINE_NOTIFICATION_PLATFORM = "Line"

    def _handle_admin(self, user_id: str, command: str, args: list, reply_token: str) -> list:
        if not self._is_admin(user_id):
            return self._reply(reply_token, "❌ 未授權，僅限管理員使用。")

        if command == "/admin/serve" and len(args) > 0:
            return self._admin_serve(user_id, args[0], reply_token)
        elif command == "/admin/serve":
            return self._admin_serve_next(user_id, reply_token)
        elif command == "/admin/status":
            return self._admin_status(reply_token)
        elif command == "/admin/stats":
            return self._handle_stats(reply_token)
        elif command == "/admin/history":
            return self._handle_admin_history(args, reply_token)
        elif command == "/admin/export":
            return self._handle_export(reply_token)
        elif command == "/admin/clear":
            return self._handle_admin_clear(user_id, reply_token)
        elif command == "/admin/ping":
            return self._handle_admin_ping(args, reply_token)
        elif command == "/admin/vip":
            if len(args) >= 1 and args[0] == "status":
                return self._handle_vip_status(reply_token)
            if len(args) >= 2 and args[0] == "toggle":
                return self._handle_vip_toggle(user_id, args[1], reply_token)
            if len(args) >= 1 and args[0] == "clear":
                return self._handle_vip_clear(user_id, reply_token)
        elif command == "/admin/config":
            return self._admin_config(args, reply_token)
        elif command == "/admin/join":
            return self._admin_join(args, reply_token)

        return self._reply(reply_token, "未知管理員指令。")

    def _handle_admin_apply_command(self, user_id: str, args: list, reply_token: str) -> list:
        if not args:
            return self._handle_admin_apply(user_id, reply_token)

        if not self._is_admin(user_id):
            return self._reply(reply_token, "❌ 未授權，僅限管理員使用。")

        sub = args[0].lower()

        if sub == "list":
            page_str = args[1] if len(args) > 1 else "1"
            try:
                page = int(page_str.replace("page+", "").replace("page-", ""))
            except ValueError:
                page = 1
            return self._handle_admin_apply_list(reply_token=reply_token, page=page)

        if sub == "approve":
            if len(args) > 1:
                return self._handle_admin_apply_approve(user_id=user_id, target_id=args[1], reply_token=reply_token)
            return self._reply(reply_token, "用法：/admin/apply approve [user_id]")

        if sub == "reject":
            if len(args) > 1:
                return self._handle_admin_apply_reject(user_id=user_id, target_id=args[1], reply_token=reply_token)
            return self._reply(reply_token, "用法：/admin/apply reject [user_id]")

        return self._reply(reply_token, "用法：/admin/apply [list|approve|reject]")

    def _handle_admin_apply(self, user_id: str, reply_token: str) -> list:
        if self._is_admin(user_id):
            return self._reply(reply_token, "❌ 你已經是管理員了，無需再次申請。")

        profile = self.queue_manager.db.get_user_profile(user_id)
        display_name = profile.display_name if profile else user_id
        result = self.queue_manager.db.add_admin_application(user_id, display_name)

        if result["status"] == "success":
            return self._reply(reply_token, f"✅ 已提交 admin 申請\n─────────────\n您的 user_id: {user_id}\n\n管理員將審核您的申請。")
        if result["status"] == "duplicate":
            return self._reply(reply_token, f"❌ 重複申請：你已經有待審核的 admin 申請了。\n   user_id: {user_id}")
        return self._reply(reply_token, f"❌ 錯誤：{result.get('message', 'Unknown error')}")

    def _handle_admin_apply_list(self, reply_token: str = "", user_id: str | None = None, page: int = 1) -> list:
        pending = self.queue_manager.db.get_pending_applications()
        if not pending:
            return self._reply(reply_token, "📋 Admin 申請列表\n─────────────\n目前沒有待審核的申請。")

        page_size = 12
        total_pages = max(1, (len(pending) + page_size - 1) // page_size)

        if page < -1:
            page = total_pages
        elif page == -1:
            page = total_pages
        elif page < 1:
            page = total_pages

        start = (page - 1) * page_size
        end = min(start + page_size, len(pending))
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
        result = self.queue_manager.db.approve_admin_application(target_id, user_id or "")
        if result["status"] == "success":
            return self._reply(reply_token, f"✅ 已批准 {target_id} 的 admin 申請。")
        return self._reply(reply_token, f"❌ 找不到 {target_id} 的待審核申請。")

    def _handle_admin_apply_reject(self, user_id: str | None = None, target_id: str = "", reply_token: str = "") -> list:
        result = self.queue_manager.db.reject_admin_application(target_id, user_id or "")
        if result["status"] == "success":
            return self._reply(reply_token, f"✅ 已拒絕 {target_id} 的 admin 申請。")
        return self._reply(reply_token, f"❌ 找不到 {target_id} 的待審核申請（已處理或不存在）。")

    def _is_admin(self, user_id: str) -> bool:
        if user_id in self.admin_ids:
            return True
        try:
            return self.queue_manager.db.is_admin(user_id)
        except Exception:
            return False

    def _admin_serve_guard_message(self) -> str | None:
        now = self._admin_serve_cooldown_clock()
        cooldown_seconds = self._admin_serve_cooldown_seconds
        if cooldown_seconds > 0 and self._last_admin_serve_at:
            if now - self._last_admin_serve_at < cooldown_seconds:
                label = self._last_admin_serve_label or "上一位使用者"
                return f"⚠️ 剛剛已叫號：{label}，請稍候再試，避免重複叫號。"
        return None

    def _record_admin_serve_success(self, display_name: str) -> None:
        self._last_admin_serve_at = self._admin_serve_cooldown_clock()
        self._last_admin_serve_label = display_name

    def _broadcast_simple_event(
        self,
        *,
        category: str,
        title: str,
        actor_label: str,
        target_label: str,
        detail_lines: list[str] | None = None,
    ) -> None:
        if getattr(self, "notification_service", None) is None:
            return
        self.notification_service.broadcast_event(
            category=category,
            title=title,
            actor_label=actor_label,
            target_label=target_label,
            detail_lines=detail_lines,
            platform=self.LINE_NOTIFICATION_PLATFORM,
        )

    def _broadcast_serve_event(
        self,
        *,
        admin_user_id: str,
        admin_display_name: str,
        target_user_id: str,
        target_display_name: str,
        command_text: str,
    ) -> None:
        if getattr(self, "notification_service", None) is None:
            return
        self.notification_service.broadcast_serve_event(
            admin_user_id=admin_user_id,
            admin_display_name=admin_display_name,
            target_user_id=target_user_id,
            target_display_name=target_display_name,
            command_text=command_text,
            at_text=now_in_taipei().strftime("%Y-%m-%d %H:%M:%S"),
            platform=self.LINE_NOTIFICATION_PLATFORM,
        )

    def _admin_serve_next(self, user_id: str, reply_token: str) -> list:
        if not self._admin_serve_lock.acquire(blocking=False):
            return self._reply(reply_token, "⚠️ 叫號進行中，請勿重複操作。")
        try:
            guard_message = self._admin_serve_guard_message()
            if guard_message:
                return self._reply(reply_token, guard_message)

            result = serve_user(queue_manager=self.queue_manager, announcement_service=self.announcement_service)
            if result["status"] == "served":
                display_name = result["display_name"]
                self._record_admin_serve_success(display_name)
                self._broadcast_serve_event(
                    admin_user_id=user_id,
                    admin_display_name=self.queue_manager.db.get_display_name(user_id),
                    target_user_id=result["target_user_id"],
                    target_display_name=display_name,
                    command_text="/admin/serve",
                )
                msg = f"✅ 已叫號：{display_name}"
            else:
                msg = f"❌ 錯誤：{result['message']}"
            return self._reply(reply_token, msg)
        finally:
            self._admin_serve_lock.release()

    def _admin_serve(self, user_id: str, target_id: str, reply_token: str) -> list:
        if not self._admin_serve_lock.acquire(blocking=False):
            return self._reply(reply_token, "⚠️ 叫號進行中，請勿重複操作。")
        try:
            guard_message = self._admin_serve_guard_message()
            if guard_message:
                return self._reply(reply_token, guard_message)

            result = serve_user(
                queue_manager=self.queue_manager,
                target_user_id=target_id,
                announcement_service=self.announcement_service,
            )
            if result["status"] == "served":
                display_name = result["display_name"]
                self._record_admin_serve_success(display_name)
                self._broadcast_serve_event(
                    admin_user_id=user_id,
                    admin_display_name=self.queue_manager.db.get_display_name(user_id),
                    target_user_id=result["target_user_id"],
                    target_display_name=display_name,
                    command_text=f"/admin/serve {target_id}",
                )
                msg = f"✅ 已叫號：{display_name}"
            else:
                msg = f"❌ 錯誤：{result['message']}"
            return self._reply(reply_token, msg)
        finally:
            self._admin_serve_lock.release()

    def _admin_status(self, reply_token: str) -> list:
        status = build_admin_status(queue_manager=self.queue_manager)

        regular_lines = [
            f"#{idx} {entry['display_name']} {'✅' if entry['verified'] else '🕓'} — {format_display_time(entry['join_time'], include_date=False)}"
            for idx, entry in enumerate(status["regular_entries"], start=1)
        ]
        vip_lines = [
            f"#{idx} {entry['display_name']} {'✅' if entry['verified'] else '🕓'} — {format_display_time(entry['join_time'], include_date=False)}"
            for idx, entry in enumerate(status["vip_entries"], start=1)
        ]

        regular_text = "\n".join(regular_lines) if regular_lines else "（空）"
        vip_text = "\n".join(vip_lines) if vip_lines else "（空）"
        message = (
            "📋 完整隊列狀態\n\n"
            f"標準隊列 ({status['regular_count']}人):\n{regular_text}\n\n"
            f"VIP 隊列 ({status['vip_count']}人):\n{vip_text}\n\n"
            f"VIP 啟用: {'是' if status['vip_enabled'] else '否'}"
        )
        return self._reply(reply_token, message)

    def _handle_stats(self, reply_token: str) -> list:
        stats = build_admin_stats(queue_manager=self.queue_manager)
        message = (
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
        return self._reply(reply_token, message)

    def _handle_vip_status(self, reply_token: str) -> list:
        status = build_vip_status(vip_service=self.vip_service)
        message = (
            "💎 VIP 隊列狀態\n"
            f"啟用: {'是' if status['enabled'] else '否'}\n"
            f"目前 VIP 排隊人數: {status['count']}"
        )
        return self._reply(reply_token, message)

    def _handle_vip_toggle(self, user_id: str, value: str, reply_token: str) -> list:
        normalized = value.lower()
        if normalized not in {"on", "off"}:
            return self._reply(reply_token, "用法：/admin/vip toggle [on/off]")

        result = toggle_vip(vip_service=self.vip_service, enabled=normalized == "on")
        self._broadcast_simple_event(
            category="admin_action",
            title="管理操作通知",
            actor_label=f"管理員：{self.queue_manager.db.get_display_name(user_id)}（{user_id}）",
            target_label=f"指令：/admin/vip toggle {normalized}",
            detail_lines=[f"結果：{result['message']}"],
        )
        return self._reply(reply_token, f"✅ {result['message']}")

    def _handle_vip_clear(self, user_id: str, reply_token: str) -> list:
        result = clear_vip_queue(queue_manager=self.queue_manager)
        self._broadcast_simple_event(
            category="admin_action",
            title="管理操作通知",
            actor_label=f"管理員：{self.queue_manager.db.get_display_name(user_id)}（{user_id}）",
            target_label="指令：/admin/vip clear",
            detail_lines=[f"結果：移除 {result['removed_count']} 筆 VIP 隊列"],
        )
        return self._reply(reply_token, f"✅ 已清空 VIP 隊列，移除 {result['removed_count']} 筆")

    def _handle_admin_clear(self, user_id: str, reply_token: str) -> list:
        keep_admin_user_ids = set(self.admin_ids)
        result = clear_all_queue(queue_manager=self.queue_manager, keep_admin_user_ids=keep_admin_user_ids)
        self._announce_new_order_on_next_join = True
        self._broadcast_simple_event(
            category="admin_action",
            title="管理操作通知",
            actor_label=f"管理員：{self.queue_manager.db.get_display_name(user_id)}（{user_id}）",
            target_label="指令：/admin/clear",
            detail_lines=[f"結果：移除 {result['removed_count']} 筆隊列，清除 {result['cleared_profiles']} 筆使用者資料"],
        )
        return self._reply(reply_token, f"✅ 已清空全部隊列，移除 {result['removed_count']} 筆，並清除 {result['cleared_profiles']} 筆使用者資料、保留 {result['kept_admin_profiles']} 筆 admin 資料")

    def _handle_admin_ping(self, args: list, reply_token: str) -> list:
        target_id = args[0] if args else None
        result = ping_user(queue_manager=self.queue_manager, target_id=target_id)
        if result["status"] != "success":
            return self._reply(reply_token, f"❌ 錯誤：{result['message']}")
        return self._reply(reply_token, f"✅ 已提醒 {result['display_name']}（{result['user_id']}）")

    def _handle_admin_history(self, args: list, reply_token: str) -> list:
        if not args:
            return self._reply(reply_token, "用法：/admin/history [ID]")

        user_id = args[0]
        payload = build_admin_history(queue_manager=self.queue_manager, user_id=user_id)
        if payload is None:
            return self._reply(reply_token, f"查無 {user_id} 的歷史紀錄")
        lines = [f"🧾 {payload['user_id']} 歷史紀錄"]
        for item in payload["history"]:
            lines.append(f"- {format_display_time(item['created_at'])}: {item['event_type']} ({item['queue_type'] or '-'})")
        return self._reply(reply_token, "\n".join(lines))

    def _handle_export(self, reply_token: str) -> list:
        payload = build_admin_export_preview(queue_manager=self.queue_manager)
        if payload["is_preview"]:
            message = f"📤 CSV 匯出（總計 {payload['total']} 筆，內容過長已預覽）\n{payload['preview']}"
        else:
            message = f"📤 CSV 匯出（總計 {payload['total']} 筆）\n{payload['csv_data']}"
        return self._reply(reply_token, message)

    def _admin_config(self, args: list, reply_token: str) -> list:
        if len(args) < 2:
            return self._reply(reply_token, "用法：/admin/config max [N]")

        key = args[0]
        value = " ".join(args[1:])

        if key == "max":
            try:
                n = int(value)
                self.queue_manager.set_max_capacity(n)
                return self._reply(reply_token, f"✅ 已將最大容量設定為 {n}")
            except ValueError:
                return self._reply(reply_token, "數字格式錯誤。")

        return self._reply(reply_token, "未知的設定鍵值。")

    def _admin_join(self, args: list, reply_token: str) -> list:
        if not args:
            result = toggle_admin_join(queue_manager=self.queue_manager)
            return self._reply(reply_token, f"✅ 隊列已{'開啟' if result['enabled'] else '關閉'}")

        sub_cmd = args[0].lower()
        if sub_cmd == "on":
            result = set_admin_join_enabled(queue_manager=self.queue_manager, enabled=True)
            return self._reply(reply_token, f"✅ 隊列已{'開啟' if result['enabled'] else '關閉'}")
        if sub_cmd == "off":
            result = set_admin_join_enabled(queue_manager=self.queue_manager, enabled=False)
            return self._reply(reply_token, f"✅ 隊列已{'開啟' if result['enabled'] else '關閉'}")
        if sub_cmd == "status":
            result = get_admin_join_status(queue_manager=self.queue_manager)
            return self._reply(reply_token, f"📋 隊列狀態：{'已開啟' if result['enabled'] else '已關閉'}")

        return self._reply(reply_token, "用法：/admin/join [on/off] 切換狀態 或 /admin/join status 查看狀態")
