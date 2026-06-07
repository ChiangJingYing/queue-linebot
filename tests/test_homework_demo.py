from __future__ import annotations

import copy
from datetime import datetime
from types import SimpleNamespace

import main
from bot.handler import LineBotHandler
from core.database import DatabaseManager
from core.queue_manager import QueueManager
from core.time_utils import TAIPEI_TZ
from services.homework_demo import (
    HomeworkBookingService,
    InMemoryHomeworkSheetGateway,
    HomeworkDemoConfig,
    build_homework_demo_config,
    parse_student_identity,
)
from services.homework_demo_presenters import build_homework_date_flex, build_homework_slot_flex


def make_text_event(text: str, user_id: str = "alice", reply_token: str = "reply-token"):
    return SimpleNamespace(
        message=SimpleNamespace(type="text", text=text),
        source=SimpleNamespace(userId=user_id),
        reply_token=reply_token,
        replyToken=reply_token,
    )


def make_postback_event(data: str, user_id: str = "alice", reply_token: str = "reply-token"):
    return SimpleNamespace(
        message=SimpleNamespace(type="text", text=data),
        source=SimpleNamespace(userId=user_id),
        postback=SimpleNamespace(data=data),
        reply_token=reply_token,
        replyToken=reply_token,
    )


def _collect_texts(node):
    texts = []
    if isinstance(node, dict):
        if isinstance(node.get("text"), str):
            texts.append(node["text"])
        for value in node.values():
            texts.extend(_collect_texts(value))
    elif isinstance(node, list):
        for item in node:
            texts.extend(_collect_texts(item))
    return texts


def _before_booking_deadline() -> datetime:
    return datetime(2026, 5, 1, 12, 0, tzinfo=TAIPEI_TZ)


def _config(**overrides) -> HomeworkDemoConfig:
    base = HomeworkDemoConfig(
        enabled=True,
        spreadsheet_id="spreadsheet-id",
        sheet_names=["Amy", "Bob"],
        ta_order=["Amy", "Bob"],
        ta_display_names={"Amy": "Amy", "Bob": "Bob"},
        ta_limits={"Amy": 2, "Bob": 1},
        ta_blacklists={"Amy": ["114106999"]},
        booking_year=2026,
        slot_range="A1:E4",
        range_start_row=1,
        range_start_col=1,
        max_demo_per_student=2,
        min_gap_days=1,
        same_ta_after_first_demo=True,
        cancel_deadline_hour=21,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _gateway() -> InMemoryHomeworkSheetGateway:
    return InMemoryHomeworkSheetGateway(
        {
            "Amy": [
                ["", "5/4", "5/5", "5/6", "5/7"],
                ["11:00-11:30", "", "114106111 王小明", "", ""],
                ["11:30-12:00", "", "", "", ""],
                ["13:30-14:00", "114106222 測試乙", "", "", ""],
            ],
            "Bob": [
                ["", "5/4", "5/5", "5/6"],
                ["11:00-11:30", "114106333 測試丙", "", ""],
                ["11:30-12:00", "", "", ""],
            ],
        }
    )


class CountingHomeworkSheetGateway(InMemoryHomeworkSheetGateway):
    def __init__(self, sheets, *, now_provider=None) -> None:
        super().__init__(sheets)
        self.now_provider = now_provider or (lambda: 0.0)
        self.list_sheet_rows_calls = 0
        self.remote_reads = 0
        self.read_requests: list[dict] = []
        self._cache: dict[tuple[str, ...], tuple[float, dict[str, list[list[str]]]]] = {}

    def list_sheet_rows(
        self,
        sheet_names: list[str],
        *,
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, list[list[str]]]:
        self.list_sheet_rows_calls += 1
        cache_key = tuple(sheet_names)
        self.read_requests.append(
            {
                "sheet_names": list(sheet_names),
                "use_cache": use_cache,
                "force_refresh": force_refresh,
            }
        )
        cached = self._cache.get(cache_key)
        if use_cache and not force_refresh and cached is not None and (self.now_provider() - cached[0]) <= 5.0:
            return copy.deepcopy(cached[1])
        self.remote_reads += 1
        result = super().list_sheet_rows(sheet_names, use_cache=use_cache, force_refresh=force_refresh)
        self._cache[cache_key] = (self.now_provider(), copy.deepcopy(result))
        return result

    def update_cell(self, sheet_name: str, row_index: int, col_index: int, value: str) -> None:
        super().update_cell(sheet_name, row_index, col_index, value)
        self.invalidate_cache(sheet_names=[sheet_name])

    def invalidate_cache(self, *, sheet_names: list[str] | None = None) -> None:
        self._cache.clear()


def test_parse_student_identity_supports_compact_input():
    parsed = parse_student_identity("114106123王小明")

    assert parsed.student_id == "114106123"
    assert parsed.student_name == "王小明"
    assert parsed.display_label == "114106123 王小明"


def test_parse_student_identity_rejects_invalid_input():
    assert parse_student_identity("11410 王小明") is None
    assert parse_student_identity("王小明") is None


def test_build_homework_demo_config_supports_slot_range_and_hardcodes_taipei_timezone():
    config = build_homework_demo_config(
        {
            "enabled": True,
            "spreadsheet_id": "sheet-id",
            "sheet_names": ["Amy"],
            "ta_order": ["Amy"],
            "slot_range": "B2:F20",
            "booking_timezone": "UTC",
        }
    )

    assert config.slot_range == "B2:F20"
    assert config.booking_timezone == "Asia/Taipei"
    assert config.sheet_names == []
    assert config.ta_order == []
    assert config.range_start_row == 2
    assert config.range_start_col == 2
    assert config.header_row == 2
    assert config.time_col == 2
    assert config.date_start_col == 2
    assert config.date_end_col == 6
    assert config.slot_start_row == 2
    assert config.slot_end_row == 20
    assert config.fetch_range == "B2:F20"


def test_build_homework_demo_config_uses_env_spreadsheet_id_and_default_limit(monkeypatch):
    monkeypatch.setenv("HOMEWORK_DEMO_SPREADSHEET_ID", "spreadsheet-from-env")

    config = build_homework_demo_config(
        {
            "enabled": True,
            "default_ta_limit": 8,
        }
    )

    assert config.spreadsheet_id == "spreadsheet-from-env"
    assert config.default_ta_limit == 8


def test_service_uses_all_sheet_names_when_not_configured():
    service = HomeworkBookingService(
        config=HomeworkDemoConfig(
            enabled=True,
            spreadsheet_id="sheet-id",
            sheet_names=[],
            ta_order=[],
            ta_display_names={},
            ta_limits={},
            ta_blacklists={},
            booking_year=2026,
            slot_range="A1:C2",
            range_start_row=1,
            range_start_col=1,
        ),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [["", "5/4", "5/5"], ["11:00-11:30", "", ""]],
                "Bob": [["", "5/4", "5/5"], ["11:00-11:30", "", ""]],
            }
        ),
        now_provider=_before_booking_deadline,
    )

    ta_names = [option.ta_name for option in service.list_ta_options(parse_student_identity("114106123 王小明"))]
    assert ta_names == ["Amy", "Bob"]


