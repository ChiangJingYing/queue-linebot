"""Validator tests."""

import pytest

from core.validators import validate_user_id, validate_command


class TestValidateUserId:
    """Tests for ID validation."""

    def test_valid_id(self):
        """Valid ID passes."""
        assert validate_user_id("user_12345") == "user_12345"

    def test_valid_id_with_hyphen(self):
        """ID with hyphen passes."""
        assert validate_user_id("user-12345") == "user-12345"

    def test_empty_id(self):
        """Empty string fails."""
        assert validate_user_id("") is None

    def test_whitespace_only(self):
        """Whitespace only fails."""
        assert validate_user_id("   ") is None

    def test_too_long(self):
        """Over 100 chars fails."""
        assert validate_user_id("x" * 101) is None

    def test_special_chars(self):
        """Special characters fail."""
        assert validate_user_id("user!@#") is None

    def test_space_in_id(self):
        """Space in ID fails."""
        assert validate_user_id("user name") is None

    def test_strips_whitespace(self):
        """Leading/trailing whitespace stripped."""
        result = validate_user_id("  alice  ")
        assert result == "alice"

    def test_numeric_id(self):
        """Numeric ID passes."""
        assert validate_user_id("12345") == "12345"


class TestValidateCommand:
    """Tests for command validation."""

    def test_valid_command(self):
        """Normal command."""
        cmd, args = validate_command("/join user_12345")
        assert cmd == "/join"
        assert args == ["user_12345"]

    def test_command_no_args(self):
        """Command without args."""
        cmd, args = validate_command("/status")
        assert cmd == "/status"
        assert args == []

    def test_invalid_command(self):
        """Not a command."""
        cmd, args = validate_command("hello")
        assert cmd == ""
        assert args == []

    def test_empty_string(self):
        """Empty string."""
        cmd, args = validate_command("")
        assert cmd == ""
        assert args == []

    def test_lowercase_command(self):
        """Command converted to lowercase."""
        cmd, args = validate_command("/JOIN user_12345")
        assert cmd == "/join"
        assert args == ["user_12345"]
