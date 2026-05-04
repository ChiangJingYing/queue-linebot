"""註冊流程資料落地 helper。"""

from __future__ import annotations


def complete_registration(*, queue_manager, user_id: str, display_name: str, location: str) -> dict:
    """將註冊結果寫入 queue/database，並回傳平台可直接顯示的訊息。"""
    result = queue_manager.register_name(user_id, display_name, location=location)
    if result.get("status") != "success":
        return {
            "status": "error",
            "message": f"❌ 錯誤：{result['message']}",
            "raw_result": result,
        }

    return {
        "status": "success",
        "display_name": result["display_name"],
        "location": result["location"],
        "message": f"✅ 已更新學號：{result['display_name']}\n位置：{result['location']}",
        "raw_result": result,
    }