def test_service_uses_default_ta_limit_when_specific_limit_missing():
    service = HomeworkBookingService(
        config=HomeworkDemoConfig(
            enabled=True,
            spreadsheet_id="sheet-id",
            sheet_names=[],
            default_ta_limit=1,
            booking_year=2026,
            slot_range="A1:C2",
            range_start_row=1,
            range_start_col=1,
        ),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [["", "5/4", "5/5"], ["11:00-11:30", "114106999 王小黑", ""]],
                "Bob": [["", "5/4", "5/5"], ["11:00-11:30", "", ""]],
            }
        ),
        now_provider=_before_booking_deadline,
    )

    options = {option.ta_name: option for option in service.list_ta_options(parse_student_identity("114106123 王小明"))}
    assert options["Amy"].selectable is False
    assert "已滿" in options["Amy"].reason
    assert options["Bob"].selectable is True


def test_build_homework_slot_flex_splits_slots_across_multiple_messages():
    options = [
        SimpleNamespace(
            booking_key=f"Amy|{index}|2",
            time_slot=f"slot-{index}",
            selectable=True,
            reason="",
        )
        for index in range(20)
    ]

    messages = build_homework_slot_flex(options, ta_name="Amy", iso_date="2026-05-04")

    assert len(messages) == 2
    assert messages[0]["altText"] == "請選擇時段"
    assert len(messages[0]["contents"]["contents"]) == 10
    assert len(messages[1]["contents"]["contents"]) == 10
    assert "slot-10" in _collect_texts(messages[1]["contents"]["contents"][0])
    first_bubble_texts = _collect_texts(messages[0]["contents"]["contents"][0])
    assert "助教" in first_bubble_texts
    assert "Amy" in first_bubble_texts
    assert "日期" in first_bubble_texts
    assert "2026-05-04" in first_bubble_texts


def test_line_handler_returns_multiple_slot_flex_messages_when_slots_exceed_twelve(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-slot-pages.db"))
    service = HomeworkBookingService(
        config=HomeworkDemoConfig(
            enabled=True,
            spreadsheet_id="sheet-id",
            sheet_names=["Amy"],
            ta_order=["Amy"],
            ta_display_names={"Amy": "Amy"},
            booking_year=2026,
            slot_range="A1:B21",
            range_start_row=1,
            range_start_col=1,
            header_row=1,
            time_col=1,
            date_start_col=2,
            date_end_col=2,
            slot_start_row=2,
            slot_end_row=21,
            fetch_range="A1:B21",
        ),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["時段", "5/4"],
                    ["08:00-08:30", ""],
                    ["08:30-09:00", ""],
                    ["09:00-09:30", ""],
                    ["09:30-10:00", ""],
                    ["10:00-10:30", ""],
                    ["10:30-11:00", ""],
                    ["11:00-11:30", ""],
                    ["11:30-12:00", ""],
                    ["13:00-13:30", ""],
                    ["13:30-14:00", ""],
                    ["14:00-14:30", ""],
                    ["14:30-15:00", ""],
                    ["15:00-15:30", ""],
                    ["15:30-16:00", ""],
                    ["16:00-16:30", ""],
                    ["16:30-17:00", ""],
                    ["19:00-19:30", ""],
                    ["20:00-20:30", ""],
                    ["20:30-21:00", ""],
                    ["21:00-21:30", ""],
                ]
            }
        ),
        now_provider=_before_booking_deadline,
    )
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    handler.handle_event(make_text_event("/homework", reply_token="r1"))
    handler.handle_event(make_text_event("114106123 王小明", reply_token="r2"))
    result = handler.handle_event(make_postback_event("homework:register:date:Amy:2026-05-04", reply_token="r3"))

    assert len(result[0]["messages"]) == 2
    assert result[0]["messages"][0]["altText"] == "請選擇時段"
    assert len(result[0]["messages"][0]["contents"]["contents"]) == 10
    assert len(result[0]["messages"][1]["contents"]["contents"]) == 10
    tail_titles = [
        bubble["body"]["contents"][1]["text"]
        for bubble in result[0]["messages"][1]["contents"]["contents"]
    ]
    assert "20:00-20:30" in tail_titles
    assert "20:30-21:00" in tail_titles
    assert "21:00-21:30" in tail_titles


def test_build_homework_slot_flex_balances_three_pages():
    options = [
        SimpleNamespace(
            booking_key=f"Amy|{index}|2",
            time_slot=f"slot-{index}",
            selectable=True,
            reason="",
        )
        for index in range(25)
    ]

    messages = build_homework_slot_flex(options, ta_name="Amy", iso_date="2026-05-04")

    sizes = [len(message["contents"]["contents"]) for message in messages]
    assert sizes == [9, 8, 8]


