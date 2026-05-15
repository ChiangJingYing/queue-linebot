from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.special_serve_rules import (
    normalize_special_serve_rules,
    resolve_special_serve_decision,
)


def test_normalize_special_serve_rules_returns_disabled_defaults():
    normalized = normalize_special_serve_rules(None)

    assert normalized["enabled"] is False
    assert normalized["match_field"] == "display_name"
    assert normalized["admins"] == {}


def test_normalize_special_serve_rules_keeps_multiple_targets():
    normalized = normalize_special_serve_rules(
        {
            "enabled": True,
            "admins": {
                "admin_a": {"targets": ["114106135", "114106102"]},
                "admin_b": {"targets": ["  114106999  "]},
            },
        }
    )

    assert normalized["enabled"] is True
    assert normalized["admins"] == {
        "admin_a": {"targets": ["114106135", "114106102"]},
        "admin_b": {"targets": ["114106999"]},
    }


def test_resolve_special_serve_decision_returns_skip_to_next_for_matching_admin_and_target(tmp_path):
    db = DatabaseManager(str(tmp_path / "special-serve-skip.db"))
    qm = QueueManager(db)
    qm.register_name("target_user", "114106135", location="A-1")
    qm.register_name("next_user", "114106999", location="A-2")
    qm.join("target_user", "regular")
    qm.join("next_user", "regular")

    decision = resolve_special_serve_decision(
        rules=normalize_special_serve_rules(
            {
                "enabled": True,
                "skip_message": "skip-msg",
                "admins": {"admin_a": {"targets": ["114106135"]}},
            }
        ),
        queue_manager=qm,
        admin_user_id="admin_a",
    )

    assert decision == {
        "status": "skip_to_next",
        "target_user_id": "next_user",
        "admin_message": "skip-msg",
    }


def test_resolve_special_serve_decision_returns_block_when_only_target_is_waiting(tmp_path):
    db = DatabaseManager(str(tmp_path / "special-serve-block.db"))
    qm = QueueManager(db)
    qm.register_name("target_user", "114106135", location="A-1")
    qm.join("target_user", "regular")

    decision = resolve_special_serve_decision(
        rules=normalize_special_serve_rules(
            {
                "enabled": True,
                "no_next_reply": "busy-msg",
                "admins": {"admin_a": {"targets": ["114106135"]}},
            }
        ),
        queue_manager=qm,
        admin_user_id="admin_a",
    )

    assert decision == {
        "status": "block",
        "target_user_id": None,
        "admin_message": "busy-msg",
    }
