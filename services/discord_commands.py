"""Discord DM 指令入口與互動元件整合層。

此模組建立在共用 queue flow 之上，負責：
- 將 Discord interaction payload 正規化成共用命令
- 轉接 register/cancel/join/status/history/help 等流程
- 組裝 Discord modal 與 button components
- 視需要透過 Telegram admin notification service 廣播後台通知
"""

from __future__ import annotations

from core.database import DatabaseManager
from core.queue_manager import QueueManager
from core.time_utils import format_display_time
from core.validators import validate_command
from services.action_schema import (
    DISCORD_CANCEL_ABORT,
    DISCORD_CANCEL_CONFIRM,
    DISCORD_REGISTER_GROUP_PREFIX,
    DISCORD_REGISTER_ITEM_PREFIX,
    build_discord_register_group_action,
    build_discord_register_item_action,
    is_discord_register_choice_action,
    normalize_discord_action,
    normalize_register_choice_action,
)
from services.cancel_flow import begin_closed_queue_cancel_flow, advance_closed_queue_cancel_flow
from services.interaction_presenters import (
    build_discord_cancel_confirmation_components,
    build_discord_choice_components,
    build_discord_menu_components,
)
from services.pending_state_store import ConfigPendingStateStore
from services.register_flow import advance_register_flow, begin_register_location_flow
from services.register_service import complete_registration
from services.telegram_admin_notifications import TelegramAdminNotificationService
from services.user_flow import build_help_message, build_history_message, cancel_user, get_user_status, join_user
from services.admin_flow import release_user