def test_build_homework_date_flex_includes_selected_ta_context():
    messages = build_homework_date_flex(
        [SimpleNamespace(iso_date="2026-05-04", date_label="2026-05-04", selectable=True, reason="", available_slots=3)],
        ta_name="Amy",
    )

    bubble_texts = _collect_texts(messages[0]["contents"]["contents"][0])
    assert "助教" in bubble_texts
    assert "Amy" in bubble_texts
    assert "可選時段" in bubble_texts
    assert "3" in bubble_texts


def test_service_parses_google_range_relative_rows_for_b2_f20():
    service = HomeworkBookingService(
        config=HomeworkDemoConfig(
            enabled=True,
            spreadsheet_id="sheet-id",
            sheet_names=["Amy"],
            ta_order=["Amy"],
            ta_display_names={"Amy": "Amy"},
            booking_year=2026,
            slot_range="B2:F20",
            range_start_row=2,
            range_start_col=2,
            header_row=2,
            time_col=2,
            date_start_col=2,
            date_end_col=6,
            slot_start_row=2,
            slot_end_row=20,
            fetch_range="B2:F20",
        ),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/4", "5/5", "5/6", "5/7"],
                    ["11:00-11:30", "", "", "", ""],
                    ["11:30-12:00", "", "114106123 王小明", "", ""],
                    ["", "", "", "", ""],
                ]
            }
        ),
        now_provider=_before_booking_deadline,
    )

    student = parse_student_identity("114106999 王小黑")
    date_options = {option.iso_date: option for option in service.list_date_options(student=student, ta_name="Amy")}
    assert date_options["2026-05-04"].selectable is True
    assert date_options["2026-05-05"].selectable is True

    bookings = service.list_bookings(parse_student_identity("114106123 王小明"))
    assert len(bookings) == 1
    assert bookings[0].iso_date == "2026-05-05"
    assert bookings[0].time_slot == "11:30-12:00"


def test_homework_service_marks_blacklist_and_full_tas():
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=_gateway(),
        now_provider=_before_booking_deadline,
    )

    ta_options = service.list_ta_options(parse_student_identity("114106999 王小黑"))

    assert ta_options[0].ta_name == "Amy"
    assert ta_options[0].selectable is False
    assert "黑名單" in ta_options[0].reason
    assert ta_options[1].ta_name == "Bob"
    assert ta_options[1].selectable is False
    assert "已滿" in ta_options[1].reason


def test_homework_service_blocks_same_day_and_different_ta_rules():
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=_gateway(),
        now_provider=_before_booking_deadline,
    )
    student = parse_student_identity("114106111 王小明")

    date_options_for_amy = service.list_date_options(student=student, ta_name="Amy")
    labels = {option.date_label: option for option in date_options_for_amy}
    assert labels["2026-05-05"].selectable is False
    assert "已登記" in labels["2026-05-05"].reason
    assert labels["2026-05-06"].selectable is True

    ta_options = service.list_ta_options(student)
    bob_option = next(option for option in ta_options if option.ta_name == "Bob")
    assert bob_option.selectable is False
    assert "您已預約其他助教" in bob_option.reason


def test_homework_service_books_slot_and_lists_bookings():
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=_gateway(),
        now_provider=_before_booking_deadline,
    )
    student = parse_student_identity("114106123 王小明")

    slot_options = service.list_slot_options(student=student, ta_name="Amy", iso_date="2026-05-07")
    selectable = next(option for option in slot_options if option.selectable)

    result = service.book_slot(student=student, ta_name="Amy", booking_key=selectable.booking_key)

    assert result.status == "success"
    assert result.booking is not None
    assert result.booking.value == "114106123 王小明"
    assert service.list_bookings(student)[0].value == "114106123 王小明"


def test_homework_service_respects_cancel_deadline():
    service = HomeworkBookingService(
        config=_config(),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/4"],
                    ["11:00-11:30", "114106123 王小明"],
                ]
            }
        ),
        now_provider=lambda: datetime(2026, 5, 3, 21, 30, tzinfo=TAIPEI_TZ),
    )
    student = parse_student_identity("114106123 王小明")
    booking = service.list_bookings(student)[0]

    result = service.cancel_booking(student=student, booking_key=booking.booking_key)

    assert result.status == "error"
    assert "前一天晚上9點前" in result.message


def test_homework_service_blocks_cancel_at_deadline_boundary():
    service = HomeworkBookingService(
        config=_config(),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/4"],
                    ["11:00-11:30", "114106123 王小明"],
                ]
            }
        ),
        now_provider=lambda: datetime(2026, 5, 3, 21, 0, tzinfo=TAIPEI_TZ),
    )
    student = parse_student_identity("114106123 王小明")
    booking = service.list_bookings(student)[0]

    result = service.cancel_booking(student=student, booking_key=booking.booking_key)

    assert result.status == "error"
    assert "前一天晚上9點前" in result.message


def test_homework_service_marks_date_unselectable_after_booking_deadline():
    service = HomeworkBookingService(
        config=_config(),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/4", "5/5"],
                    ["11:00-11:30", "", ""],
                    ["11:30-12:00", "", ""],
                ]
            }
        ),
        now_provider=lambda: datetime(2026, 5, 3, 21, 30, tzinfo=TAIPEI_TZ),
    )

    options = {
        option.iso_date: option
        for option in service.list_date_options(
            student=parse_student_identity("114106123 王小明"),
            ta_name="Amy",
        )
    }

    assert options["2026-05-04"].selectable is False
    assert options["2026-05-04"].reason == "當日已截止預約"
    assert options["2026-05-05"].selectable is True


def test_homework_service_marks_date_unselectable_at_booking_deadline_boundary():
    service = HomeworkBookingService(
        config=_config(),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/4", "5/5"],
                    ["11:00-11:30", "", ""],
                    ["11:30-12:00", "", ""],
                ]
            }
        ),
        now_provider=lambda: datetime(2026, 5, 3, 21, 0, tzinfo=TAIPEI_TZ),
    )

    options = {
        option.iso_date: option
        for option in service.list_date_options(
            student=parse_student_identity("114106123 王小明"),
            ta_name="Amy",
        )
    }

    assert options["2026-05-04"].selectable is False
    assert options["2026-05-04"].reason == "當日已截止預約"
    assert options["2026-05-05"].selectable is True


