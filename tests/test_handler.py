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


def test_admin_serve_specific_uses_display_name_and_location(tmp_path):
    db = DatabaseManager(str(tmp_path / "serve-specific.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"])

    qm.register_name("alice", "B12345678", location="A-1")
    qm.join("alice", "regular")

    reply = handler.handle_event(make_event("/admin/serve alice", user_id="admin"))

    assert reply[0]["text"] == "✅ 已叫號：B12345678（A-1）"


def test_admin_ping_next_user(tmp_path):
    db = DatabaseManager(str(tmp_path / "ping.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(queue_manager=qm, vip_service=VipService(db), admin_ids=["admin"])

    qm.register_name("alice", "王小明")
    qm.join("alice", "regular")

    reply = handler.handle_event(make_event("/admin/ping", user_id="admin"))

    assert "已提醒 王小明（alice）" in reply[0]["text"]
