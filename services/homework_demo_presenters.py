"""Flex message presenters for homework demo booking."""

from __future__ import annotations

from services.homework_demo import HomeworkBooking, HomeworkDateOption, HomeworkSlotOption, HomeworkTaOption


_CAROUSEL_PAGE_SIZE = 12
_BLUE = "#0F6CBD"
_BLUE_SOFT = "#EEF5FF"
_BLUE_TEXT = "#0A4F9C"
_RED = "#C62828"
_RED_SOFT = "#FFF1F1"
_RED_TEXT = "#A61E1E"
_GRAY = "#667085"
_GRAY_SOFT = "#F5F7FA"
_GRAY_TEXT = "#475467"
_GREEN = "#117A65"
_GREEN_SOFT = "#EAF9F3"
_GREEN_TEXT = "#0F5F4F"
_DARK = "#1F2937"
_LIGHT_BORDER = "#D8E1EA"


def build_homework_ta_flex(options: list[HomeworkTaOption]) -> list[dict]:
    return _build_carousel(
        alt_text="請選擇助教",
        title="選擇助教",
        bubbles=[
            _option_bubble(
                step_label="步驟 1/3",
                title=option.display_name,
                badge_text="可選" if option.selectable else "不可選",
                badge_tone="primary" if option.selectable else "danger",
                metadata=[
                    ("已登記人數", f"{option.current_count}" + (f"/{option.limit}" if option.limit is not None else "")),
                    ("狀態", option.reason or "可預約"),
                ],
                note_text="選擇助教後即可查看可預約日期。" if option.selectable else option.reason,
                note_tone="primary" if option.selectable else "danger",
                action_data=f"homework:register:ta:{option.ta_name}" if option.selectable else "",
                action_label="選擇助教" if option.selectable else "目前不可選",
                selectable=option.selectable,
            )
            for option in options
        ],
    )


def build_homework_date_flex(options: list[HomeworkDateOption], *, ta_name: str) -> list[dict]:
    return _build_carousel(
        alt_text="請選擇日期",
        title="選擇日期",
        bubbles=[
            _option_bubble(
                step_label="步驟 2/3",
                title=option.date_label,
                badge_text="可選" if option.selectable else "不可選",
                badge_tone="primary" if option.selectable else "danger",
                metadata=[
                    ("助教", ta_name),
                    ("可選時段", str(option.available_slots)),
                ],
                note_text=(
                    f"本日共有 {option.available_slots} 個可預約時段。"
                    if option.selectable
                    else option.reason or "目前不可選"
                ),
                note_tone="primary" if option.selectable else "danger",
                action_data=f"homework:register:date:{ta_name}:{option.iso_date}" if option.selectable else "",
                action_label="選擇日期" if option.selectable else "目前不可選",
                selectable=option.selectable,
            )
            for option in options
        ],
    )


def build_homework_slot_flex(options: list[HomeworkSlotOption], *, ta_name: str, iso_date: str) -> list[dict]:
    return _build_carousel(
        alt_text="請選擇時段",
        title="選擇時段",
        bubbles=[
            _option_bubble(
                step_label="步驟 3/3",
                title=option.time_slot,
                badge_text="可預約" if option.selectable else "不可選",
                badge_tone="primary" if option.selectable else "danger",
                metadata=[
                    ("助教", ta_name),
                    ("日期", iso_date),
                ],
                note_text="點擊後會直接送出本次預約。" if option.selectable else option.reason or "目前不可選",
                note_tone="primary" if option.selectable else "danger",
                action_data=f"homework:register:slot:{option.booking_key}" if option.selectable else "",
                action_label="預約此時段" if option.selectable else "目前不可選",
                selectable=option.selectable,
            )
            for option in options
        ],
    )


def build_homework_booking_list_flex(bookings: list[HomeworkBooking], *, mode: str) -> list[dict]:
    action_prefix = "homework:cancel:booking:" if mode == "cancel" else ""
    selectable = mode == "cancel"
    return _build_carousel(
        alt_text="Homework 預約列表",
        title="我的預約",
        bubbles=[
            _booking_list_bubble(
                booking=booking,
                mode=mode,
                selectable=selectable,
                action_data=f"{action_prefix}{booking.booking_key}" if mode == "cancel" else "",
            )
            for booking in bookings
        ] or [
            _option_bubble(
                step_label="目前預約",
                title="目前沒有預約",
                badge_text="無資料",
                badge_tone="neutral",
                metadata=[("狀態", "尚無可顯示資料")],
                note_text="當你完成預約後，這裡會列出所有 Homework Demo 時段。",
                note_tone="neutral",
                action_data="",
                action_label="無資料",
                selectable=False,
            )
        ],
    )