def test_homework_service_marks_slot_unselectable_after_booking_deadline():
    service = HomeworkBookingService(
        config=_config(),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/4"],
                    ["11:00-11:30", ""],
                    ["11:30-12:00", ""],
                ]
            }
        ),
        now_provider=lambda: datetime(2026, 5, 3, 21, 30, tzinfo=TAIPEI_TZ),
    )

    options = {
        option.time_slot: option
        for option in service.list_slot_options(
            student=parse_student_identity("114106123 王小明"),
            ta_name="Amy",
            iso_date="2026-05-04",
        )
    }

    assert options["11:00-11:30"].selectable is False
    assert options["11:00-11:30"].reason == "此時段無法預約"
    assert options["11:30-12:00"].selectable is False
    assert options["11:30-12:00"].reason == "此時段無法預約"


def test_homework_service_allows_only_white_or_unset_background_slots():
    service = HomeworkBookingService(
        config=HomeworkDemoConfig(
            enabled=True,
            spreadsheet_id="sheet-id",
            sheet_names=["Amy"],
            ta_order=["Amy"],
            booking_year=2026,
            slot_range="A1:C4",
            range_start_row=1,
            range_start_col=1,
        ),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/6", "5/7"],
                    [
                        "11:00-11:30",
                        {"value": "", "backgroundColorStyle": None},
                        {"value": "", "backgroundColorStyle": {"rgbColor": {"red": 1.0, "green": 1.0, "blue": 1.0}}},
                    ],
                    [
                        "11:30-12:00",
                        {"value": "", "backgroundColorStyle": {"rgbColor": {"red": 1.0, "green": 0.8, "blue": 0.8}}},
                        {"value": "", "backgroundColorStyle": {"themeColor": "ACCENT1"}},
                    ],
                    [
                        "13:30-14:00",
                        {"value": "114106123 王小明", "backgroundColorStyle": None},
                        {"value": "", "backgroundColorStyle": None},
                    ],
                ]
            }
        ),
        now_provider=_before_booking_deadline,
    )

    options = service.list_slot_options(
        student=parse_student_identity("114106999 王小黑"),
        ta_name="Amy",
        iso_date="2026-05-06",
    )
    option_map = {option.time_slot: option for option in options}

    assert option_map["11:00-11:30"].selectable is True
    assert option_map["11:30-12:00"].selectable is False
    assert "不可預約" in option_map["11:30-12:00"].reason


def test_homework_service_accepts_multiple_time_slot_separators():
    service = HomeworkBookingService(
        config=HomeworkDemoConfig(
            enabled=True,
            spreadsheet_id="sheet-id",
            sheet_names=["Amy"],
            ta_order=["Amy"],
            booking_year=2026,
            slot_range="A1:B5",
            range_start_row=1,
            range_start_col=1,
        ),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/6"],
                    ["11:00-11:30", ""],
                    ["11:30~12:00", ""],
                    ["13:00－13:30", ""],
                    ["13:30–14:00", ""],
                ]
            }
        ),
        now_provider=_before_booking_deadline,
    )

    options = service.list_slot_options(
        student=parse_student_identity("114106999 王小黑"),
        ta_name="Amy",
        iso_date="2026-05-06",
    )

    assert [option.time_slot for option in options] == [
        "11:00-11:30",
        "11:30~12:00",
        "13:00－13:30",
        "13:30–14:00",
    ]


def test_homework_date_available_slots_counts_only_white_or_unset_background():
    service = HomeworkBookingService(
        config=HomeworkDemoConfig(
            enabled=True,
            spreadsheet_id="sheet-id",
            sheet_names=["Amy"],
            ta_order=["Amy"],
            booking_year=2026,
            slot_range="A1:B4",
            range_start_row=1,
            range_start_col=1,
        ),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/6"],
                    ["11:00-11:30", {"value": "", "backgroundColorStyle": None}],
                    ["11:30-12:00", {"value": "", "backgroundColorStyle": {"rgbColor": {"red": 1.0, "green": 0.8, "blue": 0.8}}}],
                    ["13:30-14:00", {"value": "114106123 王小明", "backgroundColorStyle": None}],
                ]
            }
        ),
    )

    option = service.list_date_options(
        student=parse_student_identity("114106999 王小黑"),
        ta_name="Amy",
    )[0]

    assert option.available_slots == 1


def test_list_date_options_reads_sheet_rows_once_per_call():
    gateway = CountingHomeworkSheetGateway(_gateway()._sheets)
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=gateway,
        now_provider=_before_booking_deadline,
    )

    service.list_date_options(student=parse_student_identity("114106123 王小明"), ta_name="Amy")

    assert gateway.list_sheet_rows_calls == 1


def test_list_slot_options_reads_sheet_rows_once_per_call():
    gateway = CountingHomeworkSheetGateway(_gateway()._sheets)
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=gateway,
        now_provider=_before_booking_deadline,
    )

    service.list_slot_options(
        student=parse_student_identity("114106123 王小明"),
        ta_name="Amy",
        iso_date="2026-05-07",
    )

    assert gateway.list_sheet_rows_calls == 1


def test_gateway_cache_hits_within_five_seconds():
    now_state = {"value": 100.0}
    gateway = CountingHomeworkSheetGateway(_gateway()._sheets, now_provider=lambda: now_state["value"])
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=gateway,
        now_provider=_before_booking_deadline,
    )

    service.list_date_options(student=parse_student_identity("114106123 王小明"), ta_name="Amy")
    service.list_date_options(student=parse_student_identity("114106123 王小明"), ta_name="Amy")

    assert gateway.remote_reads == 1


def test_gateway_cache_expires_after_five_seconds():
    now_state = {"value": 100.0}
    gateway = CountingHomeworkSheetGateway(_gateway()._sheets, now_provider=lambda: now_state["value"])
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=gateway,
        now_provider=_before_booking_deadline,
    )

    service.list_date_options(student=parse_student_identity("114106123 王小明"), ta_name="Amy")
    now_state["value"] = 106.0
    service.list_date_options(student=parse_student_identity("114106123 王小明"), ta_name="Amy")

    assert gateway.remote_reads == 2


