from __future__ import annotations


def begin_closed_queue_cancel_flow() -> dict:
    return {
        'status': 'pending',
        'message': '當前隊列已關閉，確定要放棄嗎？\n若放棄無法再加入到隊列中！',
        'state': {'type': 'cancel_when_closed', 'step': 1},
    }


def advance_closed_queue_cancel_flow(
    *,
    state: dict,
    action: str,
    still_in_queue: bool,
    expired_message: str = '❌ 註冊流程已失效，請重新輸入 /register。',
) -> dict:
    normalized = action.strip()
    if state.get('type') != 'cancel_when_closed' or state.get('step') not in {1, 2}:
        return {'status': 'expired', 'message': expired_message}

    if normalized == '取消放棄':
        return {'status': 'aborted', 'message': '好的，已取消放棄'}

    if normalized != '確認放棄':
        return {
            'status': 'pending',
            'message': '請點選 quick reply 進行操作。',
            'state': state,
        }

    if not still_in_queue:
        return {'status': 'not_in_queue', 'message': '❌ 錯誤：你目前不在隊列中。'}

    if state.get('step') == 1:
        return {
            'status': 'pending',
            'message': '您確定要放棄嗎？',
            'state': {'type': 'cancel_when_closed', 'step': 2},
        }

    return {'status': 'confirm_cancel'}
