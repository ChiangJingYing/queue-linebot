"""Discord DM user command handling built on the shared queue logic."""

from __future__ import annotations

import json

from core.database import DatabaseManager
from core.queue_manager import QueueManager
from core.time_utils import format_display_time
from core.validators import validate_command


class DiscordCommandService:
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

    def __init__(self, *, db, location_options: dict[str, list[str]] | None = None) -> None:
        self.db = db
        self.queue_manager = QueueManager(db) if isinstance(db, DatabaseManager) else None
        self.location_options = location_options or {"A": ["1", "2"], "B": ["1", "2"]}

    def handle_interaction(self, *, user_id: str, input_value: str) -> dict:
        raw_text = (input_value or "").strip()
        normalized_text = self._normalize_action(raw_text)

        if normalized_text.startswith("register:submit:"):
            display_name = normalized_text.removeprefix("register:submit:").strip()
            if not display_name:
                return {"status": "error", "message": "學號不可為空白，請重新輸入學號。"}
            return self._start_register_flow(user_id=user_id, display_name=display_name)

        if pending := self._get_pending_register_state(user_id):
            if normalized_text.startswith("/") and normalized_text != "/register":
                self._clear_pending_register_state(user_id)
            elif normalized_text.startswith(("register:group:", "register:item:")):
                return self._handle_register_pending(user_id=user_id, text=normalized_text, state=pending)

        if normalized_text in {"cancel:confirm", "cancel:abort"}:
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

        return {"status": "error", "message": "Unknown command."}

    def _normalize_action(self, text: str) -> str:
        action_map = {
            "menu:join": "/join",
            "menu:cancel": "/cancel",
            "menu:status": "/status",
            "menu:history": "/history",
            "menu:help": "/help",
            "register:start": "/register",
        }
        return action_map.get(text, text)

    def _handle_menu(self) -> dict:
        return {
            "status": "success",
            "message": "請使用下方功能選單。",
            "components": self._button_rows(self.USER_ACTION_ROWS),
        }

    def _handle_register(self, *, user_id: str, args: list[str]) -> dict:
        if args:
            return {"status": "error", "message": "❌ 錯誤：/register 不接受參數，請直接輸入 /register 後依提示完成註冊。"}

        return self._build_register_modal()

    def _build_register_modal(self) -> dict:
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
        self._set_pending_register_state(user_id, {"type": "register_location_group", "display_name": display_name})
        groups = list(self.location_options.keys())
        return {
            "status": "pending",
            "message": f"請選擇您在第幾排座位：{'、'.join(groups)}",
            "components": self._button_rows([self._choice_buttons(groups, prefix="register:group:")]),
        }

    def _handle_join(self, *, user_id: str, args: list[str]) -> dict:
        profile = self.db.get_user_profile(user_id)
        if profile is None or not profile.display_name or not profile.location:
            return {
                "status": "error",
                "message": "❌ 錯誤：請先完成註冊（學號與座位）後再加入隊列。",
                "components": self._button_rows([[{"label": "設定基本資料", "custom_id": "register:start", "style": "primary"}]]),
            }

        queue_type = args[0].lower() if args else "regular"
        result = self.queue_manager.join(user_id, queue_type)
        if result["status"] != "success":
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}

        return {
            "status": "success",
            "message": f"✅ 已加入隊列，號碼 #{result['queue_number']}（目前 {result['total_in_queue']} 人）",
            "components": self._button_rows([
                [
                    {"label": "放棄", "custom_id": "menu:cancel", "style": "secondary"},
                    {"label": "看狀態", "custom_id": "menu:status", "style": "secondary"},
                    {"label": "看紀錄", "custom_id": "menu:history", "style": "secondary"},
                ]
            ]),
        }

    def _handle_cancel(self, *, user_id: str) -> dict:
        if not self.queue_manager.get_queue_enabled() and self.queue_manager.get_user_position(user_id) is not None:
            self.db.set_config(f"discord_pending_cancel:{user_id}", json.dumps({"type": "cancel_when_closed", "step": 1}))
            return {
                "status": "pending",
                "message": "當前隊列已關閉，確定要放棄嗎？\n若放棄無法再加入到隊列中！",
                "components": self._button_rows([self._cancel_confirmation_buttons()]),
            }

        result = self.queue_manager.cancel(user_id)
        if result["status"] != "cancelled":
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}
        return {"status": "success", "message": "✅ 已取消排隊", "components": self._button_rows(self.USER_ACTION_ROWS)}

    def _handle_status(self, *, user_id: str) -> dict:
        position = self.queue_manager.get_user_position(user_id)
        if position is None:
            total_count = len(self.queue_manager.get_queue())
            return {
                "status": "success",
                "message": f"📊 目前有 {total_count} 人在排隊中",
                "components": self._button_rows([
                    [
                        {"label": "舉手", "custom_id": "menu:join", "style": "primary"},
                        {"label": "設定資料", "custom_id": "register:start", "style": "secondary"},
                    ]
                ]),
            }

        ahead_count = max(position - 1, 0)
        return {
            "status": "success",
            "message": f"📊 目前排在第 {position} 位\n前面還有 {ahead_count} 人",
            "components": self._button_rows([
                [
                    {"label": "舉手", "custom_id": "menu:join", "style": "primary"},
                    {"label": "放棄", "custom_id": "menu:cancel", "style": "secondary"},
                    {"label": "看紀錄", "custom_id": "menu:history", "style": "secondary"},
                ]
            ]),
        }

    def _handle_user_history(self, *, user_id: str) -> dict:
        history = self.queue_manager.get_user_history(user_id)
        if not history:
            return {"status": "success", "message": "查無排隊歷史紀錄。", "components": self._button_rows(self.USER_ACTION_ROWS)}

        lines = ["排隊歷史紀錄"]
        for item in history[:10]:
            lines.append(
                f"- {format_display_time(item['created_at'])}: {item['event_type']} ({item['queue_type'] or '-'})"
            )
        return {"status": "success", "message": "\n".join(lines), "components": self._button_rows(self.USER_ACTION_ROWS)}

    def _handle_help(self) -> dict:
        msg = (
            "📋 隊列系統指令\n\n"
            "/register - 依提示完成學號與座位註冊\n"
            "/join - 以自己身分加入一般隊列\n"
            "/cancel - 取消排隊\n"
            "/status - 查看隊列狀態\n"
            "/history - 查看你的排隊歷史\n"
            "/menu - 顯示常用功能按鈕\n"
            "/help - 顯示說明\n"
        )
        return {"status": "success", "message": msg, "components": self._button_rows(self.USER_ACTION_ROWS)}

    def _handle_register_pending(self, *, user_id: str, text: str, state: dict) -> dict:
        step_type = state.get("type")
        raw_text = text.strip()

        if step_type == "register_location_group":
            normalized_group = raw_text.removeprefix("register:group:").upper()
            groups = list(self.location_options.keys())
            if normalized_group not in self.location_options:
                return {
                    "status": "error",
                    "message": f"無效的位置，請從以下選擇：{'、'.join(groups)}",
                    "components": self._button_rows([self._choice_buttons(groups, prefix="register:group:")]),
                }
            self._set_pending_register_state(
                user_id,
                {
                    "type": "register_location_item",
                    "display_name": str(state.get("display_name") or ""),
                    "group": normalized_group,
                },
            )
            options = self.location_options[normalized_group]
            return {
                "status": "pending",
                "message": f"請選擇您的座位（{normalized_group}-?）：{'、'.join(options)}",
                "components": self._button_rows([self._choice_buttons(options, prefix="register:item:")]),
            }

        if step_type == "register_location_item":
            group = str(state.get("group") or "")
            display_name = str(state.get("display_name") or "")
            normalized_item = raw_text.removeprefix("register:item:").upper()
            options = self.location_options.get(group, [])
            if normalized_item not in options:
                return {
                    "status": "error",
                    "message": f"無效的位置，請從以下選擇：{'、'.join(options)}",
                    "components": self._button_rows([self._choice_buttons(options, prefix="register:item:")]),
                }
            self._clear_pending_register_state(user_id)
            return self._complete_register(user_id=user_id, display_name=display_name, location=f"{group}-{normalized_item}")

        self._clear_pending_register_state(user_id)
        return {"status": "error", "message": "❌ 註冊流程已失效，請重新輸入 /register。"}

    def _complete_register(self, *, user_id: str, display_name: str, location: str) -> dict:
        result = self.queue_manager.register_name(user_id, display_name, location=location)
        if result["status"] != "success":
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}

        return {
            "status": "success",
            "message": f"✅ 已更新學號：{result['display_name']}\n位置：{result['location']}",
            "components": self._button_rows(self.USER_ACTION_ROWS),
        }

    def _handle_cancel_confirmation(self, *, user_id: str, action: str) -> dict:
        state = self._get_pending_cancel_state(user_id)
        if state.get("type") != "cancel_when_closed" or state.get("step") not in {1, 2}:
            return {
                "status": "error",
                "message": "❌ 放棄確認流程已失效，請重新按一次放棄。",
                "components": self._button_rows(self.USER_ACTION_ROWS),
            }

        if action == "cancel:abort":
            self._clear_pending_cancel_state(user_id)
            return {"status": "success", "message": "好的，已取消放棄", "components": self._button_rows(self.USER_ACTION_ROWS)}

        if self.queue_manager.get_user_position(user_id) is None:
            self._clear_pending_cancel_state(user_id)
            return {"status": "error", "message": "❌ 錯誤：你目前不在隊列中。"}

        if state.get("step") == 1:
            self.db.set_config(f"discord_pending_cancel:{user_id}", json.dumps({"type": "cancel_when_closed", "step": 2}))
            return {
                "status": "pending",
                "message": "您確定要放棄嗎？",
                "components": self._button_rows([self._cancel_confirmation_buttons()]),
            }

        self._clear_pending_cancel_state(user_id)
        result = self.queue_manager.cancel(user_id)
        if result["status"] != "cancelled":
            return {"status": "error", "message": f"❌ 錯誤：{result['message']}"}
        return {"status": "success", "message": "✅ 已取消排隊", "components": self._button_rows(self.USER_ACTION_ROWS)}

    def _button_rows(self, rows: list[list[dict]]) -> list[dict]:
        action_rows: list[dict] = []
        for row in rows:
            for start in range(0, len(row), 5):
                chunk = row[start:start + 5]
                action_rows.append(
                    {
                        "type": 1,
                        "components": [
                            {
                                "type": 2,
                                "style": self._discord_button_style(item.get("style", "secondary")),
                                "label": item["label"],
                                "custom_id": item["custom_id"],
                            }
                            for item in chunk
                        ],
                    }
                )
        return action_rows

    def _choice_buttons(self, options: list[str], *, prefix: str) -> list[dict]:
        return [
            {"label": str(option), "custom_id": f"{prefix}{option}", "style": "secondary"}
            for option in options
        ]

    def _cancel_confirmation_buttons(self) -> list[dict]:
        return [
            {"label": "確認放棄", "custom_id": "cancel:confirm", "style": "danger"},
            {"label": "取消放棄", "custom_id": "cancel:abort", "style": "secondary"},
        ]

    def _discord_button_style(self, style: str) -> int:
        mapping = {
            "primary": 1,
            "secondary": 2,
            "success": 3,
            "danger": 4,
        }
        return mapping.get(style, 2)

    def _get_pending_register_state(self, user_id: str) -> dict:
        raw = self.db.get_config(f"discord_pending_register:{user_id}")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _set_pending_register_state(self, user_id: str, state: dict) -> None:
        self.db.set_config(f"discord_pending_register:{user_id}", json.dumps(state, ensure_ascii=False))

    def _clear_pending_register_state(self, user_id: str) -> None:
        self.db.set_config(f"discord_pending_register:{user_id}", "")

    def _get_pending_cancel_state(self, user_id: str) -> dict:
        raw = self.db.get_config(f"discord_pending_cancel:{user_id}")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _clear_pending_cancel_state(self, user_id: str) -> None:
        self.db.set_config(f"discord_pending_cancel:{user_id}", "")