def test_book_slot_force_refreshes_before_commit():
    gateway = CountingHomeworkSheetGateway(_gateway()._sheets)
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=gateway,
        now_provider=_before_booking_deadline,
    )
    student = parse_student_identity("114106123 王小明")

    slot_options = service.list_slot_options(student=student, ta_name="Amy", iso_date="2026-05-07")
    selectable = next(option for option in slot_options if option.selectable)
    service.book_slot(student=student, ta_name="Amy", booking_key=selectable.booking_key)

    assert any(request["force_refresh"] for request in gateway.read_requests)


def test_cancel_booking_force_refreshes_before_commit():
    gateway = CountingHomeworkSheetGateway(
        {
            "Amy": [
                ["", "5/4"],
                ["11:00-11:30", "114106123 王小明"],
            ]
        }
    )
    service = HomeworkBookingService(
        config=_config(),
        gateway=gateway,
        now_provider=lambda: datetime(2026, 5, 2, 20, 0, tzinfo=TAIPEI_TZ),
    )
    student = parse_student_identity("114106123 王小明")
    booking = service.list_bookings(student)[0]

    service.cancel_booking(student=student, booking_key=booking.booking_key)

    assert any(request["force_refresh"] for request in gateway.read_requests)


def test_gateway_update_invalidates_cache():
    now_state = {"value": 100.0}
    gateway = CountingHomeworkSheetGateway(_gateway()._sheets, now_provider=lambda: now_state["value"])

    gateway.list_sheet_rows(["Amy", "Bob"])
    gateway.update_cell("Amy", 1, 1, "114106123 王小明")
    gateway.list_sheet_rows(["Amy", "Bob"])

    assert gateway.remote_reads == 2


def test_gateway_cache_key_distinguishes_sheet_name_sets():
    now_state = {"value": 100.0}
    gateway = CountingHomeworkSheetGateway(_gateway()._sheets, now_provider=lambda: now_state["value"])

    gateway.list_sheet_rows(["Amy"])
    gateway.list_sheet_rows(["Bob"])

    assert gateway.remote_reads == 2


def test_line_handler_homework_register_flow_returns_flex_and_completes_booking(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-register.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=_gateway(),
        now_provider=_before_booking_deadline,
    )
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    first = handler.handle_event(make_text_event("/homework", reply_token="r1"))
    assert "登記" in first[0]["text"]

    second = handler.handle_event(make_text_event("114106123王小明", reply_token="r2"))
    assert second[0]["messages"][0]["type"] == "text"
    assert "已完成 Homework 登記" in second[0]["messages"][0]["text"]
    assert second[0]["messages"][1]["type"] == "flex"
    assert second[0]["messages"][1]["altText"] == "請選擇助教"

    profile = db.get_homework_user_profile("alice")
    assert profile is not None
    assert profile.student_id == "114106123"
    assert profile.student_name == "王小明"

    third = handler.handle_event(make_postback_event("homework:register:ta:Amy", reply_token="r3"))
    assert third[0]["messages"][0]["altText"] == "請選擇日期"

    fourth = handler.handle_event(make_postback_event("homework:register:date:Amy:2026-05-07", reply_token="r4"))
    assert fourth[0]["messages"][0]["type"] == "flex"

    slot_key = service.list_slot_options(
        student=parse_student_identity("114106123 王小明"),
        ta_name="Amy",
        iso_date="2026-05-07",
    )[0].booking_key
    final = handler.handle_event(make_postback_event(f"homework:register:slot:{slot_key}", reply_token="r5"))

    assert "預約完成" in _collect_texts(final[0]["messages"][0])
    bookings = service.list_bookings(parse_student_identity("114106123 王小明"))
    assert len(bookings) == 1


def test_line_handler_keeps_ta_selection_when_student_already_booked_other_ta(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-same-ta-choice.db"))
    db.upsert_homework_user_profile("alice", "114106123", "王小明")
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=_gateway(),
        now_provider=_before_booking_deadline,
    )
    student = parse_student_identity("114106123 王小明")
    slot_key = next(
        option.booking_key
        for option in service.list_slot_options(
            student=student,
            ta_name="Amy",
            iso_date="2026-05-07",
        )
        if option.selectable
    )
    service.book_slot(student=student, ta_name="Amy", booking_key=slot_key)
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    result = handler.handle_event(make_text_event("/homework", reply_token="r1"))

    assert result[0]["messages"][0]["type"] == "flex"
    assert result[0]["messages"][0]["altText"] == "請選擇助教"
    bubbles = result[0]["messages"][0]["contents"]["contents"]
    amy_bubble = next(bubble for bubble in bubbles if bubble["body"]["contents"][1]["text"] == "Amy")
    bob_bubble = next(bubble for bubble in bubbles if bubble["body"]["contents"][1]["text"] == "Bob")
    assert amy_bubble["footer"]["contents"][0]["type"] == "button"
    assert bob_bubble["footer"]["contents"][0]["type"] == "box"
    assert "您已預約其他助教" in _collect_texts(bob_bubble)


