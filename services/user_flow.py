"""一般使用者共用流程與訊息組裝。

這個模組提供與平台無關的 user-facing flow helpers，讓 LINE / Telegram /
Discord 等入口能共用相同的商業邏輯結果，只在最外層處理各平台 UI 差異。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

#: 使用者尚未完成基本資料註冊時的統一錯誤訊息。
REGISTRATION_REQUIRED_MESSAGE = "❌ 錯誤：請先完成註冊（學號與座位）後再加入隊列。"
#: 查詢歷史但沒有資料時的預設回覆。
HISTORY_EMPTY_MESSAGE = "查無排隊歷史紀錄。"
#: 非管理員嘗試讀取管理員 help 時的錯誤訊息。
HELP_UNAUTHORIZED_MESSAGE = "❌ 未授權，僅限管理員使用。"


def join_user(*, queue_manager, user_id: str, queue_type: str = "regular") -> dict:
    """以平台無關的方式處理加入隊列。

    先檢查使用者是否已完成註冊；若未完成，回傳統一的
    ``needs_registration`` 狀態，交由上層平台決定如何呈現。
    """
    profile = queue_manager.db.get_user_profile(user_id)
    if profile is None or not profile.display_name or not profile.location:
        return {
            "status": "needs_registration",
            "message": REGISTRATION_REQUIRED_MESSAGE,
        }

    result = queue_manager.join(user_id, queue_type)
    if result.get("status") != "success":
        return {
            "status": "error",
            "message": f"❌ 錯誤：{result['message']}",
            "raw_result": result,
        }

    return {
        "status": "success",
        "queue_number": result["queue_number"],
        "position": result["position"],
        "total_in_queue": result["total_in_queue"],
        "raw_result": result,
    }


def cancel_user(*, queue_manager, user_id: str) -> dict:
    """以平台無關的方式處理取消排隊。"""
    result = queue_manager.cancel(user_id)
    if result.get("status") != "cancelled":
        return {
            "status": "error",
            "message": f"❌ 錯誤：{result['message']}",
            "raw_result": result,
        }

    return {
        "status": "cancelled",
        "removed_position": result["removed_position"],
        "new_total": result["new_total"],
        "raw_result": result,
    }


def get_user_status(*, queue_manager, user_id: str) -> dict:
    """回傳使用者當前排隊位置或全隊列總人數。

    叫號鎖定狀態不阻擋查詢，仍正常顯示整體排隊情況。
    """
    position = queue_manager.get_user_position(user_id)
    if position is None:
        total_count = len(queue_manager.get_queue())
        return {
            "status": "not_in_queue",
            "position": None,
            "ahead_count": None,
            "total_count": total_count,
        }

    ahead_count = max(position - 1, 0)
    return {
        "status": "in_queue",
        "position": position,
        "ahead_count": ahead_count,
        "total_count": len(queue_manager.get_queue()),
    }


def build_history_message(
    history: Iterable,
    *,
    formatter: Callable[[object], str],
    title: str = "排隊歷史紀錄",
    empty_message: str = HISTORY_EMPTY_MESSAGE,
    limit: int = 10,
) -> str:
    """將歷史資料組裝成可直接回覆給使用者的文字。"""
    items = list(history)
    if not items:
        return empty_message

    lines = [title]
    for item in items[:limit]:
        lines.append(formatter(item))
    return "\n".join(lines)


def build_help_message(
    *,
    is_admin: bool,
    admin_only: bool = False,
    include_menu: bool = False,
    include_admin_commands: bool = False,
    include_vip_join: bool = True,
    include_coffee: bool = False,
) -> dict:
    """依呼叫情境組裝 help 文字。

    這個 helper 讓不同平台可以用相同的命令說明內容，但依需求切換：
    - 是否只限管理員查看
    - 是否包含 /menu
    - 是否顯示管理員命令區塊
    - 是否顯示 VIP / coffee 相關說明
    """
    if admin_only and not is_admin:
        return {"status": "error", "message": HELP_UNAUTHORIZED_MESSAGE}

    lines = ["📋 隊列系統指令", "", "**一般使用者：**", "/register - 依提示完成學號與座位註冊", "/join - 以自己身分加入一般隊列"]
    if include_vip_join:
        lines.append("/join vip - 以自己身分加入 VIP 隊列")
    lines.extend([
        "/cancel - 取消排隊",
        "/status - 查看隊列狀態",
        "/history - 查看你的排隊歷史",
    ])
    if include_coffee:
        lines.append("/coffee - 取得 VIP 連結")
    if include_menu:
        lines.append("/menu - 顯示常用功能按鈕")
    lines.append("/help - 顯示說明")

    if include_admin_commands and is_admin:
        lines.extend([
            "",
            "**管理員指令（/admin/ 開頭）：**",
            "/admin/serve - 叫下一位",
            "/admin/serve [id] - 叫指定使用者",
            "/admin/release [id] - 解除被叫號者的鎖定（讓其可重新排隊）",
            "/admin/ping - 手動提醒下一位",
            "/admin/ping [id] - 手動提醒指定使用者",
            "/admin/status - 完整狀態",
            "/admin/stats - 統計面板",
            "/admin/clear - 清空全部隊列",
            "/admin/vip toggle [on/off] - 開關 VIP 隊列",
            "/admin/vip clear - 清空 VIP 隊列",
            "/admin/join [on/off] - 切換總隊列狀態",
            "/admin/join status - 查看總隊列狀態",
            "/admin/history [id] - 查詢使用者歷史",
            "/admin/export - 匯出 CSV 預覽",
            "/help - 顯示說明",
        ])

    return {"status": "success", "message": "\n".join(lines)}
