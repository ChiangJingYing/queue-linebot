from services.action_schema import (
    DISCORD_CANCEL_ABORT,
    DISCORD_CANCEL_CONFIRM,
    DISCORD_REGISTER_START,
    build_discord_register_group_action,
    build_discord_register_item_action,
    get_cancel_action_intent,
    get_register_choice_intent,
    is_discord_register_choice_action,
    normalize_discord_action,
)


def test_build_discord_register_actions_use_existing_tokens():
    assert build_discord_register_group_action('A') == 'register:group:A'
    assert build_discord_register_item_action('1') == 'register:item:1'


def test_is_discord_register_choice_action_recognizes_group_and_item_tokens():
    assert is_discord_register_choice_action('register:group:A') is True
    assert is_discord_register_choice_action('register:item:1') is True
    assert is_discord_register_choice_action('/register') is False


def test_get_register_choice_intent_returns_group_or_item_for_discord_tokens():
    assert get_register_choice_intent('register:group:A') == 'register_location_group'
    assert get_register_choice_intent('register:item:1') == 'register_location_item'
    assert get_register_choice_intent('/register') is None


def test_get_cancel_action_intent_recognizes_both_platform_payloads():
    assert get_cancel_action_intent(DISCORD_CANCEL_CONFIRM) == 'confirm'
    assert get_cancel_action_intent(DISCORD_CANCEL_ABORT) == 'abort'
    assert get_cancel_action_intent('確認放棄') == 'confirm'
    assert get_cancel_action_intent('取消放棄') == 'abort'
    assert get_cancel_action_intent('other') is None


def test_normalize_discord_action_preserves_existing_menu_and_cancel_tokens():
    assert normalize_discord_action('menu:join') == '/join'
    assert normalize_discord_action('menu:cancel') == '/cancel'
    assert normalize_discord_action('menu:status') == '/status'
    assert normalize_discord_action('menu:history') == '/history'
    assert normalize_discord_action('menu:help') == '/help'
    assert normalize_discord_action(DISCORD_REGISTER_START) == '/register'
    assert normalize_discord_action(DISCORD_CANCEL_CONFIRM) == DISCORD_CANCEL_CONFIRM
    assert normalize_discord_action(DISCORD_CANCEL_ABORT) == DISCORD_CANCEL_ABORT
    assert normalize_discord_action('other') == 'other'
