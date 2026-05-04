"""Notifier tests."""

import pytest

from services.notifier import Notifier


class TestNotifier:
    """Tests for notification service."""

    @pytest.fixture
    def notifier(self):
        """Create notifier instance."""
        return Notifier(
            channel_secret="test_secret",
            channel_access_token="test_token"
        )

    def test_notify_served(self, notifier):
        """Served notification."""
        result = notifier.notify_served("alice", 3)
        assert "已推送" in result
        assert "號碼 #3" in result

    def test_notify_served_respects_line_push_on_served_flag(self):
        notifier = Notifier(
            channel_secret="test_secret",
            channel_access_token="test_token",
            line_push_on_served=False,
        )

        result = notifier.notify_served("alice", 3)

        assert result.startswith("已略過 LINE 被叫號推播給 alice：")
        assert "號碼 #3" in result

    def test_notify_skip(self, notifier):
        """Skip notification."""
        result = notifier.notify_skip("alice")
        assert "已推送" in result
        assert "跳過" in result

    def test_notify_queue_updated(self, notifier):
        """Queue updated notification."""
        result = notifier.notify_queue_updated("alice", 5)
        assert "已推送" in result
        assert "順位：5" in result

    def test_notify_user_still_pushes_for_line_when_served_push_disabled(self):
        notifier = Notifier(
            channel_secret="test_secret",
            channel_access_token="test_token",
            line_push_on_served=False,
        )

        result = notifier.notify_user("alice", "hello")

        assert result == "已推送給 alice：hello"

    def test_notify_join_success(self, notifier):
        """Join success notification."""
        result = notifier.notify_join_success("alice", 1)
        assert "已推送" in result
        assert "號碼是：#1" in result
