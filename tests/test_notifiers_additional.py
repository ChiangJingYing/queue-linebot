"""Additional notifier tests."""

from services.notifier import Notifier


class TestNotifierAdditional:
    def test_notify_user_formats_push_message(self):
        notifier = Notifier("secret", "token")
        result = notifier.notify_user("alice", "hello")

        assert result == "已推送給 alice：hello"

    def test_notify_position_changed_uses_queue_updated_message_contract(self):
        notifier = Notifier("secret", "token")
        result = notifier.notify_queue_updated("alice", 2)

        assert "alice" in result
        assert "順位：2" in result

    def test_notify_served_contains_service_area_instruction(self):
        notifier = Notifier("secret", "token")
        result = notifier.notify_served("alice", 9)

        assert "服務區" in result
        assert "#9" in result

    def test_notify_join_success_contains_checkmark_and_number(self):
        notifier = Notifier("secret", "token")
        result = notifier.notify_join_success("alice", 4)

        assert "加入隊列" in result
        assert "#4" in result
