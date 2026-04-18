"""Handler tests."""

from __future__ import annotations

from datetime import datetime, timedelta
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

    assert "加入隊列成功" in reply_texts(result)[0]
    assert [entry.user_id for entry in handler.queue_manager.get_queue()] == ["alice"]



def test_handle_history_returns_user_history(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    qm = QueueManager(db)
    qm.join("alice", "regular")
    qm.cancel("alice")
    handler = LineBotHandler(queue_manager=qm)

    result = handler.handle_event(make_event("/history", user_id="alice"))

    text = reply_texts(result)[0]
    assert "排隊歷史紀錄" in text
    assert "#1" in text
    assert "cancelled" in text



def test_handle_history_returns_empty_message_when_no_history(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    handler = LineBotHandler(queue_manager=QueueManager(db))

    result = handler.handle_event(make_event("/history", user_id="alice"))

    assert reply_texts(result)[0] == "查無排隊歷史紀錄。"



def test_handle_join_vip_short_form_joins_current_user(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    db.add_vip_purchase("alice", platform="line", coffee_id="coffee_1")
    with db._connection() as conn:
        conn.execute("UPDATE vip_purchases SET verified = 1 WHERE user_id = ?", ("alice",))
        conn.commit()

    handler = LineBotHandler(queue_manager=QueueManager(db))
    result = handler.handle_event(make_event("/join vip", user_id="alice"))

    assert "加入隊列成功" in reply_texts(result)[0]
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
    assert "vip_alice" in text
    assert "alice" in text



def test_admin_stats_returns_formatted_metrics(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    db.add_vip_purchase("vip_alice", platform="line", coffee_id="coffee_1")
    with db._connection() as conn:
        conn.execute("UPDATE vip_purchases SET verified = 1 WHERE user_id = ?", ("vip_alice",))
        conn.commit()

    qm = QueueManager(db)
    qm.join("alice", "regular")
    qm.join("bob", "regular")
    qm.join("vip_alice", "vip")
    qm.serve_specific("alice")
    qm.skip_specific("bob")

    with db._connection() as conn:
        join_time = (datetime.now() - timedelta(minutes=10)).isoformat()
        served_time = datetime.now().isoformat()
        conn.execute(
            "UPDATE queues SET join_time = ?, served_time = ? WHERE user_id = ?",
            (join_time, served_time, "alice"),
        )
        conn.commit()

    handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])
    result = handler.handle_event(make_event("/admin/stats", user_id="admin"))

    text = reply_texts(result)[0]
    assert "今日排隊人數" in text
    assert "被叫號人數: 1" in text
    assert "被跳過人數: 1" in text
    assert "VIP" in text



def test_admin_vip_status_shows_enabled_and_count(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    db.add_vip_purchase("vip_alice", platform="line", coffee_id="coffee_1", verified=True)

    qm = QueueManager(db)
    qm.join("vip_alice", "vip")

    handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])
    result = handler.handle_event(make_event("/admin/vip status", user_id="admin"))

    text = reply_texts(result)[0]
    assert "VIP 隊列狀態" in text
    assert "啟用" in text
    assert "1" in text


def test_admin_vip_toggle_updates_setting(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    handler = LineBotHandler(queue_manager=QueueManager(db), admin_ids=["admin"])

    result = handler.handle_event(make_event("/admin/vip toggle off", user_id="admin"))

    assert "VIP" in reply_texts(result)[0]
    assert db.is_vip_enabled() is False



def test_admin_vip_clear_removes_active_vip_entries(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    for user_id in ("vip_alice", "vip_bob"):
        db.add_vip_purchase(user_id, platform="line", coffee_id=f"coffee_{user_id}")
    with db._connection() as conn:
        conn.execute("UPDATE vip_purchases SET verified = 1")
        conn.commit()

    qm = QueueManager(db)
    qm.join("vip_alice", "vip")
    qm.join("vip_bob", "vip")
    handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

    result = handler.handle_event(make_event("/admin/vip clear", user_id="admin"))

    text = reply_texts(result)[0]
    assert "2" in text
    assert len(db.get_vip_queue()) == 0



def test_admin_history_returns_user_events(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    qm = QueueManager(db)
    qm.join("alice", "regular")
    qm.cancel("alice")
    handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

    result = handler.handle_event(make_event("/admin/history alice", user_id="admin"))

    text = reply_texts(result)[0]
    assert "alice" in text
    assert "join" in text
    assert "cancel" in text



def test_admin_export_returns_short_csv_preview(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    qm = QueueManager(db)
    qm.join("alice", "regular")
    handler = LineBotHandler(queue_manager=qm, admin_ids=["admin"])

    result = handler.handle_event(make_event("/admin/export", user_id="admin"))

    text = reply_texts(result)[0]
    assert "CSV" in text
    assert "user_id,queue_type" in text
    assert "alice" in text



def test_reply_falls_back_to_dict_when_line_sdk_missing(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    handler = LineBotHandler(queue_manager=QueueManager(db))

    result = handler._reply("token", "hello")

    assert result == [{"replyToken": "token", "text": "hello"}]