def build_homework_success_flex(*, title: str, booking: HomeworkBooking, student_label: str) -> dict:
    success_tone = "success" if title == "預約完成" else "danger"
    accent = _GREEN if success_tone == "success" else _RED
    accent_soft = _GREEN_SOFT if success_tone == "success" else _RED_SOFT
    accent_text = _GREEN_TEXT if success_tone == "success" else _RED_TEXT
    return {
        "type": "flex",
        "altText": title,
        "contents": {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "box",
                        "layout": "vertical",
                        "backgroundColor": accent_soft,
                        "cornerRadius": "16px",
                        "paddingAll": "16px",
                        "spacing": "sm",
                        "contents": [
                            _badge(title, tone=success_tone),
                            {
                                "type": "text",
                                "text": f"{booking.ta_name}｜{booking.iso_date}",
                                "weight": "bold",
                                "size": "xl",
                                "color": accent,
                                "wrap": True,
                                "margin": "md",
                            },
                            {
                                "type": "text",
                                "text": booking.time_slot,
                                "size": "md",
                                "color": accent_text,
                                "margin": "sm",
                            },
                        ],
                    },
                    _info_panel(
                        [
                            ("助教", booking.ta_name),
                            ("日期", booking.iso_date),
                            ("時段", booking.time_slot),
                            ("學生", student_label),
                        ]
                    ),
                ],
            },
        },
    }


def _build_carousel(*, alt_text: str, title: str, bubbles: list[dict]) -> list[dict]:
    if not bubbles:
        return [
            {
                "type": "flex",
                "altText": alt_text,
                "contents": {
                    "type": "carousel",
                    "contents": [
                        _option_bubble(
                            step_label=title,
                            title=title,
                            badge_text="無資料",
                            badge_tone="neutral",
                            metadata=[("狀態", "目前沒有資料")],
                            note_text="目前沒有可顯示的資料。",
                            note_tone="neutral",
                            action_data="",
                            action_label="無資料",
                            selectable=False,
                        )
                    ],
                },
            }
        ]

    page_sizes = _balanced_page_sizes(len(bubbles), _CAROUSEL_PAGE_SIZE)
    messages: list[dict] = []
    start_index = 0
    for page_size in page_sizes:
        messages.append(
            {
                "type": "flex",
                "altText": alt_text,
                "contents": {
                    "type": "carousel",
                    "contents": bubbles[start_index:start_index + page_size],
                },
            }
        )
        start_index += page_size
    return messages


def _balanced_page_sizes(total_items: int, max_page_size: int) -> list[int]:
    if total_items <= 0:
        return []
    page_count = (total_items + max_page_size - 1) // max_page_size
    base_size, remainder = divmod(total_items, page_count)
    return [base_size + (1 if index < remainder else 0) for index in range(page_count)]


def _option_bubble(
    *,
    step_label: str,
    title: str,
    badge_text: str,
    badge_tone: str,
    metadata: list[tuple[str, str]],
    note_text: str,
    note_tone: str,
    action_data: str,
    action_label: str,
    selectable: bool,
) -> dict:
    accent = _BLUE if selectable else _RED
    body_contents = [
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "text",
                    "text": step_label,
                    "size": "xs",
                    "color": _GRAY,
                    "flex": 3,
                },
                _badge(badge_text, tone=badge_tone),
            ],
        },
        {
            "type": "text",
            "text": title,
            "weight": "bold",
            "size": "xl",
            "color": accent,
            "wrap": True,
            "margin": "md",
        },
        _info_panel(metadata),
        _note_panel(note_text, tone=note_tone),
    ]
    bubble = {
        "type": "bubble",
        "styles": {
            "body": {"backgroundColor": "#FFFFFF"},
            "footer": {"separator": True},
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "18px",
            "contents": body_contents,
        },
    }
    if selectable:
        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": _BLUE,
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": action_label,
                        "data": action_data,
                        "displayText": action_label,
                    },
                }
            ],
        }
    else:
        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": _GRAY_SOFT,
                    "cornerRadius": "12px",
                    "paddingAll": "10px",
                    "contents": [
                        {
                            "type": "text",
                            "text": action_label,
                            "size": "sm",
                            "weight": "bold",
                            "align": "center",
                            "color": _GRAY_TEXT,
                            "wrap": True,
                        }
                    ],
                }
            ],
        }
    return bubble


