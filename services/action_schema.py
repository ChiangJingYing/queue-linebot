from __future__ import annotations

DISCORD_REGISTER_START = 'register:start'
DISCORD_REGISTER_GROUP_PREFIX = 'register:group:'
DISCORD_REGISTER_ITEM_PREFIX = 'register:item:'
DISCORD_CANCEL_CONFIRM = 'cancel:confirm'
DISCORD_CANCEL_ABORT = 'cancel:abort'

TELEGRAM_ADMIN_SWITCH_PAGE1 = 'switch_page1'
TELEGRAM_ADMIN_SWITCH_PAGE2 = 'switch_page2'
TELEGRAM_ADMIN_OPEN_NOTIFY_SETTINGS = 'open_notify_settings'
TELEGRAM_CANCEL_CONFIRM = '確認放棄'
TELEGRAM_CANCEL_ABORT = '取消放棄'
TELEGRAM_REGISTER_GROUP_PREFIX = 'register:group:'
TELEGRAM_REGISTER_ITEM_PREFIX = 'register:item:'
TELEGRAM_NOTIFY_ALL_ON = 'notify:all:on'
TELEGRAM_NOTIFY_ALL_OFF = 'notify:all:off'


def build_discord_register_group_action(group: str) -> str:
    return f'{DISCORD_REGISTER_GROUP_PREFIX}{group}'


def build_discord_register_item_action(item: str) -> str:
    return f'{DISCORD_REGISTER_ITEM_PREFIX}{item}'


def build_telegram_register_group_action(group: str) -> str:
    return f'{TELEGRAM_REGISTER_GROUP_PREFIX}{group}'


def build_telegram_register_item_action(item: str) -> str:
    return f'{TELEGRAM_REGISTER_ITEM_PREFIX}{item}'


def build_telegram_notify_toggle_action(category: str) -> str:
    return f'notify:{category}:toggle'


def build_telegram_simple_callback_button(text: str, callback_data: str) -> dict:
    return {'text': text, 'callback_data': callback_data}


def get_register_choice_intent(value: str) -> str | None:
    if value.startswith((DISCORD_REGISTER_GROUP_PREFIX, TELEGRAM_REGISTER_GROUP_PREFIX)):
        return 'register_location_group'
    if value.startswith((DISCORD_REGISTER_ITEM_PREFIX, TELEGRAM_REGISTER_ITEM_PREFIX)):
        return 'register_location_item'
    return None


def is_discord_register_choice_action(value: str) -> bool:
    return get_register_choice_intent(value) in {'register_location_group', 'register_location_item'}


def is_telegram_register_choice_action(value: str) -> bool:
    return get_register_choice_intent(value) in {'register_location_group', 'register_location_item'}


def get_cancel_action_intent(value: str) -> str | None:
    if value in {DISCORD_CANCEL_CONFIRM, TELEGRAM_CANCEL_CONFIRM}:
        return 'confirm'
    if value in {DISCORD_CANCEL_ABORT, TELEGRAM_CANCEL_ABORT}:
        return 'abort'
    return None


def normalize_register_choice_action(value: str, *, expected_prefix: str) -> str:
    return value.removeprefix(expected_prefix) if value.startswith(expected_prefix) else value


def normalize_discord_action(text: str) -> str:
    action_map = {
        'menu:join': '/join',
        'menu:cancel': '/cancel',
        'menu:status': '/status',
        'menu:history': '/history',
        'menu:help': '/help',
        DISCORD_REGISTER_START: '/register',
    }
    return action_map.get(text, text)