def test_line_handler_date_flex_is_reusable_across_selections(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-date-reuse.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=_gateway(),
        now_provider=_before_booking_deadline,
    )
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    handler.handle_event(make_text_event("/homework", reply_token="r1"))
    handler.handle_event(make_text_event("114106123 王小明", reply_token="r2"))

    first_slots = handler.handle_event(make_postback_event("homework:register:date:Amy:2026-05-04", reply_token="r3"))
    second_slots = handler.handle_event(make_postback_event("homework:register:date:Amy:2026-05-05", reply_token="r4"))

    first_titles = [
        bubble["body"]["contents"][1]["text"]
        for bubble in first_slots[0]["messages"][0]["contents"]["contents"]
    ]
    second_titles = [
        bubble["body"]["contents"][1]["text"]
        for bubble in second_slots[0]["messages"][0]["contents"]["contents"]
    ]
    first_selectable_titles = [
        bubble["body"]["contents"][1]["text"]
        for bubble in first_slots[0]["messages"][0]["contents"]["contents"]
        if bubble["footer"]["contents"][0]["type"] == "button"
    ]
    second_selectable_titles = [
        bubble["body"]["contents"][1]["text"]
        for bubble in second_slots[0]["messages"][0]["contents"]["contents"]
        if bubble["footer"]["contents"][0]["type"] == "button"
    ]

    assert first_slots[0]["messages"][0]["altText"] == "請選擇時段"
    assert second_slots[0]["messages"][0]["altText"] == "請選擇時段"
    assert first_titles == ["11:00-11:30", "11:30-12:00", "13:30-14:00"]
    assert second_titles == ["11:00-11:30", "11:30-12:00", "13:30-14:00"]
    assert first_selectable_titles == ["11:00-11:30", "11:30-12:00"]
    assert second_selectable_titles == ["11:30-12:00", "13:30-14:00"]


def test_line_handler_old_slot_flex_still_books_after_switching_date(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-slot-reuse.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=_gateway(),
        now_provider=_before_booking_deadline,
    )
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    handler.handle_event(make_text_event("/homework", reply_token="r1"))
    handler.handle_event(make_text_event("114106123 王小明", reply_token="r2"))
    handler.handle_event(make_postback_event("homework:register:date:Amy:2026-05-04", reply_token="r3"))
    handler.handle_event(make_postback_event("homework:register:date:Amy:2026-05-05", reply_token="r4"))

    old_slot_key = next(
        option.booking_key
        for option in service.list_slot_options(
            student=parse_student_identity("114106123 王小明"),
            ta_name="Amy",
            iso_date="2026-05-04",
        )
        if option.selectable
    )
    final = handler.handle_event(make_postback_event(f"homework:register:slot:{old_slot_key}", reply_token="r5"))

    assert "預約完成" in _collect_texts(final[0]["messages"][0])
    bookings = service.list_bookings(parse_student_identity("114106123 王小明"))
    assert len(bookings) == 1
    assert bookings[0].iso_date == "2026-05-04"


def test_line_handler_old_date_flex_still_works_after_booking_completed(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-date-after-complete.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=_gateway(),
        now_provider=_before_booking_deadline,
    )
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    handler.handle_event(make_text_event("/homework", reply_token="r1"))
    handler.handle_event(make_text_event("114106123 王小明", reply_token="r2"))
    slot_key = next(
        option.booking_key
        for option in service.list_slot_options(
            student=parse_student_identity("114106123 王小明"),
            ta_name="Amy",
            iso_date="2026-05-07",
        )
        if option.selectable
    )
    handler.handle_event(make_postback_event(f"homework:register:slot:{slot_key}", reply_token="r3"))

    reused = handler.handle_event(make_postback_event("homework:register:date:Amy:2026-05-06", reply_token="r4"))

    assert reused[0]["messages"][0]["type"] == "flex"
    assert reused[0]["messages"][0]["altText"] == "請選擇時段"


def test_line_handler_old_slot_flex_still_works_after_booking_completed(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-slot-after-complete.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=_gateway(),
        now_provider=_before_booking_deadline,
    )
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    handler.handle_event(make_text_event("/homework", reply_token="r1"))
    handler.handle_event(make_text_event("114106123 王小明", reply_token="r2"))
    first_slot_key = next(
        option.booking_key
        for option in service.list_slot_options(
            student=parse_student_identity("114106123 王小明"),
            ta_name="Amy",
            iso_date="2026-05-07",
        )
        if option.selectable
    )
    handler.handle_event(make_postback_event(f"homework:register:slot:{first_slot_key}", reply_token="r3"))

    second_slot_key = next(
        option.booking_key
        for option in service.list_slot_options(
            student=parse_student_identity("114106123 王小明"),
            ta_name="Amy",
            iso_date="2026-05-06",
        )
        if option.selectable
    )
    reused = handler.handle_event(make_postback_event(f"homework:register:slot:{second_slot_key}", reply_token="r4"))

    assert "預約完成" in _collect_texts(reused[0]["messages"][0])


def test_line_handler_skips_ta_step_when_only_one_selectable_ta(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-single-ta.db"))
    service = HomeworkBookingService(
        config=HomeworkDemoConfig(
            enabled=True,
            spreadsheet_id="sheet-id",
            sheet_names=["江金穎"],
            ta_order=["江金穎"],
            ta_display_names={"江金穎": "江金穎"},
            ta_limits={"江金穎": 8},
            ta_blacklists={"江金穎": []},
            booking_year=2027,
            slot_range="A1:F3",
        ),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "江金穎": [
                    ["", "5/4", "5/5", "5/6", "5/7", "5/8"],
                    ["11:00-11:30", "", "", "", "", ""],
                    ["11:30-12:00", "", "", "", "", ""],
                ]
            }
        ),
        now_provider=_before_booking_deadline,
    )
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    handler.handle_event(make_text_event("/homework", reply_token="r1"))
    second = handler.handle_event(make_text_event("114106123 王小明", reply_token="r2"))

    assert second[0]["messages"][1]["type"] == "flex"
    assert second[0]["messages"][1]["altText"] == "請選擇日期"


def test_line_handler_homework_list_and_cancel_flow(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-list-cancel.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/7"],
                    ["11:00-11:30", "114106123 王小明"],
                ],
            }
        ),
        now_provider=lambda: datetime(2026, 5, 5, 20, 0, tzinfo=TAIPEI_TZ),
    )
    db.upsert_homework_user_profile("alice", "114106123", "王小明")
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    first = handler.handle_event(make_text_event("/homework/list", reply_token="r1"))
    assert first[0]["messages"][0]["type"] == "flex"

    cancel_prompt = handler.handle_event(make_text_event("/homework/cancel", reply_token="r3"))
    assert cancel_prompt[0]["messages"][0]["type"] == "flex"

    booking_key = service.list_bookings(parse_student_identity("114106123 王小明"))[0].booking_key
    cancelled = handler.handle_event(make_postback_event(f"homework:cancel:booking:{booking_key}", reply_token="r5"))

    assert "取消成功" in _collect_texts(cancelled[0]["messages"][0])
    assert service.list_bookings(parse_student_identity("114106123 王小明")) == []


