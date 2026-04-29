from __future__ import annotations

from core.database import DatabaseManager
from core.queue_manager import QueueManager


class SpyNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def notify_join_success(self, *args, **kwargs):
        self.calls.append(("notify_join_success", args, kwargs))

    def notify_skip(self, *args, **kwargs):
        self.calls.append(("notify_skip", args, kwargs))

    def notify_user(self, *args, **kwargs):
        self.calls.append(("notify_user", args, kwargs))


def test_join_success_does_not_send_push_notification(tmp_path):
    db = DatabaseManager(str(tmp_path / "queue-manager.db"))
    notifier = SpyNotifier()
    qm = QueueManager(db, notifier=notifier)
    qm.register_name("alice", "Alice", location="A-1")

    result = qm.join("alice", "regular")

    assert result["status"] == "success"
    assert notifier.calls == []


def test_join_vip_success_does_not_send_push_notification(tmp_path):
    db = DatabaseManager(str(tmp_path / "queue-manager-vip.db"))
    notifier = SpyNotifier()
    qm = QueueManager(db, notifier=notifier)
    qm.register_name("alice", "Alice", location="A-1")
    db.add_vip_purchase("alice", platform="line", coffee_id="coffee_1")
    with db._connection() as conn:
        conn.execute("UPDATE vip_purchases SET verified = 1 WHERE user_id = ?", ("alice",))
        conn.commit()

    result = qm.join("alice", "vip")

    assert result["status"] == "success"
    assert notifier.calls == []