def _booking_list_bubble(
    *,
    booking: HomeworkBooking,
    mode: str,
    selectable: bool,
    action_data: str,
) -> dict:
    is_cancel = mode == "cancel"
    accent = _RED if is_cancel else _GREEN
    accent_soft = _RED_SOFT if is_cancel else _GREEN_SOFT
    accent_text = _RED_TEXT if is_cancel else _GREEN_TEXT
    badge_text = "可取消" if is_cancel else "已登記"
    badge_tone = "danger" if is_cancel else "success"
    action_label = "取消預約" if is_cancel else "已登記"
    note_text = (
        "點擊後系統會再次檢查是否仍符合取消期限。"
        if is_cancel
        else "這是你目前已存在的 Homework 預約。"
    )
    note_tone = "danger" if is_cancel else "success"

    bubble = {
        "type": "bubble",
        "styles": {
            "body": {"backgroundColor": "#FFFFFF"},
            "footer": {"separator": True},
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "md",
            "paddingAll": "18px",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "contents": [
                        {
                            "type": "text",
                            "text": "取消流程" if is_cancel else "目前預約",
                            "size": "xs",
                            "color": _GRAY,
                            "flex": 3,
                        },
                        _badge(badge_text, tone=badge_tone),
                    ],
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": accent_soft,
                    "cornerRadius": "16px",
                    "paddingAll": "14px",
                    "spacing": "sm",
                    "contents": [
                        {
                            "type": "text",
                            "text": booking.iso_date,
                            "size": "sm",
                            "weight": "bold",
                            "color": accent_text,
                            "wrap": False,
                        },
                        {
                            "type": "text",
                            "text": booking.time_slot,
                            "size": "xxl",
                            "weight": "bold",
                            "color": accent,
                            "wrap": True,
                            "margin": "xs",
                        },
                    ],
                },
                _info_panel(
                    [
                        ("助教", booking.ta_name),
                        ("學生", booking.value),
                    ]
                ),
                _note_panel(note_text, tone=note_tone),
            ],
        },
    }
    if selectable:
        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "button",
                    "style": "primary",
                    "color": _RED,
                    "height": "sm",
                    "action": {
                        "type": "postback",
                        "label": action_label,
                        "data": action_data,
                        "displayText": action_label,
                    },
                }
            ],
        }
    else:
        bubble["footer"] = {
            "type": "box",
            "layout": "vertical",
            "paddingAll": "12px",
            "contents": [
                {
                    "type": "box",
                    "layout": "vertical",
                    "backgroundColor": _GRAY_SOFT,
                    "cornerRadius": "12px",
                    "paddingAll": "10px",
                    "contents": [
                        {
                            "type": "text",
                            "text": action_label,
                            "size": "sm",
                            "weight": "bold",
                            "align": "center",
                            "color": _GRAY_TEXT,
                            "wrap": True,
                        }
                    ],
                }
            ],
        }
    return bubble


def _badge(text: str, *, tone: str) -> dict:
    background_color, text_color = _tone_colors(tone)
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": background_color,
        "cornerRadius": "999px",
        "paddingStart": "10px",
        "paddingEnd": "10px",
        "paddingTop": "4px",
        "paddingBottom": "4px",
        "contents": [
            {
                "type": "text",
                "text": text,
                "size": "xs",
                "weight": "bold",
                "align": "center",
                "color": text_color,
                "wrap": True,
            }
        ],
    }


def _info_panel(metadata: list[tuple[str, str]]) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "sm",
        "backgroundColor": "#FFFFFF",
        "borderWidth": "1px",
        "borderColor": _LIGHT_BORDER,
        "cornerRadius": "14px",
        "paddingAll": "12px",
        "contents": [
            {
                "type": "box",
                "layout": "baseline",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": label,
                        "size": "sm",
                        "color": _GRAY,
                        "flex": 2,
                    },
                    {
                        "type": "text",
                        "text": value,
                        "size": "sm",
                        "weight": "bold",
                        "color": _DARK,
                        "wrap": True,
                        "flex": 5,
                    },
                ],
            }
            for label, value in metadata
        ],
    }


def _note_panel(note_text: str, *, tone: str) -> dict:
    background_color, text_color = _tone_colors(tone)
    return {
        "type": "box",
        "layout": "vertical",
        "backgroundColor": background_color,
        "cornerRadius": "14px",
        "paddingAll": "12px",
        "contents": [
            {
                "type": "text",
                "text": note_text,
                "size": "sm",
                "wrap": True,
                "color": text_color,
            }
        ],
    }


def _tone_colors(tone: str) -> tuple[str, str]:
    if tone == "primary":
        return _BLUE_SOFT, _BLUE_TEXT
    if tone == "danger":
        return _RED_SOFT, _RED_TEXT
    if tone == "success":
        return _GREEN_SOFT, _GREEN_TEXT
    return _GRAY_SOFT, _GRAY_TEXT