def test_homework_service_lists_only_late_cancel_applicable_bookings():
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}, ta_line_user_ids={"Amy": "Uamy123"}),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/7", "5/8", "5/9"],
                    ["11:00-11:30", "114106123 王小明", "114106123 王小明", "114106123 王小明"],
                ],
            }
        ),
        now_provider=lambda: datetime(2026, 5, 7, 10, 0, tzinfo=TAIPEI_TZ),
    )
    student = parse_student_identity("114106123 王小明")

    bookings = service.list_late_cancel_applicable_bookings(student)

    assert [(booking.iso_date, booking.time_slot) for booking in bookings] == [("2026-05-07", "11:00-11:30")]


def test_line_handler_homework_cancel_apply_requires_ta_line_mapping(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-apply-missing-ta.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}, ta_line_user_ids={}),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/8"],
                    ["11:00-11:30", "114106123 王小明"],
                ],
            }
        ),
        now_provider=lambda: datetime(2026, 5, 7, 22, 0, tzinfo=TAIPEI_TZ),
    )
    db.upsert_homework_user_profile("alice", "114106123", "王小明")
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    first = handler.handle_event(make_text_event("/homework/cancel/apply", reply_token="r1"))
    booking_key = service.list_bookings(parse_student_identity("114106123 王小明"))[0].booking_key
    second = handler.handle_event(make_postback_event(f"homework:cancel:apply:booking:{booking_key}", reply_token="r2"))

    assert first[0]["messages"][0]["type"] == "flex"
    assert "尚未設定審核通知對象" in second[0]["text"]


def test_homework_service_supports_compact_time_slot_for_late_cancel_window():
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}, ta_line_user_ids={"Amy": "Uamy123"}),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/4"],
                    ["1830-1900", "114106123 王小明"],
                ],
            }
        ),
        now_provider=lambda: datetime(2026, 5, 4, 18, 20, tzinfo=TAIPEI_TZ),
    )
    student = parse_student_identity("114106123 王小明")

    bookings = service.list_late_cancel_applicable_bookings(student)

    assert [(booking.iso_date, booking.time_slot) for booking in bookings] == [("2026-05-04", "1830-1900")]


def test_line_handler_homework_cancel_apply_marks_pending_booking_as_submitted(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-apply-pending-list.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}, ta_line_user_ids={"Amy": "UtaAmy"}),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/8"],
                    ["11:00-11:30", "114106123 王小明"],
                ],
            }
        ),
        now_provider=lambda: datetime(2026, 5, 7, 22, 0, tzinfo=TAIPEI_TZ),
    )
    db.upsert_homework_user_profile("alice", "114106123", "王小明")
    booking = service.list_bookings(parse_student_identity("114106123 王小明"))[0]
    db.create_homework_cancel_application(
        student_user_id="alice",
        student_id="114106123",
        student_name="王小明",
        booking_key=booking.booking_key,
        sheet_name=booking.sheet_name,
        booking_date=booking.iso_date,
        time_slot=booking.time_slot,
        reason="臨時有事",
    )
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    result = handler.handle_event(make_text_event("/homework/cancel/apply", reply_token="r1"))

    texts = _collect_texts(result[0]["messages"][0])
    assert "已送出申請" in texts


def test_line_handler_homework_cancel_apply_approve_clears_booking_and_pushes_student(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-apply-approve.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}, ta_line_user_ids={"Amy": "UtaAmy"}),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/8"],
                    ["11:00-11:30", "114106123 王小明"],
                ],
            }
        ),
        now_provider=lambda: datetime(2026, 5, 7, 22, 0, tzinfo=TAIPEI_TZ),
    )
    db.upsert_homework_user_profile("alice", "114106123", "王小明")
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)
    pushed: list[tuple[str, object]] = []
    handler.notifier.push_flex = lambda user_id, message: pushed.append((user_id, message)) or f"已推送 Flex 給 {user_id}"
    handler.notifier.push = lambda user_id, message: pushed.append((user_id, message)) or f"已推送給 {user_id}：{message}"

    handler.handle_event(make_text_event("/homework/cancel/apply", reply_token="r1"))
    booking_key = service.list_bookings(parse_student_identity("114106123 王小明"))[0].booking_key
    handler.handle_event(make_postback_event(f"homework:cancel:apply:booking:{booking_key}", reply_token="r2"))
    created = handler.handle_event(make_text_event("行程衝突", reply_token="r3"))
    assert "已送出" in created[0]["text"]
    pending = db.get_pending_homework_cancel_applications()
    result = handler.handle_event(
        make_postback_event(
            f"homework:cancel:apply:review:approve:{pending[0]['id']}",
            user_id="UtaAmy",
            reply_token="r4",
        )
    )

    assert "已核准" in result[0]["text"]
    assert service.list_bookings(parse_student_identity("114106123 王小明")) == []
    assert db.get_homework_cancel_application(pending[0]["id"])["status"] == "approved"
    assert pushed[0][0] == "UtaAmy"
    assert pushed[-1][0] == "alice"


def test_line_handler_homework_cancel_apply_reports_notification_failure_and_invalidates_application(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-apply-push-fail.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}, ta_line_user_ids={"Amy": "UtaAmy"}),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/8"],
                    ["11:00-11:30", "114106123 王小明"],
                ],
            }
        ),
        now_provider=lambda: datetime(2026, 5, 7, 22, 0, tzinfo=TAIPEI_TZ),
    )
    db.upsert_homework_user_profile("alice", "114106123", "王小明")
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)
    handler.notifier.push_flex = lambda user_id, message: "推播 Flex 失敗給 UtaAmy：LINE API 暫時不可用"

    handler.handle_event(make_text_event("/homework/cancel/apply", reply_token="r1"))
    booking_key = service.list_bookings(parse_student_identity("114106123 王小明"))[0].booking_key
    handler.handle_event(make_postback_event(f"homework:cancel:apply:booking:{booking_key}", reply_token="r2"))
    result = handler.handle_event(make_text_event("行程衝突", reply_token="r3"))
    application = db.get_homework_cancel_application(1)

    assert "送出失敗" in result[0]["text"]
    assert application["status"] == "invalid"
    assert application["review_reason"] == "審核通知推播失敗，請學生重新送出申請。"


