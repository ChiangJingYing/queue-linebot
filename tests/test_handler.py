"""Handler tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from bot.handler import LineBotHandler
from core.queue_manager import QueueManager
from core.database import DatabaseManager
from services.vip_service import VipService


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
    qm = QueueManager(db)
    qm.register_name("alice", "Alice", location="A-1")
    handler = LineBotHandler(queue_manager=qm)

    result = handler.handle_event(make_event("/join", user_id="alice"))

    assert "加入隊列成功" in reply_texts(result)[0]
    assert [entry.user_id for entry in handler.queue_manager.get_queue()] == ["alice"]



def test_handle_status_shows_people_ahead_for_current_user_and_hides_vip(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler-status.db"))
    qm = QueueManager(db)
    qm.register_name("alice", "Alice", location="A-1")
    qm.register_name("bob", "Bob", location="A-2")
    qm.register_name("charlie", "Charlie", location="A-3")
    qm.join("alice", "regular")
    qm.join("bob", "regular")
    qm.join("charlie", "regular")
    handler = LineBotHandler(queue_manager=qm)

    result = handler.handle_event(make_event("/status", user_id="charlie"))

    text = reply_texts(result)[0]
    assert "你前面還有 2 人" in text
    assert "VIP" not in text



def test_handle_status_when_user_not_in_queue_shows_total_queue_count(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler-status-empty.db"))
    qm = QueueManager(db)
    qm.register_name("alice", "Alice", location="A-1")
    qm.register_name("bob", "Bob", location="A-2")
    qm.join("alice", "regular")
    qm.join("bob", "regular")
    handler = LineBotHandler(queue_manager=qm)

    result = handler.handle_event(make_event("/status", user_id="charlie"))

    text = reply_texts(result)[0]
    assert "目前有 2 人在排隊中" in text
    assert "VIP" not in text



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


def test_cancel_requires_double_confirmation_when_queue_closed(tmp_path):
    db = DatabaseManager(str(tmp_path / "cancel-closed.db"))
    qm = QueueManager(db)
    qm.register_name("alice", "Alice", location="A-1")
    qm.join("alice", "regular")
    qm.set_queue_enabled(False)
    handler = LineBotHandler(queue_manager=qm)

    first = handler.handle_event(make_event("/cancel", user_id="alice", reply_token="r1"))

    assert "當前隊列已關閉，確定要放棄嗎" in first[0]["text"]
    first_qr = first[0].get("quickReply", {}).get("items", [])
    assert len(first_qr) == 2
    assert first_qr[0]["action"]["label"] == "確認放棄"
    assert first_qr[0]["action"]["text"] == "確認放棄"
    assert first_qr[1]["action"]["label"] == "我在努力看看"
    assert first_qr[1]["action"]["text"] == "取消放棄"
    assert qm.get_user_position("alice") == 1

    second = handler.handle_event(make_event("確認放棄", user_id="alice", reply_token="r2"))

    assert second[0]["text"] == "您確定要放棄嗎？"
    second_qr = second[0].get("quickReply", {}).get("items", [])
    assert len(second_qr) == 2
    assert second_qr[0]["action"]["label"] == "確認放棄"
    assert second_qr[0]["action"]["text"] == "確認放棄"
    assert second_qr[1]["action"]["label"] == "我在努力看看"
    assert second_qr[1]["action"]["text"] == "取消放棄"
    assert qm.get_user_position("alice") == 1

    final = handler.handle_event(make_event("確認放棄", user_id="alice", reply_token="r3"))

    assert "已取消排隊" in final[0]["text"]
    assert qm.get_user_position("alice") is None


def test_cancel_closed_queue_can_be_aborted_without_leaving_queue(tmp_path):
    db = DatabaseManager(str(tmp_path / "cancel-abort.db"))
    qm = QueueManager(db)
    qm.register_name("alice", "Alice", location="A-1")
    qm.join("alice", "regular")
    qm.set_queue_enabled(False)
    handler = LineBotHandler(queue_manager=qm)

    handler.handle_event(make_event("/cancel", user_id="alice", reply_token="r1"))
    abort_reply = handler.handle_event(make_event("取消放棄", user_id="alice", reply_token="r2"))

    assert abort_reply[0]["text"] == "好的，已取消放棄"
    assert qm.get_user_position("alice") == 1


def test_cancel_when_queue_open_still_cancels_immediately(tmp_path):
    db = DatabaseManager(str(tmp_path / "cancel-open.db"))
    qm = QueueManager(db)
    qm.register_name("alice", "Alice", location="A-1")
    qm.join("alice", "regular")
    handler = LineBotHandler(queue_manager=qm)

    result = handler.handle_event(make_event("/cancel", user_id="alice"))

    assert "已取消排隊" in result[0]["text"]
    assert qm.get_user_position("alice") is None



def test_handle_history_returns_empty_message_when_no_history(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    handler = LineBotHandler(queue_manager=QueueManager(db))

    result = handler.handle_event(make_event("/history", user_id="alice"))

    assert reply_texts(result)[0] == "查無排隊歷史紀錄。"



def test_handle_join_vip_short_form_joins_current_user(tmp_path):
    db = DatabaseManager(str(tmp_path / "handler.db"))
    QueueManager(db).register_name("alice", "Alice", location="A-1")
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


def test_register_enters_pending_mode_and_next_message_sets_name(tmp_path):
    db = DatabaseManager(str(tmp_path / "register.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(
        queue_manager=qm,
        vip_service=VipService(db),
        admin_ids=["admin"],
        location_options={"A": ["1", "2"], "B": ["1"]},
    )

    reply = handler.handle_event(make_event("/register", user_id="alice", reply_token="r1"))
    assert "請輸入你的學號" in reply[0]["text"]

    reply2 = handler.handle_event(make_event("王小明", user_id="alice", reply_token="r2"))
    assert "請選擇您在第幾排座位" in reply2[0]["text"]
    qr2 = reply2[0].get("quickReply", {})
    assert isinstance(qr2, dict) and "items" in qr2
    assert len(qr2["items"]) == 2
    assert qr2["items"][0]["action"]["label"] == "A"
    assert qr2["items"][1]["action"]["label"] == "B"

    reply3 = handler.handle_event(make_event("A", user_id="alice", reply_token="r3"))
    assert "請選擇您的座位（A-?）" in reply3[0]["text"]
    qr3 = reply3[0].get("quickReply", {})
    assert isinstance(qr3, dict) and "items" in qr3
    assert len(qr3["items"]) == 2
    assert qr3["items"][0]["action"]["label"] == "1"
    assert qr3["items"][1]["action"]["label"] == "2"

    reply4 = handler.handle_event(make_event("1", user_id="alice", reply_token="r4"))
    assert reply4[0]["text"] == "✅ 已更新學號：王小明\n位置：A-1"
    assert db.get_display_name("alice") == "王小明（A-1）"


def test_register_rejects_inline_args(tmp_path):
    db = DatabaseManager(str(tmp_path / "register-inline.db"))
    handler = LineBotHandler(queue_manager=QueueManager(db), vip_service=VipService(db), admin_ids=["admin"])

    reply = handler.handle_event(make_event("/register 王小明", user_id="alice"))

    assert "/register 不接受參數" in reply[0]["text"]


def test_admin_apply_subcommands_require_admin(tmp_path):
    db = DatabaseManager(str(tmp_path / "admin-apply.db"))
    handler = LineBotHandler(queue_manager=QueueManager(db), vip_service=VipService(db), admin_ids=["admin"])

    reply = handler.handle_event(make_event("/admin/apply list", user_id="alice"))

    assert "未授權" in reply[0]["text"]


def test_help_is_admin_only(tmp_path):
    db = DatabaseManager(str(tmp_path / "help.db"))
    handler = LineBotHandler(queue_manager=QueueManager(db), vip_service=VipService(db), admin_ids=["admin"])

    denied = handler.handle_event(make_event("/help", user_id="alice"))
    allowed = handler.handle_event(make_event("/help", user_id="admin"))

    assert "未授權" in denied[0]["text"]
    assert "管理員指令" in allowed[0]["text"]


def test_admin_clear_clears_queue_and_registered_profiles(tmp_path):
    db = DatabaseManager(str(tmp_path / "clear.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"])

    qm.join("alice", "regular")
    qm.register_name("alice", "王小明")

    reply = handler.handle_event(make_event("/admin/clear", user_id="admin"))

    assert "清除 1 筆使用者資料" in reply[0]["text"]
    assert db.get_all_queue() == []
    assert db.get_user_profile("alice") is None


def test_admin_clear_keeps_existing_admin_profiles_and_clears_their_dashboard_fields(tmp_path):
    db = DatabaseManager(str(tmp_path / "clear-admins.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["config_admin"])

    qm.register_name("config_admin", "靜態管理員", location="A-1")
    db.upsert_user_profile("config_admin", "靜態管理員", location="A-1", role="admin")

    qm.register_name("dynamic_admin", "動態管理員", location="B-1")
    db.upsert_user_profile("dynamic_admin", "動態管理員", location="B-1", role="admin")

    reply = handler.handle_event(make_event("/admin/clear", user_id="config_admin"))

    config_admin = db.get_user_profile("config_admin")
    dynamic_admin = db.get_user_profile("dynamic_admin")

    assert "保留 2 筆 admin 資料" in reply[0]["text"]
    assert config_admin is not None
    assert config_admin.role == "admin"
    assert config_admin.display_name == ""
    assert config_admin.location == ""
    assert dynamic_admin is not None
    assert dynamic_admin.role == "admin"
    assert dynamic_admin.display_name == ""
    assert dynamic_admin.location == ""


def test_admin_clear_keeps_all_admin_roles_but_clears_dashboard_registration_fields(tmp_path):
    db = DatabaseManager(str(tmp_path / "clear-admin-dashboard.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["config_admin"])

    qm.register_name("config_admin", "靜態管理員", location="A-1")
    db.upsert_user_profile("config_admin", "靜態管理員", location="A-1", verified=True, role="admin")

    qm.register_name("dynamic_admin", "動態管理員", location="B-1")
    db.upsert_user_profile("dynamic_admin", "動態管理員", location="B-1", verified=True, role="admin")

    reply = handler.handle_event(make_event("/admin/clear", user_id="config_admin"))

    config_kept = db.get_user_profile("config_admin")
    dynamic_kept = db.get_user_profile("dynamic_admin")
    assert "保留 2 筆 admin 資料" in reply[0]["text"]

    assert config_kept is not None
    assert config_kept.role == "admin"
    assert config_kept.display_name == ""
    assert config_kept.location == ""
    assert config_kept.verified == 0

    assert dynamic_kept is not None
    assert dynamic_kept.role == "admin"
    assert dynamic_kept.display_name == ""
    assert dynamic_kept.location == ""
    assert dynamic_kept.verified == 0


def test_admin_serve_next_uses_display_name_and_location(tmp_path):
    db = DatabaseManager(str(tmp_path / "serve-next.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"])

    qm.register_name("alice", "B12345678", location="A-1")
    qm.join("alice", "regular")

    reply = handler.handle_event(make_event("/admin/serve", user_id="admin"))

    assert reply[0]["text"] == "✅ 已叫號：B12345678（A-1）"



def test_admin_serve_next_is_blocked_during_cooldown(tmp_path):
    db = DatabaseManager(str(tmp_path / "serve-next-cooldown.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"], admin_serve_cooldown_seconds=3)

    qm.register_name("alice", "B12345678", location="A-1")
    qm.register_name("bob", "B23456789", location="A-2")
    qm.join("alice", "regular")
    qm.join("bob", "regular")

    handler._admin_serve_cooldown_clock = lambda: 100.0

    first = handler.handle_event(make_event("/admin/serve", user_id="admin"))
    handler._admin_serve_cooldown_clock = lambda: 101.0
    second = handler.handle_event(make_event("/admin/serve", user_id="admin"))

    assert first[0]["text"] == "✅ 已叫號：B12345678（A-1）"
    assert second[0]["text"] == "⚠️ 剛剛已叫號：B12345678（A-1），請稍候再試，避免重複叫號。"
    assert [entry.user_id for entry in qm.get_queue()] == ["bob"]



def test_admin_serve_specific_shares_same_cooldown_guard(tmp_path):
    db = DatabaseManager(str(tmp_path / "serve-specific-cooldown.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"], admin_serve_cooldown_seconds=3)

    qm.register_name("alice", "B12345678", location="A-1")
    qm.register_name("bob", "B23456789", location="A-2")
    qm.join("alice", "regular")
    qm.join("bob", "regular")

    handler._admin_serve_cooldown_clock = lambda: 200.0

    first = handler.handle_event(make_event("/admin/serve", user_id="admin"))
    handler._admin_serve_cooldown_clock = lambda: 201.0
    second = handler.handle_event(make_event("/admin/serve bob", user_id="admin"))

    assert first[0]["text"] == "✅ 已叫號：B12345678（A-1）"
    assert second[0]["text"] == "⚠️ 剛剛已叫號：B12345678（A-1），請稍候再試，避免重複叫號。"
    assert [entry.user_id for entry in qm.get_queue()] == ["bob"]



def test_admin_serve_is_blocked_while_another_serve_is_in_progress(tmp_path):
    db = DatabaseManager(str(tmp_path / "serve-lock.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"])

    qm.register_name("alice", "B12345678", location="A-1")
    qm.join("alice", "regular")

    handler._admin_serve_lock.acquire()
    try:
        reply = handler.handle_event(make_event("/admin/serve", user_id="admin"))
    finally:
        handler._admin_serve_lock.release()

    assert reply[0]["text"] == "⚠️ 叫號進行中，請勿重複操作。"
    assert [entry.user_id for entry in qm.get_queue()] == ["alice"]



def test_admin_serve_cooldown_expires_and_next_serve_succeeds(tmp_path):
    db = DatabaseManager(str(tmp_path / "serve-cooldown-expire.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"], admin_serve_cooldown_seconds=3)

    qm.register_name("alice", "B12345678", location="A-1")
    qm.register_name("bob", "B23456789", location="A-2")
    qm.join("alice", "regular")
    qm.join("bob", "regular")

    handler._admin_serve_cooldown_clock = lambda: 300.0
    first = handler.handle_event(make_event("/admin/serve", user_id="admin"))

    handler._admin_serve_cooldown_clock = lambda: 304.0
    second = handler.handle_event(make_event("/admin/serve", user_id="admin"))

    assert first[0]["text"] == "✅ 已叫號：B12345678（A-1）"
    assert second[0]["text"] == "✅ 已叫號：B23456789（A-2）"
    assert qm.get_queue() == []



def test_admin_serve_failure_does_not_start_cooldown(tmp_path):
    db = DatabaseManager(str(tmp_path / "serve-failure-no-cooldown.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"], admin_serve_cooldown_seconds=3)

    handler._admin_serve_cooldown_clock = lambda: 400.0
    first = handler.handle_event(make_event("/admin/serve", user_id="admin"))

    qm.register_name("alice", "B12345678", location="A-1")
    qm.join("alice", "regular")

    handler._admin_serve_cooldown_clock = lambda: 401.0
    second = handler.handle_event(make_event("/admin/serve", user_id="admin"))

    assert first[0]["text"] == "❌ 錯誤：目前隊列是空的。"
    assert second[0]["text"] == "✅ 已叫號：B12345678（A-1）"



class BlockingQueueManager(QueueManager):
    def __init__(self, db, gate):
        super().__init__(db)
        self.gate = gate

    def serve_next(self) -> dict:
        self.gate.wait(timeout=2)
        return super().serve_next()



def test_admin_serve_concurrent_requests_only_serve_one_user(tmp_path):
    import threading

    db = DatabaseManager(str(tmp_path / "serve-concurrent.db"))
    gate = threading.Event()
    qm = BlockingQueueManager(db, gate)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"], admin_serve_cooldown_seconds=0)

    qm.register_name("alice", "B12345678", location="A-1")
    qm.register_name("bob", "B23456789", location="A-2")
    qm.join("alice", "regular")
    qm.join("bob", "regular")

    replies = []

    def run_first():
        replies.append(("first", handler.handle_event(make_event("/admin/serve", user_id="admin", reply_token="r1"))))

    t1 = threading.Thread(target=run_first)
    t1.start()

    # Let the first request enter serve_next() and hold the lock.
    import time
    time.sleep(0.05)

    second = handler.handle_event(make_event("/admin/serve", user_id="admin", reply_token="r2"))
    gate.set()
    t1.join(timeout=2)

    first_reply = dict(replies)["first"]
    assert first_reply[0]["text"] == "✅ 已叫號：B12345678（A-1）"
    assert second[0]["text"] == "⚠️ 叫號進行中，請勿重複操作。"
    assert [entry.user_id for entry in qm.get_queue()] == ["bob"]



def test_admin_serve_specific_uses_display_name_and_location(tmp_path):
    db = DatabaseManager(str(tmp_path / "serve-specific.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"])

    qm.register_name("alice", "B12345678", location="A-1")
    qm.join("alice", "regular")

    reply = handler.handle_event(make_event("/admin/serve alice", user_id="admin"))

    assert reply[0]["text"] == "✅ 已叫號：B12345678（A-1）"


class FakeAnnouncementService:
    def __init__(self):
        self.calls = []

    def announce_called_guest(self, *, display_name: str):
        self.calls.append(("called_guest", display_name))
        return {
            "status": "ok",
            "text": f"來賓 {display_name} 請準備demo",
            "audioUrl": "/dashboard/audio/fake.mp3",
        }

    def announce_new_order(self, *, text: str):
        self.calls.append(("new_order", text))
        return {
            "status": "ok",
            "text": text,
            "audioUrl": "/dashboard/audio/new-order.mp3",
        }


def test_admin_serve_next_creates_dashboard_announcement_with_display_name(tmp_path):
    db = DatabaseManager(str(tmp_path / "serve-next-announcement.db"))
    qm = QueueManager(db)
    announcement_service = FakeAnnouncementService()
    handler = LineBotHandler(
        queue_manager=qm,
        vip_service=VipService(db),
        admin_ids=["admin"],
        announcement_service=announcement_service,
    )

    qm.register_name("alice", "110316888", location="A-1")
    qm.join("alice", "regular")

    reply = handler.handle_event(make_event("/admin/serve", user_id="admin"))

    assert reply[0]["text"] == "✅ 已叫號：110316888（A-1）"
    assert announcement_service.calls == [("called_guest", "110316888")]


def test_admin_serve_specific_creates_dashboard_announcement_with_display_name(tmp_path):
    db = DatabaseManager(str(tmp_path / "serve-specific-announcement.db"))
    qm = QueueManager(db)
    announcement_service = FakeAnnouncementService()
    handler = LineBotHandler(
        queue_manager=qm,
        vip_service=VipService(db),
        admin_ids=["admin"],
        announcement_service=announcement_service,
    )

    qm.register_name("alice", "110316888", location="A-1")
    qm.join("alice", "regular")

    reply = handler.handle_event(make_event("/admin/serve alice", user_id="admin"))

    assert reply[0]["text"] == "✅ 已叫號：110316888（A-1）"
    assert announcement_service.calls == [("called_guest", "110316888")]


def test_join_after_idle_empty_queue_announces_new_order(tmp_path):
    db = DatabaseManager(str(tmp_path / "idle-new-order.db"))
    qm = QueueManager(db)
    announcement_service = FakeAnnouncementService()
    handler = LineBotHandler(
        queue_manager=qm,
        vip_service=VipService(db),
        announcement_service=announcement_service,
        new_order_idle_seconds=300,
        new_order_announcement_text="您有新訂單",
    )

    qm.register_name("alice", "Alice", location="A-1")
    handler._new_order_last_joined_at = datetime.now() - timedelta(minutes=6)

    reply = handler.handle_event(make_event("/join", user_id="alice"))

    assert "加入隊列成功" in reply[0]["text"]
    assert announcement_service.calls == [("new_order", "您有新訂單")]



def test_join_after_admin_clear_announces_new_order_immediately(tmp_path):
    db = DatabaseManager(str(tmp_path / "clear-new-order.db"))
    qm = QueueManager(db)
    announcement_service = FakeAnnouncementService()
    handler = LineBotHandler(
        queue_manager=qm,
        vip_service=VipService(db),
        admin_ids=["admin"],
        announcement_service=announcement_service,
        new_order_idle_seconds=300,
        new_order_announcement_text="您有新訂單",
    )

    qm.register_name("alice", "Alice", location="A-1")
    qm.join("someone", "regular")

    clear_reply = handler.handle_event(make_event("/admin/clear", user_id="admin"))
    qm.register_name("alice", "Alice", location="A-1")
    join_reply = handler.handle_event(make_event("/join", user_id="alice"))

    assert "已清空全部隊列" in clear_reply[0]["text"]
    assert "加入隊列成功" in join_reply[0]["text"]
    assert announcement_service.calls == [("new_order", "您有新訂單")]


def test_dashboard_announcement_formats_digit_only_id_for_tts(tmp_path):
    from services.dashboard_announcement import DashboardAnnouncementService

    class CapturingTTS:
        def __init__(self):
            self.calls = []

        def synthesize(self, text: str) -> bytes:
            self.calls.append(text)
            return b""

    tts = CapturingTTS()
    service = DashboardAnnouncementService(root=tmp_path / "announcements", tts_service=tts)

    payload = service.announce_called_guest(display_name="114205")

    assert payload["text"] == "來賓 一一四二零五 請準備demo"
    assert tts.calls == ["來賓 一一四二零五 請準備demo"]


def test_dashboard_announcement_template_can_use_mp3_path(tmp_path):
    from services.dashboard_announcement import DashboardAnnouncementService

    class CapturingTTS:
        def __init__(self):
            self.calls = []

        def synthesize(self, text: str) -> bytes:
            self.calls.append(text)
            return b"generated-audio"

    mp3_path = tmp_path / "custom-audio.mp3"
    mp3_path.write_bytes(b"custom-mp3")
    tts = CapturingTTS()
    service = DashboardAnnouncementService(
        root=tmp_path / "announcements",
        tts_service=tts,
        announcement_template=str(mp3_path),
    )

    payload = service.announce_called_guest(display_name="114205")

    assert payload["text"] == "來賓 一一四二零五 請準備demo"
    assert payload["audioUrl"].endswith("/custom-audio.mp3")
    assert tts.calls == []


def test_new_order_announcement_can_use_mp3_path(tmp_path):
    from services.dashboard_announcement import DashboardAnnouncementService

    class CapturingTTS:
        def __init__(self):
            self.calls = []

        def synthesize(self, text: str) -> bytes:
            self.calls.append(text)
            return b"generated-audio"

    mp3_path = tmp_path / "new-order.mp3"
    mp3_path.write_bytes(b"new-order-mp3")
    tts = CapturingTTS()
    service = DashboardAnnouncementService(
        root=tmp_path / "announcements",
        tts_service=tts,
        new_order_announcement_text=str(mp3_path),
    )

    payload = service.announce_new_order()

    assert payload["text"] == "您有新訂單"
    assert payload["audioUrl"].endswith("/new-order.mp3")
    assert tts.calls == []


def test_admin_ping_next_user(tmp_path):
    db = DatabaseManager(str(tmp_path / "ping.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"])

    qm.register_name("alice", "王小明")
    qm.join("alice", "regular")

    reply = handler.handle_event(make_event("/admin/ping", user_id="admin"))

    assert "已提醒 王小明（alice）" in reply[0]["text"]
