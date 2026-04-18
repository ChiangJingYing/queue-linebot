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
        assert "Pushed" in result
        assert "number #3" in result

    def test_notify_skip(self, notifier):
        """Skip notification."""
        result = notifier.notify_skip("alice")
        assert "Pushed" in result
        assert "skipped" in result.lower()

    def test_notify_queue_updated(self, notifier):
        """Queue updated notification."""
        result = notifier.notify_queue_updated("alice", 5)
        assert "Pushed" in result
        assert "position: 5" in result

    def test_notify_join_success(self, notifier):
        """Join success notification."""
        result = notifier.notify_join_success("alice", 1)
        assert "Pushed" in result
        assert "number: #1" in result
