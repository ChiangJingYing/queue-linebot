"""多平台互動元件 presenter helpers。

集中管理 LINE quick reply、Telegram reply/inline keyboard、Discord button components
的組裝邏輯，讓 command service 只關心 flow 與文案，不必重複處理各平台 schema。
"""

from __future__ import annotations

from services.action_schema import (
    DISCORD_CANCEL_ABORT,
    DISCORD_CANCEL_CONFIRM,
    DISCORD_REGISTER_GROUP_PREFIX,
    DISCORD_REGISTER_ITEM_PREFIX,
    TELEGRAM_CANCEL_ABORT,
    TELEGRAM_CANCEL_CONFIRM,
    TELEGRAM_REGISTER_GROUP_PREFIX,
    TELEGRAM_REGISTER_ITEM_PREFIX,
    build_discord_register_group_action,
    build_discord_register_item_action,
    build_telegram_register_group_action,
    build_telegram_register_item_action,
    build_telegram_simple_callback_button,
)


#: Discord button style 名稱到 API 數字 enum 的映射。
_DISCORD_BUTTON_STYLE_MAP = {
    "primary": 1,
    "secondary": 2,
    "success": 3,
    "danger": 4,
}


def build_line_cancel_confirmation_quick_options() -> list[dict]:
    """建立 LINE 封隊放棄流程使用的 quick reply 選項。"""
    return [
        {"label": "確認放棄", "text": "確認放棄"},
        {"label": "我在努力看看", "text": "取消放棄"},
    ]


def build_telegram_reply_keyboard_markup(keyboard: list[list[dict]]) -> dict:
    """建立 Telegram reply keyboard markup。"""
    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "is_persistent": True,
        "one_time_keyboard": False,
    }


def build_telegram_cancel_confirmation_markup() -> dict:
    """建立 Telegram 封隊放棄確認的 inline keyboard。"""
    return {
        "inline_keyboard": [[
            {"text": "確認放棄", "callback_data": TELEGRAM_CANCEL_CONFIRM},
            {"text": "取消放棄", "callback_data": TELEGRAM_CANCEL_ABORT},
        ]]
    }


def build_telegram_choice_markup(*, options: list[str], prefix: str) -> dict:
    """建立 Telegram 註冊流程或一般選項用的單列 inline keyboard。"""
    if prefix == TELEGRAM_REGISTER_GROUP_PREFIX:
        row = [build_telegram_simple_callback_button(option, build_telegram_register_group_action(option)) for option in options]
    elif prefix == TELEGRAM_REGISTER_ITEM_PREFIX:
        row = [build_telegram_simple_callback_button(option, build_telegram_register_item_action(option)) for option in options]
    else:
        row = [{"text": option, "callback_data": f"{prefix}{option}"} for option in options]
    return {"inline_keyboard": [row]}


def _normalize_discord_button(button: dict) -> dict:
    """把內部 button 表示法轉成 Discord components API 需要的格式。"""
    normalized = dict(button)
    style = normalized.get("style", "secondary")
    if isinstance(style, str):
        normalized["style"] = _DISCORD_BUTTON_STYLE_MAP.get(style, 2)
    elif isinstance(style, int):
        normalized["style"] = style
    else:
        normalized["style"] = 2
    return {"type": 2, **normalized}


def build_discord_menu_components(rows: list[list[dict]]) -> list[dict]:
    """建立 Discord action rows，並正規化其中 button style。"""
    return [{"type": 1, "components": [_normalize_discord_button(item) for item in row]} for row in rows]


def build_discord_cancel_confirmation_components() -> list[dict]:
    """建立 Discord 封隊放棄確認用的按鈕列。"""
    return build_discord_menu_components([
        [
            {"label": "確認放棄", "custom_id": DISCORD_CANCEL_CONFIRM, "style": "danger"},
            {"label": "取消放棄", "custom_id": DISCORD_CANCEL_ABORT, "style": "secondary"},
        ]
    ])


def build_discord_choice_components(*, options: list[str], prefix: str) -> list[dict]:
    """建立 Discord 選項按鈕，並遵守每列最多 5 顆按鈕的限制。"""
    if prefix == DISCORD_REGISTER_GROUP_PREFIX:
        buttons = [{"label": option, "custom_id": build_discord_register_group_action(option), "style": "secondary"} for option in options]
    elif prefix == DISCORD_REGISTER_ITEM_PREFIX:
        buttons = [{"label": option, "custom_id": build_discord_register_item_action(option), "style": "secondary"} for option in options]
    else:
        buttons = [{"label": option, "custom_id": f"{prefix}{option}", "style": "secondary"} for option in options]

    rows = [buttons[index:index + 5] for index in range(0, len(buttons), 5)]
    return build_discord_menu_components(rows)
