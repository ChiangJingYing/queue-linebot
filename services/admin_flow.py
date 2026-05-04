"""管理員共用流程與資料整理 helpers。

這個模組負責把 queue/database 層的原始資料轉成管理介面較容易消費的結構，
例如完整狀態、統計、歷史預覽、匯出預覽，以及管理員可直接呼叫的簡單動作。
"""

from __future__ import annotations


def _profile_label(queue_manager, user_id: str) -> str:
    """取得使用者顯示名稱，作為 admin 介面標籤。"""
    return queue_manager.db.get_display_name(user_id)


def _profile_verified(queue_manager, user_id: str) -> bool:
    """判斷使用者是否已完成驗證。"""
    profile = queue_manager.db.get_user_profile(user_id)
    return bool(profile and profile.verified)


def build_admin_status(*, queue_manager) -> dict:
    """建立 admin 完整狀態面板所需資料。"""
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
    """回傳 admin 統計面板所需資料。"""
    return queue_manager.get_stats()


def build_vip_status(*, vip_service) -> dict:
    """回傳 VIP 功能啟用狀態與數量資訊。"""
    return vip_service.get_vip_status()


def toggle_vip(*, vip_service, enabled: bool) -> dict:
    """開關 VIP 功能。"""
    return vip_service.toggle_vip(enabled)


def clear_vip_queue(*, queue_manager) -> dict:
    """清空 VIP 隊列。"""
    return queue_manager.clear_vip_queue()


def build_admin_history(*, queue_manager, user_id: str) -> dict | None:
    """建立指定使用者的歷史查詢結果；若無資料則回傳 ``None``。"""
    history = queue_manager.get_user_history(user_id)
    if not history:
        return None
    return {"user_id": user_id, "history": history[:10]}


def build_admin_export_preview(*, queue_manager, limit: int = 200, preview_lines: int = 12, preview_threshold: int = 3500) -> dict:
    """建立 CSV 匯出預覽。

    若匯出內容過長，會改成只回傳前幾行 preview，避免訊息平台塞爆。
    """
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
    """切換總隊列開關狀態。"""
    enabled = not queue_manager.get_queue_enabled()
    queue_manager.set_queue_enabled(enabled)
    return {"enabled": enabled}


def set_admin_join_enabled(*, queue_manager, enabled: bool) -> dict:
    """直接指定總隊列是否開放加入。"""
    queue_manager.set_queue_enabled(enabled)
    return {"enabled": enabled}


def get_admin_join_status(*, queue_manager) -> dict:
    """讀取總隊列開放狀態。"""
    return {"enabled": queue_manager.get_queue_enabled()}


def ping_user(*, queue_manager, target_id: str | None = None) -> dict:
    """提醒下一位或指定使用者。"""
    return queue_manager.ping_user(target_id)


def clear_all_queue(*, queue_manager, keep_admin_user_ids: set[str]) -> dict:
    """清空全部隊列，但保留指定 admin 使用者資料。"""
    return queue_manager.clear_all_queue(keep_admin_user_ids=keep_admin_user_ids)
