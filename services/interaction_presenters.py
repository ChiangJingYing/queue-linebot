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


def build_line_cancel_confirmation_quick_options() -> list[dict]:
    return [
        {"label": "確認放棄", "text": "確認放棄"},
        {"label": "我在努力看看", "text": "取消放棄"},
    ]


def build_telegram_reply_keyboard_markup(keyboard: list[list[dict]]) -> dict:
    return {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "is_persistent": True,
        "one_time_keyboard": False,
    }


def build_telegram_cancel_confirmation_markup() -> dict:
    return {
        "inline_keyboard": [[
            {"text": "確認放棄", "callback_data": TELEGRAM_CANCEL_CONFIRM},
            {"text": "取消放棄", "callback_data": TELEGRAM_CANCEL_ABORT},
        ]]
    }


def build_telegram_choice_markup(*, options: list[str], prefix: str) -> dict:
    if prefix == TELEGRAM_REGISTER_GROUP_PREFIX:
        row = [build_telegram_simple_callback_button(option, build_telegram_register_group_action(option)) for option in options]
    elif prefix == TELEGRAM_REGISTER_ITEM_PREFIX:
        row = [build_telegram_simple_callback_button(option, build_telegram_register_item_action(option)) for option in options]
    else:
        row = [{"text": option, "callback_data": f"{prefix}{option}"} for option in options]
    return {"inline_keyboard": [row]}


def build_discord_menu_components(rows: list[list[dict]]) -> list[dict]:
    return [{"type": 1, "components": [{"type": 2, **item} for item in row]} for row in rows]


def build_discord_cancel_confirmation_components() -> list[dict]:
    return build_discord_menu_components([
        [
            {"label": "確認放棄", "custom_id": DISCORD_CANCEL_CONFIRM, "style": "danger"},
            {"label": "取消放棄", "custom_id": DISCORD_CANCEL_ABORT, "style": "secondary"},
        ]
    ])


def build_discord_choice_components(*, options: list[str], prefix: str) -> list[dict]:
    if prefix == DISCORD_REGISTER_GROUP_PREFIX:
        row = [{"label": option, "custom_id": build_discord_register_group_action(option), "style": "secondary"} for option in options]
    elif prefix == DISCORD_REGISTER_ITEM_PREFIX:
        row = [{"label": option, "custom_id": build_discord_register_item_action(option), "style": "secondary"} for option in options]
    else:
        row = [{"label": option, "custom_id": f"{prefix}{option}", "style": "secondary"} for option in options]
    return build_discord_menu_components([row])
