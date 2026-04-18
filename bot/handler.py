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
    ) -> None:
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token
        self.queue_manager = queue_manager or QueueManager()
        self.vip_service = vip_service or VipService(self.queue_manager.db)
        self.notifier = Notifier(channel_secret, channel_access_token)
        self.admin_ids = admin_ids or []

    def handle_event(self, event) -> list:
        """Handle a LINE event. Returns list of reply actions."""
        if hasattr(event, "message") and getattr(event.message, "type", None) == "text":
            return self._handle_message(event)
        return []

    def _handle_message(self, event) -> list:
        """Process text message."""
        text = event.message.text
        user_id = event.source.userId

        command, args = validate_command(text)

        if command == "/join":
            return self._handle_join(user_id, args, event.reply_token)
        elif command == "/cancel":
            return self._handle_cancel(user_id, event.reply_token)
        elif command == "/status":
            return self._handle_status(event.reply_token)
        elif command == "/remind":
            return self._handle_remind(user_id, args, event.reply_token)
        elif command == "/help":
            return self._handle_help(event.reply_token)
        elif command == "/coffee":
            return self._handle_coffee(user_id, event.reply_token)
        elif command.startswith("/admin/"):
            return self._handle_admin(user_id, command, args, event.reply_token)

        return self._reply(event.reply_token, "Unknown command. Type /help for options.")

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
                f"✅ Joined queue!\n"
                f"   Queue number: #{result['queue_number']}\n"
                f"   Position: {result['position']}\n"
                f"   Total in queue: {result['total_in_queue']}"
            )
        else:
            msg = f"❌ Error: {result['message']}"

        return self._reply(reply_token, msg)

    def _handle_cancel(self, user_id: str, reply_token: str) -> list:
        """Handle /cancel command."""
        result = self.queue_manager.cancel(user_id)

        if result["status"] == "cancelled":
            msg = (
                f"✅ Cancelled!\n"
                f"   Original position: #{result['removed_position']}\n"
                f"   New total: {result['new_total']}"
            )
        else:
            msg = f"❌ Error: {result['message']}"

        return self._reply(reply_token, msg)

    def _handle_status(self, reply_token: str) -> list:
        """Handle /status command."""
        status = self.queue_manager.get_status()
        msg = (
            f"📊 Queue Status\n\n"
            f"Regular Queue: {status['regular_count']} people\n"
            f"VIP Queue: {status['vip_count']} people\n"
            f"VIP Enabled: {'Yes' if status['vip_enabled'] else 'No'}"
        )
        return self._reply(reply_token, msg)

    def _handle_remind(self, user_id: str, args: list, reply_token: str) -> list:
        """Handle /remind command.

        Current lightweight implementation acknowledges the requested threshold
        and sends a confirmation push message through the notifier.
        """
        if len(args) < 1:
            return self._reply(reply_token, "Usage: /remind N\nExample: /remind 3")

        try:
            n = int(args[0])
            if n <= 0:
                raise ValueError
            self.notifier.notify_queue_updated(user_id, n)
            return self._reply(reply_token, f"✅ Reminder set for position {n}")
        except ValueError:
            return self._reply(reply_token, "Invalid number. Use /remind N")

    def _handle_coffee(self, user_id: str, reply_token: str) -> list:
        """Handle /coffee command."""
        msg = (
            "☕ Buy a Coffee to get VIP queue access!\n\n"
            f"[Buy Coffee](https://buymeacoffee.com/yourname)\n\n"
            "After purchasing, type /join vip to join VIP queue."
        )
        return self._reply(reply_token, msg)

    def _handle_help(self, reply_token: str) -> list:
        """Handle /help command."""
        msg = (
            "📋 Queue System Commands\n\n"
            "**Regular Users:**\n"
            "/join - Join regular queue as yourself\n"
            "/join vip - Join VIP queue as yourself\n"
            "/join [id] [queue_type] - Join queue for a specific user\n"
            "/cancel - Cancel queue\n"
            "/status - View queue status\n"
            "/remind N - Get reminder at position N\n"
            "/coffee - Get VIP link\n"
            "/help - Show help\n\n"
            "**Admin Commands (prefix with /admin/):**\n"
            "/admin/serve - Serve next\n"
            "/admin/serve [id] - Serve specific\n"
            "/admin/skip - Skip next\n"
            "/admin/skip [id] - Skip specific\n"
            "/admin/status - Full status\n"
            "/admin/config max [N] - Set max capacity"
        )
        return self._reply(reply_token, msg)

    def _handle_admin(self, user_id: str, command: str, args: list,
                      reply_token: str) -> list:
        """Handle admin commands."""
        if not self._is_admin(user_id):
            return self._reply(reply_token, "❌ Unauthorized. Admin only.")

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
        elif command == "/admin/config":
            return self._admin_config(args, reply_token)

        return self._reply(reply_token, "Unknown admin command.")

    def _is_admin(self, user_id: str) -> bool:
        """Check if user is admin."""
        return user_id in self.admin_ids

    def _admin_serve_next(self, reply_token: str) -> list:
        """Serve next in queue."""
        result = self.queue_manager.serve_next()
        if result["status"] == "served":
            msg = f"✅ Served #{result['id']} (number {result['queue_number']})"
        else:
            msg = f"❌ Error: {result['message']}"
        return self._reply(reply_token, msg)

    def _admin_serve(self, user_id: str, target_id: str, reply_token: str) -> list:
        """Serve specific user."""
        result = self.queue_manager.serve_specific(target_id)
        if result["status"] == "served":
            msg = f"✅ Served #{result['id']} (number {result['queue_number']})"
        else:
            msg = f"❌ Error: {result['message']}"
        return self._reply(reply_token, msg)

    def _admin_skip_next(self, reply_token: str) -> list:
        """Skip next in queue."""
        result = self.queue_manager.skip_next()
        if result["status"] == "skipped":
            msg = f"⏭ Skipped #{result['id']} (number {result['queue_number']})"
        else:
            msg = f"❌ Error: {result['message']}"
        return self._reply(reply_token, msg)

    def _admin_skip(self, user_id: str, target_id: str, reply_token: str) -> list:
        """Skip specific user."""
        result = self.queue_manager.skip_specific(target_id)
        if result["status"] == "skipped":
            msg = f"⏭ Skipped #{result['id']} (number {result['queue_number']})"
        else:
            msg = f"❌ Error: {result['message']}"
        return self._reply(reply_token, msg)

    def _admin_status(self, reply_token: str) -> list:
        """Admin full status view."""
        status = self.queue_manager.get_status()
        msg = (
            f"📋 Full Queue Status\n\n"
            f"Regular Queue ({status['regular_count']}): "
            f"head: {status['regular_head']}\n"
            f"VIP Queue ({status['vip_count']}): "
            f"head: {status['vip_next']}, enabled: {status['vip_enabled']}"
        )
        return self._reply(reply_token, msg)

    def _admin_config(self, args: list, reply_token: str) -> list:
        """Admin config update."""
        if len(args) < 2:
            return self._reply(reply_token, "Usage: /admin/config max [N]")

        key = args[0]
        value = " ".join(args[1:])

        if key == "max":
            try:
                n = int(value)
                self.queue_manager.set_max_capacity(n)
                return self._reply(
                    reply_token,
                    f"✅ Max capacity set to {n}"
                )
            except ValueError:
                return self._reply(reply_token, "Invalid number.")

        return self._reply(reply_token, "Unknown config key.")

    def _reply(self, reply_token: str, message: str) -> list:
        """Create reply action.

        Falls back to a simple dict if the LINE SDK is not installed, which keeps
        the handler testable in local/dev environments.
        """
        try:
            from line_bot_sdk import models
            return [
                models.ReplyMessage(
                    replyToken=reply_token,
                    text=message
                )
            ]
        except ImportError:
            return [{"replyToken": reply_token, "text": message}]
