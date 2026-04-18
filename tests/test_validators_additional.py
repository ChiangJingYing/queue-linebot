"""Additional validator tests."""

from core.validators import validate_command, validate_user_id


class TestValidateUserIdAdditional:
    def test_accepts_exactly_100_characters(self):
        user_id = "a" * 100
        assert validate_user_id(user_id) == user_id

    def test_rejects_embedded_newline_characters(self):
        assert validate_user_id("ali\nce") is None


class TestValidateCommandAdditional:
    def test_command_with_multiple_spaces(self):
        cmd, args = validate_command("  /JOIN   alice   vip  ")
        assert cmd == "/join"
        assert args == ["alice", "vip"]

    def test_slash_only_command(self):
        cmd, args = validate_command("/")
        assert cmd == ""
        assert args == []
