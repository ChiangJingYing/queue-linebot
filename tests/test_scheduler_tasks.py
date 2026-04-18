"""Scheduler task tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from scheduler import check_reminders, check_timeouts, register_timeout_job


class FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify_user(self, user_id: str, message: str):
        self.calls.append((user_id, message))
        return f"Pushed to {user_id}: {message}"


class FakeScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, *args, **kwargs):
        self.jobs.append((args, kwargs))


def test_check_timeouts_cancels_expired_entries(queue_manager):
    queue_manager.join("alice", "regular")
    queue_manager.join("bob", "regular")

    with queue_manager.db._connection() as conn:
        conn.execute(
            "UPDATE queues SET join_time = ? WHERE user_id = ?",
            ((datetime.now() - timedelta(minutes=31)).isoformat(), "alice"),
        )
        conn.commit()

    notifier = FakeNotifier()
    result = check_timeouts(queue_manager, notifier)

    assert result["status"] == "ok"
    assert result["removed_count"] == 1
    assert result["removed"][0]["user_id"] == "alice"
    assert notifier.calls[0][0] == "alice"
    assert [entry.user_id for entry in queue_manager.get_queue()] == ["bob"]


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


def test_register_timeout_job_registers_interval_job(queue_manager):
    scheduler = FakeScheduler()
    notifier = FakeNotifier()

    register_timeout_job(scheduler, queue_manager, notifier)

    assert len(scheduler.jobs) == 1
    args, kwargs = scheduler.jobs[0]
    assert args[0] is check_timeouts
    assert args[1] == "interval"
    assert kwargs["seconds"] == 60
    assert kwargs["id"] == "queue-timeout-check"
    assert kwargs["replace_existing"] is True
    assert kwargs["args"] == [queue_manager, notifier]
