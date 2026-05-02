from services.register_flow import advance_register_flow, begin_register_location_flow


def test_begin_register_location_flow_returns_group_step_and_options():
    outcome = begin_register_location_flow(display_name='B12345678', location_options={'A': ['1', '2'], 'B': ['1']})

    assert outcome == {
        'status': 'pending',
        'message': '請選擇您在第幾排座位：A、B',
        'state': {'type': 'register_location_group', 'display_name': 'B12345678'},
        'options': ['A', 'B'],
    }


def test_advance_register_flow_transitions_from_name_to_group_selection():
    outcome = advance_register_flow(
        state={'type': 'register_name'},
        text=' B12345678 ',
        location_options={'A': ['1', '2'], 'B': ['1']},
    )

    assert outcome == {
        'status': 'pending',
        'message': '請選擇您在第幾排座位：A、B',
        'state': {'type': 'register_location_group', 'display_name': 'B12345678'},
        'options': ['A', 'B'],
    }


def test_advance_register_flow_rejects_invalid_group_and_preserves_group_choices():
    outcome = advance_register_flow(
        state={'type': 'register_location_group', 'display_name': 'B12345678'},
        text='C',
        location_options={'A': ['1', '2'], 'B': ['1']},
    )

    assert outcome == {
        'status': 'error',
        'message': '無效的位置，請從以下選擇：A、B',
        'options': ['A', 'B'],
    }


def test_advance_register_flow_transitions_from_group_to_item_selection():
    outcome = advance_register_flow(
        state={'type': 'register_location_group', 'display_name': 'B12345678'},
        text='a',
        location_options={'A': ['1', '2'], 'B': ['1']},
    )

    assert outcome == {
        'status': 'pending',
        'message': '請選擇您的座位（A-?）：1、2',
        'state': {'type': 'register_location_item', 'display_name': 'B12345678', 'group': 'A'},
        'options': ['1', '2'],
    }


def test_advance_register_flow_accepts_prefixed_discord_values_for_group_and_item():
    grouped = advance_register_flow(
        state={'type': 'register_location_group', 'display_name': 'B12345678'},
        text='register:group:b',
        location_options={'A': ['1', '2'], 'B': ['1']},
        group_prefix='register:group:',
        item_prefix='register:item:',
    )

    assert grouped == {
        'status': 'pending',
        'message': '請選擇您的座位（B-?）：1',
        'state': {'type': 'register_location_item', 'display_name': 'B12345678', 'group': 'B'},
        'options': ['1'],
    }

    completed = advance_register_flow(
        state=grouped['state'],
        text='register:item:1',
        location_options={'A': ['1', '2'], 'B': ['1']},
        group_prefix='register:group:',
        item_prefix='register:item:',
    )

    assert completed == {
        'status': 'complete',
        'display_name': 'B12345678',
        'location': 'B-1',
    }


def test_advance_register_flow_rejects_invalid_item_and_preserves_item_choices():
    outcome = advance_register_flow(
        state={'type': 'register_location_item', 'display_name': 'B12345678', 'group': 'A'},
        text='9',
        location_options={'A': ['1', '2'], 'B': ['1']},
    )

    assert outcome == {
        'status': 'error',
        'message': '無效的位置，請從以下選擇：1、2',
        'options': ['1', '2'],
    }
