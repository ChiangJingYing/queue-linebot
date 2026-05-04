"""跨平台 callback / action 字串 schema。

集中管理 Discord / Telegram 互動按鈕與 callback payload，避免各平台 handler
散落硬編碼字串，讓測試與 UI builder 可以共用同一套常數與正規化 helper。
"""

from __future__ import annotations

#: Discord 註冊流程起點 action。
DISCORD_REGISTER_START = 'register:start'
#: Discord 選排別的 callback 前綴。
DISCORD_REGISTER_GROUP_PREFIX = 'register:group:'
#: Discord 選座號的 callback 前綴。
DISCORD_REGISTER_ITEM_PREFIX = 'register:item:'
#: Discord 封隊放棄確認 action。
DISCORD_CANCEL_CONFIRM = 'cancel:confirm'
#: Discord 封隊放棄取消 action。
DISCORD_CANCEL_ABORT = 'cancel:abort'

#: Telegram admin 切回主選單頁 action。
TELEGRAM_ADMIN_SWITCH_PAGE1 = 'switch_page1'
#: Telegram admin 切到第二頁功能選單 action。
TELEGRAM_ADMIN_SWITCH_PAGE2 = 'switch_page2'
#: Telegram 打開推播設定面板 action。
TELEGRAM_ADMIN_OPEN_NOTIFY_SETTINGS = 'open_notify_settings'
#: Telegram 封隊放棄確認 action。
TELEGRAM_CANCEL_CONFIRM = '確認放棄'
#: Telegram 封隊放棄取消 action。
TELEGRAM_CANCEL_ABORT = '取消放棄'
#: Telegram 選排別的 callback 前綴。
TELEGRAM_REGISTER_GROUP_PREFIX = 'register:group:'
#: Telegram 選座號的 callback 前綴。
TELEGRAM_REGISTER_ITEM_PREFIX = 'register:item:'
#: Telegram 一鍵打開全部推播 action。
TELEGRAM_NOTIFY_ALL_ON = 'notify:all:on'
#: Telegram 一鍵關閉全部推播 action。
TELEGRAM_NOTIFY_ALL_OFF = 'notify:all:off'


def build_discord_register_group_action(group: str) -> str:
    """建立 Discord 註冊流程的排別 callback。"""
    return f'{DISCORD_REGISTER_GROUP_PREFIX}{group}'


def build_discord_register_item_action(item: str) -> str:
    """建立 Discord 註冊流程的座號 callback。"""
    return f'{DISCORD_REGISTER_ITEM_PREFIX}{item}'


def build_telegram_register_group_action(group: str) -> str:
    """建立 Telegram 註冊流程的排別 callback。"""
    return f'{TELEGRAM_REGISTER_GROUP_PREFIX}{group}'


def build_telegram_register_item_action(item: str) -> str:
    """建立 Telegram 註冊流程的座號 callback。"""
    return f'{TELEGRAM_REGISTER_ITEM_PREFIX}{item}'


def build_telegram_notify_toggle_action(category: str) -> str:
    """建立 Telegram 單一推播類別的 toggle action。"""
    return f'notify:{category}:toggle'


def build_telegram_simple_callback_button(text: str, callback_data: str) -> dict:
    """建立最精簡的 Telegram inline button 結構。"""
    return {'text': text, 'callback_data': callback_data}


def get_register_choice_intent(value: str) -> str | None:
    """辨識 callback 是否為註冊流程中的排別/座號選擇。"""
    if value.startswith((DISCORD_REGISTER_GROUP_PREFIX, TELEGRAM_REGISTER_GROUP_PREFIX)):
        return 'register_location_group'
    if value.startswith((DISCORD_REGISTER_ITEM_PREFIX, TELEGRAM_REGISTER_ITEM_PREFIX)):
        return 'register_location_item'
    return None


def is_discord_register_choice_action(value: str) -> bool:
    """判斷 Discord action 是否屬於註冊流程選項。"""
    return get_register_choice_intent(value) in {'register_location_group', 'register_location_item'}


def is_telegram_register_choice_action(value: str) -> bool:
    """判斷 Telegram action 是否屬於註冊流程選項。"""
    return get_register_choice_intent(value) in {'register_location_group', 'register_location_item'}


def get_cancel_action_intent(value: str) -> str | None:
    """將各平台的取消確認 action 正規化為 confirm/abort。"""
    if value in {DISCORD_CANCEL_CONFIRM, TELEGRAM_CANCEL_CONFIRM}:
        return 'confirm'
    if value in {DISCORD_CANCEL_ABORT, TELEGRAM_CANCEL_ABORT}:
        return 'abort'
    return None


def normalize_register_choice_action(value: str, *, expected_prefix: str) -> str:
    """移除註冊 callback 前綴，回傳實際選項值。"""
    return value.removeprefix(expected_prefix) if value.startswith(expected_prefix) else value


def normalize_discord_action(text: str) -> str:
    """把 Discord menu action 正規化成共用 slash command。"""
    action_map = {
        'menu:join': '/join',
        'menu:cancel': '/cancel',
        'menu:status': '/status',
        'menu:history': '/history',
        'menu:help': '/help',
        DISCORD_REGISTER_START: '/register',
    }
    return action_map.get(text, text)
