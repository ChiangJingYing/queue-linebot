"""Notification service - LINE Push/Reply stubs."""

from __future__ import annotations


class Notifier:
    """Sends notifications via LINE Push API."""

    def __init__(
        self,
        channel_secret: str = "",
        channel_access_token: str = "",
    ) -> None:
        self.channel_secret = channel_secret
        self.channel_access_token = channel_access_token

    def notify_user(self, user_id: str, message: str) -> str:
        """Send push notification to user."""
        # TODO: Replace with actual LINE Push API call
        return f"Pushed to {user_id}: {message}"

    def notify_served(self, user_id: str, queue_number: int) -> str:
        """Notify user they are being served."""
        msg = (
            f"\U0001f389 You are number #{queue_number}!\n"
            "Please go to the service area.\n"
            "Reply 'done' when finished."
        )
        return self.notify_user(user_id, msg)

    def notify_skip(self, user_id: str) -> str:
        """Notify user was skipped."""
        msg = "\u23ed You were skipped. Queue position changed."
        return self.notify_user(user_id, msg)

    def notify_queue_updated(self, user_id: str, position: int) -> str:
        """Notify user someone ahead left."""
        msg = f"Someone ahead left. Your position: {position}"
        return self.notify_user(user_id, msg)

    def notify_join_success(self, user_id: str, queue_number: int) -> str:
        """Notify user joined successfully."""
        msg = f"\u2705 Joined queue! Your number: #{queue_number}"
        return self.notify_user(user_id, msg)
