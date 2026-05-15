"""Config-driven special serve rules shared by LINE and Telegram admin flows."""

from __future__ import annotations

from core.queue_manager import QueueManager


def normalize_special_serve_rules(raw: dict | None) -> dict:
    """Normalize config payload for special serve rules."""
    defaults = {
        "enabled": False,
        "match_field": "display_name",
        "skip_message": "警告此人會哭😭，已為您跳過",
        "no_next_reply": "警告此人會哭😭，我想幫你跳過，但後面沒人啦\n裝忙一下唄",
        "admins": {},
    }
    if not isinstance(raw, dict):
        return defaults

    admins: dict[str, dict[str, list[str]]] = {}
    for admin_id, rule in (raw.get("admins") or {}).items():
        normalized_admin_id = str(admin_id).strip()
        if not normalized_admin_id or not isinstance(rule, dict):
            continue
        targets = []
        for target in rule.get("targets") or []:
            normalized_target = str(target).strip()
            if normalized_target:
                targets.append(normalized_target)
        if targets:
            admins[normalized_admin_id] = {"targets": targets}

    return {
        "enabled": bool(raw.get("enabled", defaults["enabled"])),
        "match_field": str(raw.get("match_field", defaults["match_field"])).strip() or defaults["match_field"],
        "skip_message": str(raw.get("skip_message", defaults["skip_message"])).strip() or defaults["skip_message"],
        "no_next_reply": str(raw.get("no_next_reply", defaults["no_next_reply"])).strip() or defaults["no_next_reply"],
        "admins": admins,
    }


def resolve_special_serve_decision(*, rules: dict | None, queue_manager: QueueManager, admin_user_id: str) -> dict:
    """Return a platform-agnostic decision for special serve behavior."""
    normalized = normalize_special_serve_rules(rules)
    if not normalized["enabled"]:
        return {"status": "disabled", "target_user_id": None, "admin_message": None}
    if normalized["match_field"] != "display_name":
        return {"status": "disabled", "target_user_id": None, "admin_message": None}

    admin_rule = normalized["admins"].get(str(admin_user_id).strip())
    if not admin_rule:
        return {"status": "disabled", "target_user_id": None, "admin_message": None}

    queue_entries = queue_manager.get_queue()
    if not queue_entries:
        return {"status": "disabled", "target_user_id": None, "admin_message": None}

    head_profile = queue_manager.db.get_user_profile(queue_entries[0].user_id)
    head_display_name = (head_profile.display_name if head_profile else "").strip()
    if head_display_name not in admin_rule["targets"]:
        return {"status": "disabled", "target_user_id": None, "admin_message": None}

    if len(queue_entries) < 2:
        return {
            "status": "block",
            "target_user_id": None,
            "admin_message": normalized["no_next_reply"],
        }

    return {
        "status": "skip_to_next",
        "target_user_id": queue_entries[1].user_id,
        "admin_message": normalized["skip_message"],
    }
