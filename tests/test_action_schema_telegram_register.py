from services.action_schema import (
    TELEGRAM_REGISTER_GROUP_PREFIX,
    TELEGRAM_REGISTER_ITEM_PREFIX,
    build_telegram_register_group_action,
    build_telegram_register_item_action,
    is_telegram_register_choice_action,
)


def test_telegram_register_action_constants_preserve_existing_prefixes():
    assert TELEGRAM_REGISTER_GROUP_PREFIX == 'register:group:'
    assert TELEGRAM_REGISTER_ITEM_PREFIX == 'register:item:'



def test_build_telegram_register_actions_use_existing_prefixed_tokens():
    assert build_telegram_register_group_action('A') == 'register:group:A'
    assert build_telegram_register_item_action('1') == 'register:item:1'



def test_is_telegram_register_choice_action_recognizes_group_and_item_tokens():
    assert is_telegram_register_choice_action('register:group:A') is True
    assert is_telegram_register_choice_action('register:item:1') is True
    assert is_telegram_register_choice_action('A') is False
    assert is_telegram_register_choice_action('1') is False
