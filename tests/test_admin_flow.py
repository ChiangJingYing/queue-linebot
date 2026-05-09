from __future__ import annotations

from datetime import datetime, timedelta

from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.admin_flow import (
    build_admin_export_preview,
    build_admin_history,
    build_admin_stats,
    build_admin_status,
    clear_vip_queue,
    get_admin_join_status,
    release_user,
    set_admin_join_enabled,
    toggle_admin_join,
    toggle_vip,
)
from services.vip_service import VipService


def test_build_admin_status_groups_regular_and_vip_entries(tmp_path):
    db = DatabaseManager(str(tmp_path / "admin-flow-status.db"))
    db.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
    db.upsert_user_profile("bob", "B23456789", location="A-2", verified=False, role="user")
    db.add_vip_purchase("bob", platform="line", coffee_id="coffee_1", verified=True)

    qm = QueueManager(db)
    qm.join("alice", "regular")
    qm.join("bob", "vip")

    payload = build_admin_status(queue_manager=qm)

    assert payload["regular_count"] == 1
    assert payload["vip_count"] == 1
    assert payload["vip_enabled"] is True
    assert payload["regular_entries"][0]["display_name"] == "B12345678（A-1）"
    assert payload["regular_entries"][0]["verified"] is True
    assert payload["vip_entries"][0]["display_name"] == "B23456789（A-2）"
    assert payload["vip_entries"][0]["verified"] is False


def test_build_admin_stats_formats_metrics(tmp_path):
    db = DatabaseManager(str(tmp_path / "admin-flow-stats.db"))
    db.add_vip_purchase("vip_alice", platform="line", coffee_id="coffee_1", verified=True)

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

    payload = build_admin_stats(queue_manager=qm)

    assert payload["joined_today"] == 3
    assert payload["served_count"] == 1
    assert payload["skipped_count"] == 1
    assert payload["vip"]["active_count"] == 1


def test_build_admin_history_and_export_preview_match_existing_wording(tmp_path):
    db = DatabaseManager(str(tmp_path / "admin-flow-history.db"))
    qm = QueueManager(db)
    qm.join("alice", "regular")
    qm.cancel("alice")

    history_payload = build_admin_history(queue_manager=qm, user_id="alice")
    export_payload = build_admin_export_preview(queue_manager=qm)

    assert history_payload["user_id"] == "alice"
    assert history_payload["history"][0]["event_type"] == "cancel"
    assert any(item["event_type"] == "join" and item["queue_type"] == "regular" for item in history_payload["history"])
    assert export_payload["total"] >= 1
    assert export_payload["preview"].startswith("user_id,")


def test_build_admin_history_returns_none_when_missing(tmp_path):
    db = DatabaseManager(str(tmp_path / "admin-flow-history-missing.db"))
    qm = QueueManager(db)

    assert build_admin_history(queue_manager=qm, user_id="ghost") is None


def test_admin_join_operations_go_through_shared_service(tmp_path):
    db = DatabaseManager(str(tmp_path / "admin-flow-join.db"))
    qm = QueueManager(db)

    assert get_admin_join_status(queue_manager=qm) == {"enabled": True}
    assert set_admin_join_enabled(queue_manager=qm, enabled=False) == {"enabled": False}
    assert get_admin_join_status(queue_manager=qm) == {"enabled": False}
    assert toggle_admin_join(queue_manager=qm) == {"enabled": True}


def test_toggle_vip_and_clear_vip_queue_go_through_shared_service(tmp_path):
    db = DatabaseManager(str(tmp_path / "admin-flow-vip.db"))
    db.add_vip_purchase("bob", platform="line", coffee_id="coffee_1", verified=True)
    qm = QueueManager(db)
    qm.join("bob", "vip")
    vip_service = VipService(db)

    assert toggle_vip(vip_service=vip_service, enabled=False) == {"vip_enabled": False, "message": "VIP 隊列已停用"}
    clear_result = clear_vip_queue(queue_manager=qm)
    assert clear_result["status"] == "cleared"
    assert clear_result["removed_count"] == 1
    assert clear_result["removed_users"] == ["bob"]


def test_release_user_by_location_success_returns_user_id_and_display_name(tmp_path):
    db = DatabaseManager(str(tmp_path / "release-user-success.db"))
    db.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
    qm = QueueManager(db)
    qm.join("alice", "regular")
    qm.serve_next()

    result = release_user(queue_manager=qm, location="A-1")

    assert result["status"] == "released"
    assert result["user_id"] == "alice"
    assert result["display_name"] == "B12345678（A-1）"


def test_release_user_by_location_not_registered_returns_error(tmp_path):
    db = DatabaseManager(str(tmp_path / "release-user-missing.db"))
    qm = QueueManager(db)

    result = release_user(queue_manager=qm, location="Z-9")

    assert result["status"] == "error"
    assert "Z-9" in result["message"]


def test_release_user_by_location_no_queue_entry_still_succeeds(tmp_path):
    db = DatabaseManager(str(tmp_path / "release-user-no-entry.db"))
    db.upsert_user_profile("alice", "B12345678", location="A-1", verified=True, role="user")
    qm = QueueManager(db)

    result = release_user(queue_manager=qm, location="A-1")

    assert result["status"] == "released"
    assert result["user_id"] == "alice"
    assert result["queue_number"] is None
