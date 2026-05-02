from __future__ import annotations


def begin_register_location_flow(*, display_name: str, location_options: dict[str, list[str]]) -> dict:
    groups = list(location_options.keys())
    return {
        'status': 'pending',
        'message': f"請選擇您在第幾排座位：{'、'.join(groups)}",
        'state': {'type': 'register_location_group', 'display_name': display_name.strip()},
        'options': groups,
    }


def advance_register_flow(
    *,
    state: dict,
    text: str,
    location_options: dict[str, list[str]],
    group_prefix: str = '',
    item_prefix: str = '',
) -> dict:
    step_type = state.get('type')
    raw_text = text.strip()

    if step_type == 'register_name':
        if not raw_text:
            return {'status': 'error', 'message': '學號不可為空白，請重新輸入學號。'}
        return begin_register_location_flow(display_name=raw_text, location_options=location_options)

    if step_type == 'register_location_group':
        normalized_group = raw_text.removeprefix(group_prefix).upper()
        groups = list(location_options.keys())
        if normalized_group not in location_options:
            return {
                'status': 'error',
                'message': f"無效的位置，請從以下選擇：{'、'.join(groups)}",
                'options': groups,
            }
        options = location_options[normalized_group]
        return {
            'status': 'pending',
            'message': f"請選擇您的座位（{normalized_group}-?）：{'、'.join(options)}",
            'state': {
                'type': 'register_location_item',
                'display_name': str(state.get('display_name') or ''),
                'group': normalized_group,
            },
            'options': options,
        }

    if step_type == 'register_location_item':
        group = str(state.get('group') or '')
        display_name = str(state.get('display_name') or '')
        normalized_item = raw_text.removeprefix(item_prefix).upper()
        options = location_options.get(group, [])
        if normalized_item not in options:
            return {
                'status': 'error',
                'message': f"無效的位置，請從以下選擇：{'、'.join(options)}",
                'options': options,
            }
        return {
            'status': 'complete',
            'display_name': display_name,
            'location': f'{group}-{normalized_item}',
        }

    return {'status': 'expired', 'message': '❌ 註冊流程已失效，請重新輸入 /register。'}
