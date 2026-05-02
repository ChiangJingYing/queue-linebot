from services.cancel_flow import begin_closed_queue_cancel_flow, advance_closed_queue_cancel_flow


def test_begin_closed_queue_cancel_flow_returns_step1_prompt():
    outcome = begin_closed_queue_cancel_flow()

    assert outcome == {
        'status': 'pending',
        'message': '當前隊列已關閉，確定要放棄嗎？\n若放棄無法再加入到隊列中！',
        'state': {'type': 'cancel_when_closed', 'step': 1},
    }


def test_cancel_flow_abort_clears_state_without_cancelling():
    outcome = advance_closed_queue_cancel_flow(
        state={'type': 'cancel_when_closed', 'step': 1},
        action='取消放棄',
        still_in_queue=True,
    )

    assert outcome == {
        'status': 'aborted',
        'message': '好的，已取消放棄',
    }


def test_cancel_flow_invalid_action_reprompts_confirmation():
    outcome = advance_closed_queue_cancel_flow(
        state={'type': 'cancel_when_closed', 'step': 1},
        action='其他文字',
        still_in_queue=True,
    )

    assert outcome == {
        'status': 'pending',
        'message': '請點選 quick reply 進行操作。',
        'state': {'type': 'cancel_when_closed', 'step': 1},
    }


def test_cancel_flow_missing_state_rejects_stale_confirm():
    outcome = advance_closed_queue_cancel_flow(
        state={},
        action='確認放棄',
        still_in_queue=True,
        expired_message='❌ 放棄確認流程已失效，請重新按一次放棄。',
    )

    assert outcome == {
        'status': 'expired',
        'message': '❌ 放棄確認流程已失效，請重新按一次放棄。',
    }


def test_cancel_flow_step1_confirm_advances_to_step2():
    outcome = advance_closed_queue_cancel_flow(
        state={'type': 'cancel_when_closed', 'step': 1},
        action='確認放棄',
        still_in_queue=True,
    )

    assert outcome == {
        'status': 'pending',
        'message': '您確定要放棄嗎？',
        'state': {'type': 'cancel_when_closed', 'step': 2},
    }


def test_cancel_flow_step2_confirm_completes_cancel():
    outcome = advance_closed_queue_cancel_flow(
        state={'type': 'cancel_when_closed', 'step': 2},
        action='確認放棄',
        still_in_queue=True,
    )

    assert outcome == {
        'status': 'confirm_cancel',
    }


def test_cancel_flow_when_user_already_left_queue_returns_not_in_queue():
    outcome = advance_closed_queue_cancel_flow(
        state={'type': 'cancel_when_closed', 'step': 2},
        action='確認放棄',
        still_in_queue=False,
    )

    assert outcome == {
        'status': 'not_in_queue',
        'message': '❌ 錯誤：你目前不在隊列中。',
    }
