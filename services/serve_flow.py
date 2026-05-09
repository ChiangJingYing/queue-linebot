"""叫號共用流程 helper。"""

from __future__ import annotations

from core.queue_manager import QueueManager


def _get_announcement_display_name(*, queue_manager: QueueManager, user_id: str) -> str:
    """取得適合用於現場廣播的顯示名稱。"""
    profile = queue_manager.db.get_user_profile(user_id)
    if profile and profile.display_name:
        return profile.display_name
    return user_id


def serve_user(
    *,
    queue_manager: QueueManager,
    target_user_id: str | None = None,
    announcement_service: object | None = None,
    admin_user_id: str | None = None,
) -> dict:
    """叫下一位或指定使用者，並補齊上層常用欄位。

    注意這裡有兩條不同的通知路徑：
    - ``queue_manager.serve_next()`` / ``serve_specific()`` 內部若有 ``queue_manager.notifier``，
      會對被叫號者送出私訊推播（例如 LINE / Telegram / Discord DM）。
    - ``announcement_service`` 則是額外的現場公告通道，通常用於 dashboard 顯示或語音播報，
      不負責使用者私訊。

    這裡會統一：
    - 呼叫 queue manager 的 serve 動作（含自動 release 前一次叫號）
    - 取得顯示名稱與位置編號
    - 觸發 dashboard / 語音公告（若有）
    - 回傳 enriched 結果給 LINE / Telegram / Discord handler
    """
    if target_user_id:
        result = queue_manager.serve_specific(target_user_id, admin_user_id=admin_user_id)
    else:
        result = queue_manager.serve_next(admin_user_id=admin_user_id)
    if result.get("status") != "served":
        return result

    served_user_id = result["id"]
    display_name = queue_manager.db.get_display_name(served_user_id)
    announcement_display_name = _get_announcement_display_name(
        queue_manager=queue_manager,
        user_id=served_user_id,
    )

    profile = queue_manager.db.get_user_profile(served_user_id)
    location = (profile.location if profile and profile.location else "") or served_user_id

    if announcement_service is not None:
        try:
            announcement_service.announce_called_guest(display_name=announcement_display_name)
        except Exception:
            pass

    enriched = dict(result)
    enriched["target_user_id"] = served_user_id
    enriched["display_name"] = display_name
    enriched["announcement_display_name"] = announcement_display_name
    enriched["location"] = location
    return enriched
