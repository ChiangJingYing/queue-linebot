from __future__ import annotations

from core.queue_manager import QueueManager


def _get_announcement_display_name(*, queue_manager: QueueManager, user_id: str) -> str:
    profile = queue_manager.db.get_user_profile(user_id)
    if profile and profile.display_name:
        return profile.display_name
    return user_id


def serve_user(
    *,
    queue_manager: QueueManager,
    target_user_id: str | None = None,
    announcement_service: object | None = None,
) -> dict:
    result = queue_manager.serve_specific(target_user_id) if target_user_id else queue_manager.serve_next()
    if result.get("status") != "served":
        return result

    served_user_id = result["id"]
    display_name = queue_manager.db.get_display_name(served_user_id)
    announcement_display_name = _get_announcement_display_name(
        queue_manager=queue_manager,
        user_id=served_user_id,
    )

    if announcement_service is not None:
        try:
            announcement_service.announce_called_guest(display_name=announcement_display_name)
        except Exception:
            pass

    enriched = dict(result)
    enriched["target_user_id"] = served_user_id
    enriched["display_name"] = display_name
    enriched["announcement_display_name"] = announcement_display_name
    return enriched
