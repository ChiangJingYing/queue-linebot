"""Command router for LINE Bot."""

from __future__ import annotations


class CommandRouter:
    """Routes commands to appropriate handlers."""

    def __init__(self) -> None:
        self._registered_commands: dict[str, callable] = {}

    def register(self, command: str, handler: callable) -> None:
        """Register a command handler."""
        self._registered_commands[command.lower()] = handler

    def handle(
        self, text: str, user_id: str, admin_users: list[str] = None
    ) -> dict:
        """Process text message and return result."""
        command, args = self._parse_command(text)

        if command in self._registered_commands:
            return self._registered_commands[command](user_id, args)

        return {"status": "error", "message": "Unknown command."}

    @staticmethod
    def _parse_command(text: str) -> tuple[str, list[str]]:
        """Parse command string."""
        from core.validators import validate_command
        return validate_command(text)
