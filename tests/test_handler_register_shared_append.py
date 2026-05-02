from bot.handler import LineBotHandler
from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.vip_service import VipService
from tests.test_handler import make_event


def test_register_invalid_group_reprompts_same_choices(tmp_path):
    db = DatabaseManager(str(tmp_path / "register-invalid-group.db"))
    qm = QueueManager(db)
    handler = LineBotHandler(
        queue_manager=qm,
        vip_service=VipService(db),
        admin_ids=["admin"],
        location_options={"A": ["1", "2"], "B": ["1"]},
    )

    handler.handle_event(make_event("/register", user_id="alice", reply_token="r1"))
    handler.handle_event(make_event("王小明", user_id="alice", reply_token="r2"))
    reply = handler.handle_event(make_event("C", user_id="alice", reply_token="r3"))

    assert reply[0]["text"] == "無效的位置，請從以下選擇：A、B"
    qr = reply[0].get("quickReply", {})
    assert isinstance(qr, dict) and "items" in qr
    assert [item["action"]["label"] for item in qr["items"]] == ["A", "B"]
