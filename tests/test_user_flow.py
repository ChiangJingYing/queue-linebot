from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.user_flow import (
    HELP_UNAUTHORIZED_MESSAGE,
    HISTORY_EMPTY_MESSAGE,
    build_help_message,
    build_history_message,
    cancel_user,
    get_user_status,
    join_user,
)


def _make_queue_manager(tmp_path):
    db = DatabaseManager(str(tmp_path / "shared-user-flow.db"))
    return QueueManager(db)


def test_join_user_requires_registration(tmp_path):
    qm = _make_queue_manager(tmp_path)

    outcome = join_user(queue_manager=qm, user_id="alice")

    assert outcome == {
        "status": "needs_registration",
        "message": "❌ 錯誤：請先完成註冊（學號與座位）後再加入隊列。",
    }


def test_join_user_returns_shared_success_payload(tmp_path):
    qm = _make_queue_manager(tmp_path)
    qm.register_name("alice", "Alice", location="A-1")

    outcome = join_user(queue_manager=qm, user_id="alice", queue_type="regular")

    assert outcome["status"] == "success"
    assert outcome["queue_number"] == 1
    assert outcome["position"] == 1
    assert outcome["total_in_queue"] == 1


def test_cancel_user_returns_shared_cancelled_payload(tmp_path):
    qm = _make_queue_manager(tmp_path)
    qm.register_name("alice", "Alice", location="A-1")
    qm.join("alice", "regular")

    outcome = cancel_user(queue_manager=qm, user_id="alice")

    assert outcome["status"] == "cancelled"
    assert outcome["removed_position"] == 1
    assert outcome["new_total"] == 0


def test_get_user_status_reports_position_and_ahead_count(tmp_path):
    qm = _make_queue_manager(tmp_path)
    qm.register_name("alice", "Alice", location="A-1")
    qm.register_name("bob", "Bob", location="A-2")
    qm.join("alice", "regular")
    qm.join("bob", "regular")

    outcome = get_user_status(queue_manager=qm, user_id="bob")

    assert outcome == {
        "status": "in_queue",
        "position": 2,
        "ahead_count": 1,
        "total_count": 2,
    }


def test_get_user_status_reports_total_count_when_not_in_queue(tmp_path):
    qm = _make_queue_manager(tmp_path)
    qm.register_name("alice", "Alice", location="A-1")
    qm.join("alice", "regular")

    outcome = get_user_status(queue_manager=qm, user_id="bob")

    assert outcome == {
        "status": "not_in_queue",
        "position": None,
        "ahead_count": None,
        "total_count": 1,
    }


def test_build_history_message_supports_dict_history_format():
    history = [
        {"created_at": "2026-01-01T10:00:00", "event_type": "join", "queue_type": "regular"},
        {"created_at": "2026-01-01T10:05:00", "event_type": "cancel", "queue_type": "regular"},
    ]

    message = build_history_message(
        history,
        formatter=lambda item: f"- {item['created_at']}: {item['event_type']} ({item['queue_type'] or '-'})",
    )

    assert message == (
        "排隊歷史紀錄\n"
        "- 2026-01-01T10:00:00: join (regular)\n"
        "- 2026-01-01T10:05:00: cancel (regular)"
    )


def test_build_history_message_supports_object_history_format():
    class Entry:
        def __init__(self, queue_number, queue_type, status, time):
            self.queue_number = queue_number
            self.queue_type = queue_type
            self.status = status
            self.time = time

    history = [Entry(1, "regular", "cancelled", "10:05")]

    message = build_history_message(
        history,
        formatter=lambda entry: f"#{entry.queue_number} {entry.queue_type} - {entry.status} ({entry.time})",
    )

    assert message == "排隊歷史紀錄\n#1 regular - cancelled (10:05)"


def test_build_history_message_returns_shared_empty_message():
    message = build_history_message([], formatter=lambda item: str(item))
    assert message == HISTORY_EMPTY_MESSAGE


def test_build_help_message_for_non_admin_user():
    outcome = build_help_message(is_admin=False, include_menu=True)

    assert outcome["status"] == "success"
    assert "/menu - 顯示常用功能按鈕" in outcome["message"]
    assert "管理員指令" not in outcome["message"]


def test_build_help_message_can_be_admin_only():
    denied = build_help_message(is_admin=False, admin_only=True, include_admin_commands=True, include_coffee=True)
    allowed = build_help_message(is_admin=True, admin_only=True, include_admin_commands=True, include_coffee=True)

    assert denied == {"status": "error", "message": HELP_UNAUTHORIZED_MESSAGE}
    assert allowed["status"] == "success"
    assert "管理員指令" in allowed["message"]
    assert "/coffee - 取得 VIP 連結" in allowed["message"]
