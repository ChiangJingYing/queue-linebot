"""Bot command tests."""

import pytest

from core.queue_manager import QueueManager
from core.validators import validate_command


class TestBotCommands:
    """Tests for bot commands."""

    def test_join_command(self):
        """/join command parsed correctly."""
        cmd, args = validate_command("/join user_12345")
        assert cmd == "/join"
        assert args == ["user_12345"]

    def test_status_command(self):
        """Status command."""
        cmd, args = validate_command("/status")
        assert cmd == "/status"
        assert args == []

    def test_cancel_command(self):
        """Cancel command."""
        cmd, args = validate_command("/cancel")
        assert cmd == "/cancel"
        assert args == []

    def test_remind_command(self):
        """Remind command."""
        cmd, args = validate_command("/remind 5")
        assert cmd == "/remind"
        assert args == ["5"]

    def test_help_command(self):
        """Help command."""
        cmd, args = validate_command("/help")
        assert cmd == "/help"
        assert args == []

    def test_join_duplicate_same_user(self, queue_manager):
        """Join same user twice -> rejected by DB constraint."""
        queue_manager.join("alice", "regular")
        with pytest.raises(Exception):
            queue_manager.join("alice", "regular")

    def test_join_no_id(self, queue_manager):
        """Join without ID -> reject."""
        result = queue_manager.join("", "regular")
        assert result["status"] == "error"

    def test_vip_command(self):
        """VIP command parsed."""
        cmd, args = validate_command("/coffee")
        assert cmd == "/coffee"
        assert args == []

    def test_invalid_command(self):
        """Invalid command."""
        cmd, args = validate_command("hello world")
        assert cmd == ""
        assert args == []

    def test_join_vip_no_purchase(self, queue_manager):
        """VIP join without purchase -> reject."""
        result = queue_manager.join("non_vip", "vip")
        assert result["status"] == "error"


class TestAdminCommands:
    """Tests for admin commands."""

    def test_admin_serve(self, queue_manager):
        """Admin serve command."""
        queue_manager.join("alice", "regular")
        result = queue_manager.serve_next()
        assert result["status"] == "served"

    def test_admin_serve_specific(self, queue_manager):
        """Admin serve specific."""
        queue_manager.join("alice", "regular")
        queue_manager.join("bob", "regular")
        result = queue_manager.serve_specific("bob")
        assert result["status"] == "served"

    def test_admin_skip(self, queue_manager):
        """Admin skip command."""
        queue_manager.join("alice", "regular")
        result = queue_manager.skip_next()
        assert result["status"] == "skipped"

    def test_admin_vip_toggle(self, queue_manager):
        """Admin toggle VIP."""
        queue_manager.db.set_config("vip_enabled", "false")
        status = queue_manager.get_status()
        assert status["vip_enabled"] is False

    def test_admin_status(self, queue_manager):
        """Admin status view."""
        queue_manager.join("alice", "regular")
        status = queue_manager.get_status()
        assert status["regular_count"] == 1

    def test_admin_config(self, queue_manager):
        """Admin config update."""
        result = queue_manager.set_max_capacity(100)
        assert result["max_capacity"] == 100
