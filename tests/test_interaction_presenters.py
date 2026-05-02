from services.action_schema import (
    DISCORD_REGISTER_GROUP_PREFIX,
    DISCORD_REGISTER_ITEM_PREFIX,
    TELEGRAM_REGISTER_GROUP_PREFIX,
    TELEGRAM_REGISTER_ITEM_PREFIX,
)
from services.interaction_presenters import (
    build_discord_cancel_confirmation_components,
    build_discord_choice_components,
    build_discord_menu_components,
    build_telegram_cancel_confirmation_markup,
    build_telegram_choice_markup,
    build_telegram_reply_keyboard_markup,
    build_line_cancel_confirmation_quick_options,
)


def test_build_line_cancel_confirmation_quick_options_matches_existing_labels():
    assert build_line_cancel_confirmation_quick_options() == [
        {"label": "確認放棄", "text": "確認放棄"},
        {"label": "我在努力看看", "text": "取消放棄"},
    ]


def test_build_telegram_cancel_confirmation_markup_matches_existing_callbacks():
    assert build_telegram_cancel_confirmation_markup() == {
        "inline_keyboard": [[
            {"text": "確認放棄", "callback_data": "確認放棄"},
            {"text": "取消放棄", "callback_data": "取消放棄"},
        ]]
    }


def test_build_discord_cancel_confirmation_components_match_existing_buttons():
    components = build_discord_cancel_confirmation_components()

    assert len(components) == 1
    row = components[0]["components"]
    assert [button["label"] for button in row] == ["確認放棄", "取消放棄"]
    assert [button["custom_id"] for button in row] == ["cancel:confirm", "cancel:abort"]


def test_build_telegram_choice_markup_uses_action_schema_builders():
    group_markup = build_telegram_choice_markup(options=["A", "B"], prefix=TELEGRAM_REGISTER_GROUP_PREFIX)
    item_markup = build_telegram_choice_markup(options=["1", "2"], prefix=TELEGRAM_REGISTER_ITEM_PREFIX)

    assert group_markup == {
        "inline_keyboard": [[
            {"text": "A", "callback_data": "register:group:A"},
            {"text": "B", "callback_data": "register:group:B"},
        ]]
    }
    assert item_markup == {
        "inline_keyboard": [[
            {"text": "1", "callback_data": "register:item:1"},
            {"text": "2", "callback_data": "register:item:2"},
        ]]
    }


def test_build_discord_choice_components_uses_action_schema_builders():
    group_components = build_discord_choice_components(options=["A", "B"], prefix=DISCORD_REGISTER_GROUP_PREFIX)
    item_components = build_discord_choice_components(options=["1", "2"], prefix=DISCORD_REGISTER_ITEM_PREFIX)

    assert [button["label"] for button in group_components[0]["components"]] == ["A", "B"]
    assert [button["custom_id"] for button in group_components[0]["components"]] == ["register:group:A", "register:group:B"]
    assert [button["label"] for button in item_components[0]["components"]] == ["1", "2"]
    assert [button["custom_id"] for button in item_components[0]["components"]] == ["register:item:1", "register:item:2"]


def test_build_telegram_reply_keyboard_markup_keeps_resize_and_persistence_flags():
    keyboard = [
        [{"text": "舉手"}, {"text": "放棄"}, {"text": "看狀態"}],
        [{"text": "看紀錄"}, {"text": "設定資料"}, {"text": "排隊紀錄"}],
    ]

    assert build_telegram_reply_keyboard_markup(keyboard) == {
        "keyboard": keyboard,
        "resize_keyboard": True,
        "is_persistent": True,
        "one_time_keyboard": False,
    }


def test_build_discord_menu_components_wrap_rows_into_discord_action_rows():
    rows = [
        [{"label": "舉手", "custom_id": "menu:join", "style": "primary"}],
        [{"label": "放棄", "custom_id": "menu:cancel", "style": "secondary"}],
    ]

    components = build_discord_menu_components(rows)

    assert components == [
        {"type": 1, "components": [{"type": 2, "label": "舉手", "custom_id": "menu:join", "style": "primary"}]},
        {"type": 1, "components": [{"type": 2, "label": "放棄", "custom_id": "menu:cancel", "style": "secondary"}]},
    ]
