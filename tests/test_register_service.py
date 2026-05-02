from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.register_service import complete_registration


def test_complete_registration_returns_normalized_success_payload(tmp_path):
    db = DatabaseManager(str(tmp_path / "register-service.db"))
    qm = QueueManager(db)

    outcome = complete_registration(
        queue_manager=qm,
        user_id="alice",
        display_name=" 王小明 ",
        location="A-1",
    )

    assert outcome == {
        "status": "success",
        "display_name": "王小明",
        "location": "A-1",
        "message": "✅ 已更新學號：王小明\n位置：A-1",
        "raw_result": {
            "status": "success",
            "user_id": "alice",
            "display_name": "王小明",
            "location": "A-1",
            "verified": False,
        },
    }


def test_complete_registration_returns_normalized_error_payload(tmp_path):
    db = DatabaseManager(str(tmp_path / "register-service-error.db"))
    qm = QueueManager(db)

    outcome = complete_registration(
        queue_manager=qm,
        user_id="alice",
        display_name="   ",
        location="A-1",
    )

    assert outcome == {
        "status": "error",
        "message": "❌ 錯誤：名稱不可為空白。",
        "raw_result": {
            "status": "error",
            "message": "名稱不可為空白。",
        },
    }
