"""LINE Push Notification service."""

from __future__ import annotations


class LinePusher:
    """Sends LINE push notifications."""

    def __init__(
        self, channel_secret: str = "", channel_access_token: str = ""
    ) -> None:
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token

    def push(self, user_id: str, message: str) -> str:
        """Send push notification."""
        # TODO: Replace with actual LINE Push API call
        return f"Pushed to {user_id}: {message}"

    def push_served(self, user_id: str, queue_number: int) -> str:
        """Push served notification."""
        msg = f"🎉 You are number #{queue_number}! Go to service area."
        return self.push(user_id, msg)

    def push_skip(self, user_id: str) -> str:
        """Push skip notification."""
        msg = "⏭ You were skipped."
        return self.push(user_id, msg)
