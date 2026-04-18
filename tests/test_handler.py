"""Handler tests."""

from __future__ import annotations

from types import SimpleNamespace

from bot.handler import LineBotHandler
from core.queue_manager import QueueManager
from core.database import DatabaseManager


def make_event(text: str, user_id: str = "alice", reply_token: str = "reply-token"):
    return SimpleNamespace(
        message=SimpleNamespace(type="text", text=text),
        source=SimpleNamespace(userId=user_id),
        reply_token=reply_token,
    )


def reply_texts(result):
    return [item["text"] if isinstance(item, dict) else getattr(item, "text", "") for item in result]


def test_handle_join_without_args_joins_current_user(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    handler = LineBotHandler(queue_manager=QueueManager(db))

    result = handler.handle_event(make_event("/join", user_id="alice"))

    assert "Joined queue" in reply_texts(result)[0]
    assert [entry.user_id for entry in handler.queue_manager.get_queue()] == ["alice"]


def test_handle_join_vip_short_form_joins_current_user(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    db.add_vip_purchase("alice", platform="line", coffee_id="coffee_1")
    with db._connection() as conn:
        conn.execute("UPDATE vip_purchases SET verified = 1 WHERE user_id = ?", ("alice",))
        conn.commit()

    handler = LineBotHandler(queue_manager=QueueManager(db))
    result = handler.handle_event(make_event("/join vip", user_id="alice"))

    assert "Joined queue" in reply_texts(result)[0]
    queue = handler.queue_manager.get_queue()
    assert len(queue) == 1
    assert queue[0].queue_type == "vip"


def test_admin_status_uses_vip_head_value(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    db.add_vip_purchase("vip_alice", platform="line", coffee_id="coffee_1")
    with db._connection() as conn:
        conn.execute("UPDATE vip_purchases SET verified = 1 WHERE user_id = ?", ("vip_alice",))
        conn.commit()

    qm = QueueManager(db)
    qm.join("alice", "regular")
    qm.join("vip_alice", "vip")

    handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])
    result = handler.handle_event(make_event("/admin/status", user_id="admin"))

    text = reply_texts(result)[0]
    assert "user_vip_alice" in text
    assert "user_alice" in text


def test_reply_falls_back_to_dict_when_line_sdk_missing(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    handler = LineBotHandler(queue_manager=QueueManager(db))

    result = handler._reply("token", "hello")

    assert result == [{"replyToken": "token", "text": "hello"}]