class DiscordCommandService:
    """Discord 平台的 command façade 與 component presenter。"""

    #: 廣播給 admin 時使用的平台標籤。
    PLATFORM_LABEL = "Discord"
    #: 一般使用者固定功能列。
    USER_ACTION_ROWS = [
        [
            {"label": "舉手", "custom_id": "menu:join", "style": "primary"},
            {"label": "放棄", "custom_id": "menu:cancel", "style": "secondary"},
            {"label": "看狀態", "custom_id": "menu:status", "style": "secondary"},
        ],
        [
            {"label": "看紀錄", "custom_id": "menu:history", "style": "secondary"},
            {"label": "設定資料", "custom_id": "register:start", "style": "secondary"},
            {"label": "幫助", "custom_id": "menu:help", "style": "secondary"},
        ],
    ]

    def __init__(
        self,
        *,
        db,
        location_options: dict[str, list[str]] | None = None,
        telegram_sender=None,
        notification_dispatcher=None,
        line_display_name_resolver=None,
    ) -> None:
        """建立 Discord command service 與其共用依賴。"""
        self.db = db
        #: Discord command 層共用的隊列核心；join/cancel/status 都透過它落到共用邏輯。
        self.queue_manager = QueueManager(db) if isinstance(db, DatabaseManager) else None
        self.location_options = location_options or {"A": ["1", "2"], "B": ["1", "2"]}
        #: 保存 Discord register/cancel 多步驟互動狀態。
        self.pending_state_store = ConfigPendingStateStore(db, namespace="discord")
        #: 透過 Telegram 發送給管理員的後台事件廣播 service。
        self.notification_service = (
            TelegramAdminNotificationService(
                db=db,
                sender=telegram_sender,
                dispatcher=notification_dispatcher,
                line_display_name_resolver=line_display_name_resolver,
            )
            if telegram_sender is not None
            else None
        )

    def handle_interaction(self, *, user_id: str, input_value: str) -> dict:
        """處理 Discord slash command、button action 與 modal submit payload。"""
        raw_text = (input_value or "").strip()
        normalized_text = normalize_discord_action(raw_text)

        if normalized_text.startswith("register:submit:"):
            display_name = normalized_text.removeprefix("register:submit:").strip()
            if not display_name:
                return {"status": "error", "message": "學號不可為空白，請重新輸入學號。"}
            return self._start_register_flow(user_id=user_id, display_name=display_name)

        if pending := self._get_pending_register_state(user_id):
            if normalized_text.startswith("/") and normalized_text != "/register":
                self._clear_pending_register_state(user_id)
            elif is_discord_register_choice_action(normalized_text):
                return self._handle_register_pending(user_id=user_id, text=normalized_text, state=pending)

        if normalized_text in {DISCORD_CANCEL_CONFIRM, DISCORD_CANCEL_ABORT}:
            return self._handle_cancel_confirmation(user_id=user_id, action=normalized_text)

        command, args = validate_command(normalized_text)
        if command == "/menu":
            return self._handle_menu()
        if command == "/register":
            return self._handle_register(user_id=user_id, args=args)
        if command == "/join":
            return self._handle_join(user_id=user_id, args=args)
        if command == "/cancel":
            return self._handle_cancel(user_id=user_id)
        if command == "/status":
            return self._handle_status(user_id=user_id)
        if command == "/history":
            return self._handle_user_history(user_id=user_id)
        if command == "/help":
            return self._handle_help()
        if command == "/admin/release":
            return self._handle_admin_release(user_id=user_id, args=args)
        # if command == "/admin/release_confirm":
        #     return self._handle_admin_release(user_id=user_id, args=args)

        return {"status": "error", "message": "Unknown command."}

    def _normalize_action(self, text: str) -> str:
        """將 Discord menu/button action 正規化為共用命令字串。"""
        return normalize_discord_action(text)

    def _handle_menu(self) -> dict:
        """回傳 Discord 使用者功能選單。"""
        return {
            "status": "success",
            "message": "請使用下方功能選單。",
            "components": build_discord_menu_components(self.USER_ACTION_ROWS),
        }

    def _handle_register(self, *, user_id: str, args: list[str]) -> dict:
        """啟動 Discord 註冊 modal。"""
        if args:
            return {"status": "error", "message": "❌ 錯誤：/register 不接受參數，請直接輸入 /register 後依提示完成註冊。"}

        return self._build_register_modal()

    def _build_register_modal(self) -> dict:
        """建立 Discord 學號輸入 modal。"""
        return {
            "status": "modal",
            "modal": {
                "custom_id": "register:submit",
                "title": "設定基本資料",
                "components": [
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": "text_input",
                                "custom_id": "student_id",
                                "label": "學號",
                                "style": "short",
                                "required": True,
                                "placeholder": "請輸入學號",
                            }
                        ],
                    }
                ],
            },
        }

    def _start_register_flow(self, *, user_id: str, display_name: str) -> dict:
        """在 Discord modal 送出學號後，進入排別/座位多步驟流程。"""
        outcome = begin_register_location_flow(
            display_name=display_name,
            location_options=self.location_options,
        )
        self._set_pending_register_state(user_id, outcome["state"])
        return {
            "status": "pending",
            "message": outcome["message"],
            "components": build_discord_choice_components(options=outcome["options"], prefix=DISCORD_REGISTER_GROUP_PREFIX),
        }

    def _handle_join(self, *, user_id: str, args: list[str]) -> dict:
        """處理 Discord 使用者加入隊列，必要時附回後續操作按鈕。"""
        queue_type = args[0].lower() if args else "regular"
        outcome = join_user(queue_manager=self.queue_manager, user_id=user_id, queue_type=queue_type)
        if outcome["status"] == "needs_registration":
            return {
                "status": "error",
                "message": outcome["message"],
                "components": self._button_rows([[{"label": "設定基本資料", "custom_id": "register:start", "style": "primary"}]]),
            }

        if outcome["status"] != "success":
            raw = outcome.get("raw_result", {})
            if raw.get("message") == "目前隊列已關閉，請稍後再試。":
                self._broadcast_join_error_event(
                    user_id=user_id,
                    command_text="/join" if queue_type == "regular" else f"/join {queue_type}",
                    error_message=raw["message"],
                )
            return {"status": "error", "message": outcome["message"]}

        if self.notification_service is not None:
            self.notification_service.broadcast_event(
                category="join",
                title="排隊通知",
                actor_label=f"使用者：{self.db.get_display_name(user_id)}",
                target_label=f"隊列：{queue_type}",
                detail_lines=[
                    f"號碼：#{outcome['queue_number']}",
                    f"目前總人數：{outcome['total_in_queue']}",
                ],
                platform=self.PLATFORM_LABEL,
            )

        return {
            "status": "success",
            "message": f"✅ 已加入隊列，號碼 #{outcome['queue_number']}（目前 {outcome['total_in_queue']} 人）",
            "components": self._button_rows([
                [
                    {"label": "放棄", "custom_id": "menu:cancel", "style": "secondary"},
                    {"label": "看狀態", "custom_id": "menu:status", "style": "secondary"},
                    {"label": "看紀錄", "custom_id": "menu:history", "style": "secondary"},
                ]
            ]),
        }

    def _broadcast_join_error_event(self, *, user_id: str, command_text: str, error_message: str) -> None:
        """Broadcast join failures that should be visible to Telegram admins."""
        if self.notification_service is None:
            return
        self.notification_service.broadcast_event(
            category="error",
            title="失敗通知",
            actor_label=f"使用者：{self.db.get_display_name(user_id)}",
            target_label=f"指令：{command_text}",
            detail_lines=[f"原因：{error_message}"],
            platform=self.PLATFORM_LABEL,
        )

    def _handle_cancel(self, *, user_id: str) -> dict:
        """處理取消排隊；封隊時改走 Discord 二次確認按鈕流程。"""
        if not self.queue_manager.get_queue_enabled() and self.queue_manager.get_user_position(user_id) is not None:
            outcome = begin_closed_queue_cancel_flow()
            self.pending_state_store.set(user_id=user_id, flow="cancel", state=outcome["state"])
            return {
                "status": "pending",
                "message": outcome["message"],
                "components": build_discord_cancel_confirmation_components(),
            }

        outcome = cancel_user(queue_manager=self.queue_manager, user_id=user_id)
        if outcome["status"] != "cancelled":
            return {"status": "error", "message": outcome["message"]}
        if self.notification_service is not None:
            self.notification_service.broadcast_event(
                category="cancel",
                title="取消通知",
                actor_label=f"使用者：{self.db.get_display_name(user_id)}",
                target_label="動作：離開隊列",
                platform=self.PLATFORM_LABEL,
            )
        return {"status": "success", "message": "✅ 已取消排隊", "components": self._button_rows(self.USER_ACTION_ROWS)}

    def _handle_status(self, *, user_id: str) -> dict:
        """回傳 Discord 版個人隊列狀態。"""
        outcome = get_user_status(queue_manager=self.queue_manager, user_id=user_id)
        if outcome["status"] == "not_in_queue":
            return {
                "status": "success",
                "message": f"📊 目前有 {outcome['total_count']} 人在排隊中",
                "components": self._button_rows([
                    [
                        {"label": "舉手", "custom_id": "menu:join", "style": "primary"},
                        {"label": "設定資料", "custom_id": "register:start", "style": "secondary"},
                    ]
                ]),
            }

        return {
            "status": "success",
            "message": f"📊 目前排在第 {outcome['position']} 位\n前面還有 {outcome['ahead_count']} 人",
            "components": self._button_rows([
                [
                    {"label": "舉手", "custom_id": "menu:join", "style": "primary"},
                    {"label": "放棄", "custom_id": "menu:cancel", "style": "secondary"},
                    {"label": "看紀錄", "custom_id": "menu:history", "style": "secondary"},
                ]
            ]),
        }

    def _handle_user_history(self, *, user_id: str) -> dict:
        """回傳使用者歷史紀錄，並保留 Discord 功能按鈕。"""
        history = self.queue_manager.get_user_history(user_id)
        return {
            "status": "success",
            "message": build_history_message(
                history,
                formatter=lambda item: f"- {format_display_time(item['created_at'])}: {item['event_type']} ({item['queue_type'] or '-'})",
            ),
            "components": self._button_rows(self.USER_ACTION_ROWS),
        }

    def _handle_help(self) -> dict:
        """回傳 Discord 使用者版說明文字。"""
        outcome = build_help_message(
            is_admin=False,
            include_menu=True,
            include_admin_commands=False,
            include_vip_join=False,
            include_coffee=False,
        )
        return {"status": outcome["status"], "message": outcome["message"], "components": self._button_rows(self.USER_ACTION_ROWS)}

    # def _handle_admin_release(self, *, user_id: str, args: list[str]) -> dict:
    #     """處理 Discord admin 解除叫號鎖定。"""
    #     if not self.db.is_admin(user_id):
    #         return {"status": "error", "message": "❌ 未授權，僅限管理員使用。"}

    #     if not args:
    #         return {"status": "error", "message": "用法：/admin/release [user_id]"}
            
    #     target_id = args[0]
    #     result = release_user(queue_manager=self.queue_manager, user_id=target_id)
    #     if result["status"] != "released":
    #         return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}

    #     target_display_name = self.db.get_display_name(target_id)
    #     if self.notification_service is not None:
    #         self.notification_service.broadcast_event(
    #             category="admin_action",
    #             title="解除叫號通知",
    #             actor_label=f"管理員：{self.db.get_display_name(user_id)}（{user_id}）",
    #             target_label=f"對象：{target_display_name}（{target_id}）",
    #             detail_lines=[f"號碼：#{result['queue_number']}"],
    #             platform=self.PLATFORM_LABEL,
    #         )
    #     return {"status": "success", "message": f"✅ 已解除 {target_display_name} 的叫號鎖定，其可重新排隊"}

    def _normalize_register_pending_text(self, *, text: str, state: dict) -> str:
        """將 Discord 註冊 callback 還原成 flow state machine 可理解的值。"""
        if not is_discord_register_choice_action(text):
            return text

        if state.get("type") == "register_location_group":
            return normalize_register_choice_action(text, expected_prefix=DISCORD_REGISTER_GROUP_PREFIX)
        if state.get("type") == "register_location_item":
            return normalize_register_choice_action(text, expected_prefix=DISCORD_REGISTER_ITEM_PREFIX)
        return text

    def _handle_register_pending(self, *, user_id: str, text: str, state: dict) -> dict:
        """推進 Discord 註冊 pending state。"""
        normalized_pending_text = self._normalize_register_pending_text(text=text, state=state)
        outcome = advance_register_flow(
            state=state,
            text=normalized_pending_text,
            location_options=self.location_options,
        )

        if outcome["status"] == "pending":
            self._set_pending_register_state(user_id, outcome["state"])
            prefix = DISCORD_REGISTER_ITEM_PREFIX if outcome["state"]["type"] == "register_location_item" else DISCORD_REGISTER_GROUP_PREFIX
            return {
                "status": "pending",
                "message": outcome["message"],
                "components": self._button_rows([
                    self._choice_buttons(outcome["options"], prefix=prefix)
                ]),
            }

        if outcome["status"] == "error":
            response = {"status": "error", "message": outcome["message"]}
            if "options" in outcome:
                prefix = DISCORD_REGISTER_ITEM_PREFIX if state.get("type") == "register_location_item" else DISCORD_REGISTER_GROUP_PREFIX
                response["components"] = build_discord_choice_components(options=outcome["options"], prefix=prefix)
            return response

        if outcome["status"] == "complete":
            self._clear_pending_register_state(user_id)
            return self._complete_register(
                user_id=user_id,
                display_name=outcome["display_name"],
                location=outcome["location"],
            )

        self._clear_pending_register_state(user_id)
        return {"status": "error", "message": outcome["message"]}

    def _complete_register(self, *, user_id: str, display_name: str, location: str) -> dict:
        """將 Discord 註冊結果落地並返回預設功能列。"""
        outcome = complete_registration(
            queue_manager=self.queue_manager,
            user_id=user_id,
            display_name=display_name,
            location=location,
        )
        if outcome["status"] != "success":
            return {"status": "error", "message": outcome["message"]}

        return {
            "status": "success",
            "message": outcome["message"],
            "components": self._button_rows(self.USER_ACTION_ROWS),
        }

    def _handle_cancel_confirmation(self, *, user_id: str, action: str) -> dict:
        """處理 Discord 封隊放棄確認按鈕的狀態推進。"""
        state = self._get_pending_cancel_state(user_id)
        outcome = advance_closed_queue_cancel_flow(
            state=state,
            action="確認放棄" if action == DISCORD_CANCEL_CONFIRM else "取消放棄",
            still_in_queue=self.queue_manager.get_user_position(user_id) is not None,
            expired_message="❌ 放棄確認流程已失效，請重新按一次放棄。",
        )

        if outcome["status"] == "expired":
            return {
                "status": "error",
                "message": outcome["message"],
                "components": self._button_rows(self.USER_ACTION_ROWS),
            }

        if outcome["status"] == "aborted":
            self._clear_pending_cancel_state(user_id)
            return {"status": "success", "message": outcome["message"], "components": self._button_rows(self.USER_ACTION_ROWS)}

        if outcome["status"] == "not_in_queue":
            self._clear_pending_cancel_state(user_id)
            return {"status": "error", "message": outcome["message"], "components": self._button_rows(self.USER_ACTION_ROWS)}

        if outcome["status"] == "pending":
            self.pending_state_store.set(user_id=user_id, flow="cancel", state=outcome["state"])
            return {
                "status": "pending",
                "message": outcome["message"],
                "components": build_discord_cancel_confirmation_components(),
            }

        self._clear_pending_cancel_state(user_id)
        result = self.queue_manager.cancel(user_id)
        if result["status"] != "cancelled":
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}", "components": self._button_rows(self.USER_ACTION_ROWS)}
        if self.notification_service is not None:
            self.notification_service.broadcast_event(
                category="cancel",
                title="取消通知",
                actor_label=f"使用者：{self.db.get_display_name(user_id)}",
                target_label="動作：離開隊列",
                platform=self.PLATFORM_LABEL,
            )
        return {"status": "success", "message": "✅ 已取消排隊", "components": self._button_rows(self.USER_ACTION_ROWS)}


    def _button_rows(self, rows: list[list[dict]]) -> list[dict]:
        """將內部按鈕列表示法轉成 Discord components rows。"""
        return build_discord_menu_components(rows)

    def _choice_buttons(self, options: list[str], *, prefix: str) -> list[dict]:
        """建立單一 action row 可直接使用的 Discord 選項按鈕。"""
        return [
            {
                "label": button["label"],
                "custom_id": button["custom_id"],
                "style": button.get("style", "secondary"),
            }
            for button in build_discord_choice_components(options=options, prefix=prefix)[0]["components"]
        ]

    def _cancel_confirmation_buttons(self) -> list[dict]:
        """建立 Discord 封隊取消確認的單列按鈕。"""
        return [
            {
                "label": button["label"],
                "custom_id": button["custom_id"],
                "style": button.get("style", "secondary"),
            }
            for button in build_discord_cancel_confirmation_components()[0]["components"]
        ]

    def _get_pending_register_state(self, user_id: str) -> dict:
        """讀取 Discord 註冊流程 pending state。"""
        return self.pending_state_store.get(user_id=user_id, flow="register")

    def _set_pending_register_state(self, user_id: str, state: dict) -> None:
        """寫入 Discord 註冊流程 pending state。"""
        self.pending_state_store.set(user_id=user_id, flow="register", state=state)

    def _clear_pending_register_state(self, user_id: str) -> None:
        """清除 Discord 註冊流程 pending state。"""
        self.pending_state_store.clear(user_id=user_id, flow="register")

    def _get_pending_cancel_state(self, user_id: str) -> dict:
        """讀取 Discord 封隊取消流程 pending state。"""
        return self.pending_state_store.get(user_id=user_id, flow="cancel")

    def _clear_pending_cancel_state(self, user_id: str) -> None:
        """清除 Discord 封隊取消流程 pending state。"""
        self.pending_state_store.clear(user_id=user_id, flow="cancel")
