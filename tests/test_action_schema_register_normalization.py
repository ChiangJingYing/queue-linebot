from services.action_schema import (
    DISCORD_REGISTER_GROUP_PREFIX,
    DISCORD_REGISTER_ITEM_PREFIX,
    TELEGRAM_REGISTER_GROUP_PREFIX,
    TELEGRAM_REGISTER_ITEM_PREFIX,
    normalize_register_choice_action,
)


def test_normalize_register_choice_action_for_group_prefixes():
    assert normalize_register_choice_action('register:group:A', expected_prefix=DISCORD_REGISTER_GROUP_PREFIX) == 'A'
    assert normalize_register_choice_action('register:group:B', expected_prefix=TELEGRAM_REGISTER_GROUP_PREFIX) == 'B'


def test_normalize_register_choice_action_for_item_prefixes():
    assert normalize_register_choice_action('register:item:1', expected_prefix=DISCORD_REGISTER_ITEM_PREFIX) == '1'
    assert normalize_register_choice_action('register:item:2', expected_prefix=TELEGRAM_REGISTER_ITEM_PREFIX) == '2'


def test_normalize_register_choice_action_leaves_nonmatching_values_unchanged():
    assert normalize_register_choice_action('A', expected_prefix=DISCORD_REGISTER_GROUP_PREFIX) == 'A'
    assert normalize_register_choice_action('register:item:1', expected_prefix=DISCORD_REGISTER_GROUP_PREFIX) == 'register:item:1'
