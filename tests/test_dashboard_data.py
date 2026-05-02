from datetime import datetime, timedelta


ALICE_LOCATION = "1-1"
BOB_LOCATION = "2-1"


def test_dashboard_data_reverts_served_user_to_registered_after_blink_window(client, db_manager):
    db_manager.upsert_user_profile("alice", "B12345678", location=ALICE_LOCATION, role="user")
    entry = db_manager.join_queue("alice", "regular")
    db_manager.serve_queue("alice")

    old_join = (datetime.now() - timedelta(minutes=10)).isoformat()
    old_served = (datetime.now() - timedelta(seconds=120)).isoformat()
    with db_manager._connection() as conn:
        conn.execute(
            "UPDATE queues SET join_time = ?, served_time = ? WHERE id = ?",
            (old_join, old_served, entry.id or 1),
        )
        conn.commit()

    response = client.get("/dashboard/data")
    assert response.status_code == 200
    payload = response.json()

    row, col = ALICE_LOCATION.split("-")
    cell = payload["grid"][row][col]
    assert cell["status"] == "registered"
    assert cell.get("recently_served") is False


def test_dashboard_data_keeps_recent_served_user_blinking(client, db_manager):
    db_manager.upsert_user_profile("alice", "B12345678", location=ALICE_LOCATION, role="user")
    db_manager.join_queue("alice", "regular")
    db_manager.serve_queue("alice")

    response = client.get("/dashboard/data")
    assert response.status_code == 200
    payload = response.json()

    row, col = ALICE_LOCATION.split("-")
    cell = payload["grid"][row][col]
    assert cell["status"] == "served"
    assert cell.get("recently_served") is True


def test_dashboard_data_includes_active_queue_list(client, db_manager):
    db_manager.upsert_user_profile("alice", "B12345678", location=ALICE_LOCATION, role="user")
    db_manager.upsert_user_profile("bob", "B87654321", location=BOB_LOCATION, role="user")
    db_manager.join_queue("alice", "regular")
    db_manager.join_queue("bob", "vip")

    response = client.get("/dashboard/data")
    assert response.status_code == 200
    payload = response.json()

    active_queue = payload["active_queue"]
    assert len(active_queue) == 2
    assert active_queue[0]["user_id"] == "alice"
    assert active_queue[0]["display_name"] == "B12345678"
    assert active_queue[0]["location"] == ALICE_LOCATION
    assert active_queue[1]["user_id"] == "bob"
    assert active_queue[1]["queue_type"] == "vip"


def test_dashboard_data_formats_times_in_utc_plus_8(client, db_manager):
    db_manager.upsert_user_profile("alice", "B12345678", location=ALICE_LOCATION, role="user")
    entry = db_manager.join_queue("alice", "regular")
    with db_manager._connection() as conn:
        conn.execute(
            "UPDATE queues SET join_time = ? WHERE id = ?",
            ("2026-04-29T06:30:00+00:00", entry.id or 1),
        )
        conn.commit()

    response = client.get("/dashboard/data")
    assert response.status_code == 200
    payload = response.json()

    assert payload["active_queue"][0]["join_time"] == "2026-04-29 14:30"
