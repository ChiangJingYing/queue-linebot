from __future__ import annotations


def _profile_label(queue_manager, user_id: str) -> str:
    return queue_manager.db.get_display_name(user_id)


def _profile_verified(queue_manager, user_id: str) -> bool:
    profile = queue_manager.db.get_user_profile(user_id)
    return bool(profile and profile.verified)


def build_admin_status(*, queue_manager) -> dict:
    status = queue_manager.get_status()
    entries = queue_manager.get_queue()

    regular_entries: list[dict] = []
    vip_entries: list[dict] = []

    for entry in entries:
        item = {
            "user_id": entry.user_id,
            "display_name": _profile_label(queue_manager, entry.user_id),
            "verified": _profile_verified(queue_manager, entry.user_id),
            "join_time": entry.join_time,
            "queue_type": entry.queue_type,
        }
        if entry.queue_type == "vip":
            vip_entries.append(item)
        else:
            regular_entries.append(item)

    return {
        "regular_count": status["regular_count"],
        "vip_count": status["vip_count"],
        "vip_enabled": status["vip_enabled"],
        "regular_entries": regular_entries,
        "vip_entries": vip_entries,
    }


def build_admin_stats(*, queue_manager) -> dict:
    return queue_manager.get_stats()


def build_vip_status(*, vip_service) -> dict:
    return vip_service.get_vip_status()


def toggle_vip(*, vip_service, enabled: bool) -> dict:
    return vip_service.toggle_vip(enabled)


def clear_vip_queue(*, queue_manager) -> dict:
    return queue_manager.clear_vip_queue()


def build_admin_history(*, queue_manager, user_id: str) -> dict | None:
    history = queue_manager.get_user_history(user_id)
    if not history:
        return None
    return {"user_id": user_id, "history": history[:10]}


def build_admin_export_preview(*, queue_manager, limit: int = 200, preview_lines: int = 12, preview_threshold: int = 3500) -> dict:
    csv_data = queue_manager.export_queue_csv(limit=limit)
    lines = csv_data.splitlines()
    total = max(len(lines) - 1, 0)
    is_preview = len(csv_data) > preview_threshold
    return {
        "total": total,
        "csv_data": csv_data,
        "preview": "\n".join(lines[:preview_lines]) if is_preview else csv_data,
        "is_preview": is_preview,
    }


def toggle_admin_join(*, queue_manager) -> dict:
    enabled = not queue_manager.get_queue_enabled()
    queue_manager.set_queue_enabled(enabled)
    return {"enabled": enabled}


def set_admin_join_enabled(*, queue_manager, enabled: bool) -> dict:
    queue_manager.set_queue_enabled(enabled)
    return {"enabled": enabled}


def get_admin_join_status(*, queue_manager) -> dict:
    return {"enabled": queue_manager.get_queue_enabled()}


def ping_user(*, queue_manager, target_id: str | None = None) -> dict:
    return queue_manager.ping_user(target_id)


def clear_all_queue(*, queue_manager, keep_admin_user_ids: set[str]) -> dict:
    return queue_manager.clear_all_queue(keep_admin_user_ids=keep_admin_user_ids)
