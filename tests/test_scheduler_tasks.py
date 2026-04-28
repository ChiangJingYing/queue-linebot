"""Scheduler task tests."""

from __future__ import annotations

from types import SimpleNamespace

from scheduler import check_reminders


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify_user(self, user_id: str, message: str):
        self.calls.append((user_id, message))
        return f"Pushed to {user_id}: {message}"



def test_check_reminders_notifies_when_position_reaches_target():
    entries = [
        SimpleNamespace(user_id="alice", reminder_position=1, reminder_sent=False),
        SimpleNamespace(user_id="bob", reminder_position=3, reminder_sent=False),
        SimpleNamespace(user_id="charlie", reminder_position=None, reminder_sent=False),
    ]
    queue_manager = SimpleNamespace(get_queue=lambda: entries)
    notifier = FakeNotifier()

    result = check_reminders(queue_manager, notifier)

    assert result["status"] == "ok"
    assert result["sent_count"] == 2
    assert [call[0] for call in notifier.calls] == ["alice", "bob"]
    assert entries[0].reminder_sent is True
    assert entries[1].reminder_sent is True
