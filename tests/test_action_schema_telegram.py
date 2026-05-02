from services.action_schema import (
    TELEGRAM_ADMIN_OPEN_NOTIFY_SETTINGS,
    TELEGRAM_ADMIN_SWITCH_PAGE1,
    TELEGRAM_ADMIN_SWITCH_PAGE2,
    TELEGRAM_CANCEL_ABORT,
    TELEGRAM_CANCEL_CONFIRM,
    TELEGRAM_NOTIFY_ALL_OFF,
    TELEGRAM_NOTIFY_ALL_ON,
    build_telegram_notify_toggle_action,
    build_telegram_simple_callback_button,
)
from services.telegram_admin_notifications import TELEGRAM_NOTIFICATION_CATEGORIES



def test_telegram_action_constants_preserve_existing_payloads():
    assert TELEGRAM_ADMIN_SWITCH_PAGE1 == 'switch_page1'
    assert TELEGRAM_ADMIN_SWITCH_PAGE2 == 'switch_page2'
    assert TELEGRAM_ADMIN_OPEN_NOTIFY_SETTINGS == 'open_notify_settings'
    assert TELEGRAM_CANCEL_CONFIRM == '確認放棄'
    assert TELEGRAM_CANCEL_ABORT == '取消放棄'
    assert TELEGRAM_NOTIFY_ALL_ON == 'notify:all:on'
    assert TELEGRAM_NOTIFY_ALL_OFF == 'notify:all:off'



def test_build_telegram_notify_toggle_action_preserves_existing_payload_format():
    for category in TELEGRAM_NOTIFICATION_CATEGORIES:
        assert build_telegram_notify_toggle_action(category) == f'notify:{category}:toggle'



def test_build_telegram_simple_callback_button_preserves_text_and_payload():
    assert build_telegram_simple_callback_button('設定基本資料', '/register') == {
        'text': '設定基本資料',
        'callback_data': '/register',
    }
