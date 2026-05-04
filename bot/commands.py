"""簡單的文字指令路由器。

這個模組主要提供較輕量、可重用的 command dispatch 能力。
目前 LINE webhook 主流程已使用 ``LineBotHandler`` 為主，但這個 router
仍可用於測試、腳本或較小型的命令入口。
"""

from __future__ import annotations

from collections.abc import Callable


class CommandRouter:
    """將已註冊的文字指令分派到對應處理函式。"""

    def __init__(self) -> None:
        """初始化指令名稱到 handler 的映射表。"""
        #: 已註冊指令對應的 handler，key 一律以小寫儲存。
        self._registered_commands: dict[str, Callable] = {}

    def register(self, command: str, handler: Callable) -> None:
        """註冊單一指令的處理函式。"""
        self._registered_commands[command.lower()] = handler

    def handle(
        self, text: str, user_id: str, admin_users: list[str] = None
    ) -> dict:
        """解析文字並呼叫對應 handler。

        ``admin_users`` 目前未直接使用，但保留做舊介面相容用途。
        """
        command, args = self._parse_command(text)

        if command in self._registered_commands:
            return self._registered_commands[command](user_id, args)

        return {"status": "error", "message": "Unknown command."}

    @staticmethod
    def _parse_command(text: str) -> tuple[str, list[str]]:
        """將原始文字轉成 ``(command, args)``。"""
        from core.validators import validate_command
        return validate_command(text)