def test_line_handler_homework_cancel_apply_reject_requires_reason_and_notifies_student(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-apply-reject.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}, ta_line_user_ids={"Amy": "UtaAmy"}),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/8"],
                    ["11:00-11:30", "114106123 王小明"],
                ],
            }
        ),
        now_provider=lambda: datetime(2026, 5, 7, 22, 0, tzinfo=TAIPEI_TZ),
    )
    db.upsert_homework_user_profile("alice", "114106123", "王小明")
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)
    pushed: list[tuple[str, object]] = []
    handler.notifier.push_flex = lambda user_id, message: pushed.append((user_id, message)) or f"已推送 Flex 給 {user_id}"
    handler.notifier.push = lambda user_id, message: pushed.append((user_id, message)) or f"已推送給 {user_id}：{message}"

    handler.handle_event(make_text_event("/homework/cancel/apply", reply_token="r1"))
    booking_key = service.list_bookings(parse_student_identity("114106123 王小明"))[0].booking_key
    handler.handle_event(make_postback_event(f"homework:cancel:apply:booking:{booking_key}", reply_token="r2"))
    handler.handle_event(make_text_event("臨時有事", reply_token="r3"))
    pending = db.get_pending_homework_cancel_applications()
    prompt = handler.handle_event(
        make_postback_event(
            f"homework:cancel:apply:review:reject:{pending[0]['id']}",
            user_id="UtaAmy",
            reply_token="r4",
        )
    )
    completed = handler.handle_event(make_text_event("不符合補退條件", user_id="UtaAmy", reply_token="r5"))

    assert "輸入不許可理由" in prompt[0]["text"]
    assert "已送出不許可" in completed[0]["text"]
    assert db.get_homework_cancel_application(pending[0]["id"])["status"] == "rejected"
    assert db.get_homework_cancel_application(pending[0]["id"])["review_reason"] == "不符合補退條件"
    assert service.list_bookings(parse_student_identity("114106123 王小明")) != []
    assert pushed[-1][0] == "alice"


def test_homework_list_requires_binding_and_then_uses_saved_profile(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-bind.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/7"],
                    ["11:00-11:30", "114106123 王小明"],
                ],
            }
        ),
        now_provider=_before_booking_deadline,
    )
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    first = handler.handle_event(make_text_event("/homework/list", reply_token="r1"))
    assert "登記" in first[0]["text"]

    second = handler.handle_event(make_text_event("114106123 王小明", reply_token="r2"))
    assert second[0]["messages"][0]["type"] == "text"
    assert "已完成 Homework 登記" in second[0]["messages"][0]["text"]
    assert second[0]["messages"][1]["type"] == "flex"

    third = handler.handle_event(make_text_event("/homework/list", reply_token="r3"))
    assert third[0]["messages"][0]["type"] == "flex"


def test_homework_register_command_overwrites_existing_binding(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-register-profile.db"))
    db.upsert_homework_user_profile("alice", "114106123", "王小明")
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=_gateway(),
        now_provider=_before_booking_deadline,
    )
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    first = handler.handle_event(make_text_event("/homework/register", reply_token="r1"))
    assert "重新輸入" in first[0]["text"] or "請輸入" in first[0]["text"]

    second = handler.handle_event(make_text_event("114106999 王小華", reply_token="r2"))

    assert "已更新 Homework 登記" in second[0]["text"]
    profile = db.get_homework_user_profile("alice")
    assert profile is not None
    assert profile.student_id == "114106999"
    assert profile.student_name == "王小華"


def test_homework_booking_and_cancel_logs_events(tmp_path):
    db = DatabaseManager(str(tmp_path / "homework-log.db"))
    service = HomeworkBookingService(
        config=_config(ta_limits={"Amy": 3, "Bob": 1}),
        gateway=InMemoryHomeworkSheetGateway(
            {
                "Amy": [
                    ["", "5/7", "5/8"],
                    ["11:00-11:30", "", "114106123 王小明"],
                ],
            }
        ),
        now_provider=lambda: datetime(2026, 5, 6, 20, 0, tzinfo=TAIPEI_TZ),
    )
    db.upsert_homework_user_profile("alice", "114106123", "王小明")
    handler = LineBotHandler(queue_manager=QueueManager(db), homework_booking_service=service)

    slot_key = service.list_slot_options(
        student=parse_student_identity("114106123 王小明"),
        ta_name="Amy",
        iso_date="2026-05-07",
    )[0].booking_key
    handler.handle_event(make_postback_event(f"homework:register:slot:{slot_key}", reply_token="r1"))

    booking = service.list_bookings(parse_student_identity("114106123 王小明"))[0]
    handler.handle_event(make_postback_event(f"homework:cancel:booking:{booking.booking_key}", reply_token="r2"))

    events = db.get_event_history("alice")
    event_types = [event.event_type for event in events]
    assert "homework_register" in event_types
    assert "homework_cancel" in event_types
    assert any("Amy" in event.details and "2026-05-07" in event.details for event in events if event.event_type == "homework_register")
    assert any("114106123 王小明" in event.details for event in events if event.event_type == "homework_cancel")


def test_normalize_event_supports_line_postback():
    event = main._normalize_event(
        {
            "type": "postback",
            "replyToken": "reply-token",
            "source": {"userId": "alice"},
            "postback": {"data": "homework:register:ta:Amy"},
        }
    )

    assert event is not None
    assert event.message.text == "homework:register:ta:Amy"
