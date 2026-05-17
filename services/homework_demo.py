"""Homework demo booking domain logic and sheet gateways."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
import copy
from collections import defaultdict
import logging
import os
from pathlib import Path
import re
import threading
import time as time_module
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from core.time_utils import TAIPEI_TZ, now_in_taipei


_STUDENT_RE = re.compile(r"^\s*(\d{9})\s*(\S.+?)\s*$")
_TIME_SLOT_SEPARATOR_RE = re.compile(r"[-~－–—]")
_SPREADSHEET_ID_FROM_URL_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")
_HOMEWORK_CACHE_TTL_SECONDS = 5.0
logger = logging.getLogger(__name__)


def google_sheets_dependencies_status() -> tuple[bool, str]:
    try:
        import google.oauth2.service_account  # noqa: F401
        import googleapiclient.discovery  # noqa: F401
    except Exception:
        return (
            False,
            "Google Sheets 依賴尚未安裝。請重新建置容器，確認 image 已包含 google-api-python-client 與 google-auth。",
        )
    return (True, "Google Sheets 依賴已就緒")


@dataclass
class StudentIdentity:
    student_id: str
    student_name: str

    @property
    def display_label(self) -> str:
        return f"{self.student_id} {self.student_name}"


@dataclass
class HomeworkDemoConfig:
    enabled: bool = False
    spreadsheet_id: str = ""
    sheet_names: list[str] = field(default_factory=list)
    ta_order: list[str] = field(default_factory=list)
    ta_display_names: dict[str, str] = field(default_factory=dict)
    default_ta_limit: int | None = None
    ta_limits: dict[str, int] = field(default_factory=dict)
    ta_blacklists: dict[str, list[str]] = field(default_factory=dict)
    booking_year: int = datetime.now(TAIPEI_TZ).year
    booking_timezone: str = "Asia/Taipei"
    slot_range: str = "A1:F20"
    max_demo_per_student: int = 2
    min_gap_days: int = 1
    same_ta_after_first_demo: bool = True
    cancel_deadline_hour: int = 21
    range_start_row: int = 1
    range_start_col: int = 1
    header_row: int = 1
    time_col: int = 1
    date_start_col: int = 2
    date_end_col: int = 6
    slot_start_row: int = 2
    slot_end_row: int = 20
    fetch_range: str = "A1:F20"


@dataclass
class HomeworkBooking:
    ta_name: str
    sheet_name: str
    iso_date: str
    date_label: str
    booking_date: date
    time_slot: str
    row_index: int
    col_index: int
    booking_key: str
    value: str = ""
    student_id: str = ""
    student_name: str = ""
    background_bookable: bool = True


@dataclass
class HomeworkTaOption:
    ta_name: str
    display_name: str
    selectable: bool
    reason: str = ""
    current_count: int = 0
    limit: int | None = None


@dataclass
class HomeworkDateOption:
    iso_date: str
    date_label: str
    selectable: bool
    reason: str = ""
    available_slots: int = 0


@dataclass
class HomeworkSlotOption:
    booking_key: str
    time_slot: str
    selectable: bool
    reason: str = ""


@dataclass
class HomeworkActionResult:
    status: str
    message: str
    booking: HomeworkBooking | None = None
    violations: list[str] = field(default_factory=list)


@dataclass
class HomeworkSnapshot:
    sheet_names: list[str]
    rows_by_sheet: dict[str, list[list[object]]]
    bookings: list[HomeworkBooking]
    bookings_with_empty: list[HomeworkBooking]
    bookings_by_ta: dict[str, list[HomeworkBooking]]
    student_bookings_by_id: dict[str, list[HomeworkBooking]]


class HomeworkSheetGateway(Protocol):
    def list_sheet_names(self, *, use_cache: bool = True, force_refresh: bool = False) -> list[str]: ...
    def list_sheet_rows(
        self,
        sheet_names: list[str],
        *,
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, list[list[object]]]: ...
    def update_cell(self, sheet_name: str, row_index: int, col_index: int, value: str) -> None: ...
    def invalidate_cache(self, *, sheet_names: list[str] | None = None) -> None: ...


class InMemoryHomeworkSheetGateway:
    """Test-friendly sheet gateway backed by a nested list matrix."""

    def __init__(self, sheets: dict[str, list[list[object]]]) -> None:
        self._sheets = copy.deepcopy(sheets)

    def list_sheet_names(self, *, use_cache: bool = True, force_refresh: bool = False) -> list[str]:
        return list(self._sheets.keys())

    def list_sheet_rows(
        self,
        sheet_names: list[str],
        *,
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, list[list[object]]]:
        names = sheet_names or list(self._sheets.keys())
        return {name: copy.deepcopy(self._sheets.get(name, [])) for name in names}

    def update_cell(self, sheet_name: str, row_index: int, col_index: int, value: str) -> None:
        rows = self._sheets.setdefault(sheet_name, [])
        while len(rows) <= row_index:
            rows.append([])
        while len(rows[row_index]) <= col_index:
            rows[row_index].append("")
        rows[row_index][col_index] = value

    def invalidate_cache(self, *, sheet_names: list[str] | None = None) -> None:
        return None


class GoogleSheetHomeworkGateway:
    """Google Sheets backed gateway using service account credentials."""

    def __init__(
        self,
        *,
        spreadsheet_id: str,
        fetch_range: str = "A1:G25",
        credentials_path: str = "",
        credentials_json: str = "",
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.fetch_range = fetch_range
        self.credentials_path = credentials_path
        self.credentials_json = credentials_json
        self._service = None
        self._sheet_names_cache: tuple[float, list[str]] | None = None
        self._rows_cache: dict[tuple[str, str, tuple[str, ...]], tuple[float, dict[str, list[list[object]]]]] = {}
        self._cache_lock = threading.Lock()

    def _build_service(self):
        if self._service is not None:
            return self._service
        dependencies_ready, dependency_message = google_sheets_dependencies_status()
        if not dependencies_ready:  # pragma: no cover - depends on optional runtime packages
            raise RuntimeError(dependency_message)
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except Exception as exc:  # pragma: no cover - depends on optional runtime packages
            raise RuntimeError(dependency_message) from exc

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        if self.credentials_json:
            import json

            info = json.loads(self.credentials_json)
            credentials = Credentials.from_service_account_info(info, scopes=scopes)
        elif self.credentials_path:
            credentials = Credentials.from_service_account_file(self.credentials_path, scopes=scopes)
        else:  # pragma: no cover - runtime configuration path
            raise RuntimeError("Google Sheets 憑證未設定。")
        self._service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return self._service

    def list_sheet_names(self, *, use_cache: bool = True, force_refresh: bool = False) -> list[str]:
        with self._cache_lock:
            if use_cache and not force_refresh and self._sheet_names_cache is not None:
                cached_at, cached_value = self._sheet_names_cache
                if self._is_cache_alive(cached_at):
                    logger.info(
                        "Homework sheet names cache hit spreadsheet_id=%s count=%s",
                        self.spreadsheet_id,
                        len(cached_value),
                    )
                    return list(cached_value)

        started_at = time_module.monotonic()
        service = self._build_service()
        response = service.spreadsheets().get(
            spreadsheetId=self.spreadsheet_id,
            fields="sheets(properties(title))",
        ).execute()
        sheets = response.get("sheets") or []
        names = [
            str(sheet.get("properties", {}).get("title") or "").strip()
            for sheet in sheets
            if str(sheet.get("properties", {}).get("title") or "").strip()
        ]
        elapsed_ms = round((time_module.monotonic() - started_at) * 1000, 2)
        logger.info(
            "Homework sheet names fetch spreadsheet_id=%s count=%s elapsed_ms=%s",
            self.spreadsheet_id,
            len(names),
            elapsed_ms,
        )
        with self._cache_lock:
            self._sheet_names_cache = (time_module.monotonic(), list(names))
        return names

    def list_sheet_rows(
        self,
        sheet_names: list[str],
        *,
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> dict[str, list[list[object]]]:
        names = list(sheet_names)
        cache_key = (self.spreadsheet_id, self.fetch_range, tuple(names))
        with self._cache_lock:
            if use_cache and not force_refresh:
                cached_entry = self._rows_cache.get(cache_key)
                if cached_entry is not None and self._is_cache_alive(cached_entry[0]):
                    logger.info(
                        "Homework sheet rows cache hit spreadsheet_id=%s sheets=%s range=%s",
                        self.spreadsheet_id,
                        len(names),
                        self.fetch_range,
                    )
                    return copy.deepcopy(cached_entry[1])

        started_at = time_module.monotonic()
        service = self._build_service()
        ranges = [f"{sheet_name}!{self.fetch_range}" for sheet_name in names]
        response = (
            service.spreadsheets()
            .get(
                spreadsheetId=self.spreadsheet_id,
                ranges=ranges,
                includeGridData=True,
            )
            .execute()
        )
        result: dict[str, list[list[object]]] = {}
        for sheet in response.get("sheets", []):
            sheet_name = str(sheet.get("properties", {}).get("title") or "").strip()
            row_data = ((sheet.get("data") or [{}])[0].get("rowData") or [])
            result[sheet_name] = [
                [
                    {
                        "value": str(cell.get("formattedValue") or ""),
                        "backgroundColorStyle": (
                            ((cell.get("userEnteredFormat") or {}).get("backgroundColorStyle"))
                            or None
                        ),
                    }
                    for cell in (row.get("values") or [])
                ]
                for row in row_data
            ]
        for name in names:
            result.setdefault(name, [])
        elapsed_ms = round((time_module.monotonic() - started_at) * 1000, 2)
        logger.info(
            "Homework sheet rows fetch spreadsheet_id=%s sheets=%s range=%s elapsed_ms=%s use_cache=%s force_refresh=%s",
            self.spreadsheet_id,
            len(names),
            self.fetch_range,
            elapsed_ms,
            use_cache,
            force_refresh,
        )
        with self._cache_lock:
            self._rows_cache[cache_key] = (time_module.monotonic(), copy.deepcopy(result))
        return result

    def update_cell(self, sheet_name: str, row_index: int, col_index: int, value: str) -> None:
        service = self._build_service()
        a1 = f"{_column_letter(col_index + 1)}{row_index + 1}"
        (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{sheet_name}!{a1}",
                valueInputOption="RAW",
                body={"values": [[value]]},
            )
            .execute()
        )
        self.invalidate_cache(sheet_names=[sheet_name])

    def invalidate_cache(self, *, sheet_names: list[str] | None = None) -> None:
        with self._cache_lock:
            self._rows_cache = {
                key: value
                for key, value in self._rows_cache.items()
                if key[0] != self.spreadsheet_id
            }

    def _is_cache_alive(self, cached_at: float) -> bool:
        return (time_module.monotonic() - cached_at) <= _HOMEWORK_CACHE_TTL_SECONDS


def parse_student_identity(text: str) -> StudentIdentity | None:
    match = _STUDENT_RE.match(str(text or ""))
    if not match:
        return None
    student_id, student_name = match.groups()
    return StudentIdentity(student_id=student_id, student_name=student_name.strip())


def build_homework_demo_config(raw: dict | None) -> HomeworkDemoConfig:
    raw = raw if isinstance(raw, dict) else {}
    slot_range = str(raw.get("slot_range") or "A1:F20")
    parsed_slot_range = _parse_slot_range(slot_range)
    spreadsheet_id = extract_google_sheet_id(str(raw.get("spreadsheet_id") or os.getenv("HOMEWORK_DEMO_SPREADSHEET_ID", "")))
    return HomeworkDemoConfig(
        enabled=bool(raw.get("enabled", False)),
        spreadsheet_id=spreadsheet_id,
        sheet_names=[],
        ta_order=[],
        ta_display_names={},
        default_ta_limit=(
            int(raw.get("default_ta_limit"))
            if raw.get("default_ta_limit") not in (None, "")
            else None
        ),
        ta_limits={},
        ta_blacklists={
            str(key): [str(student_id) for student_id in value]
            for key, value in dict(raw.get("ta_blacklists") or {}).items()
            if isinstance(value, list)
        },
        booking_year=int(raw.get("booking_year") or datetime.now(TAIPEI_TZ).year),
        booking_timezone="Asia/Taipei",
        slot_range=slot_range,
        max_demo_per_student=int(raw.get("max_demo_per_student") or 2),
        min_gap_days=int(raw.get("min_gap_days") or 1),
        same_ta_after_first_demo=bool(raw.get("same_ta_after_first_demo", True)),
        cancel_deadline_hour=int(raw.get("cancel_deadline_hour") or 21),
        range_start_row=int(raw.get("range_start_row") or parsed_slot_range["range_start_row"]),
        range_start_col=int(raw.get("range_start_col") or parsed_slot_range["range_start_col"]),
        header_row=int(raw.get("header_row") or parsed_slot_range["header_row"]),
        time_col=int(raw.get("time_col") or parsed_slot_range["time_col"]),
        date_start_col=int(raw.get("date_start_col") or parsed_slot_range["date_start_col"]),
        date_end_col=int(raw.get("date_end_col") or parsed_slot_range["date_end_col"]),
        slot_start_row=int(raw.get("slot_start_row") or parsed_slot_range["slot_start_row"]),
        slot_end_row=int(raw.get("slot_end_row") or parsed_slot_range["slot_end_row"]),
        fetch_range=str(raw.get("fetch_range") or parsed_slot_range["fetch_range"]),
    )


def build_google_homework_gateway(config: HomeworkDemoConfig) -> GoogleSheetHomeworkGateway:
    return GoogleSheetHomeworkGateway(
        spreadsheet_id=config.spreadsheet_id,
        fetch_range=config.fetch_range,
        credentials_path=resolve_google_service_account_path(),
        credentials_json=str(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")).strip(),
    )


def build_homework_gateway(config: HomeworkDemoConfig) -> HomeworkSheetGateway:
    return build_google_homework_gateway(config)


def extract_google_sheet_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    match = _SPREADSHEET_ID_FROM_URL_RE.search(raw)
    if match:
        return match.group(1)
    return raw


def resolve_google_service_account_path() -> str:
    configured = str(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")).strip()
    if configured:
        return configured
    fallback = os.fspath((Path.cwd() / "config" / "google-service-account.json").resolve())
    return fallback if os.path.exists(fallback) else ""


class HomeworkBookingService:
    def __init__(
        self,
        *,
        config: HomeworkDemoConfig,
        gateway: HomeworkSheetGateway,
        now_provider: Callable[[], datetime] = now_in_taipei,
    ) -> None:
        self.config = config
        self.gateway = gateway
        self.now_provider = now_provider

    def is_enabled(self) -> bool:
        return self.config.enabled

    def list_ta_options(self, student: StudentIdentity) -> list[HomeworkTaOption]:
        started_at = time_module.monotonic()
        snapshot = self._load_snapshot()
        options = self._build_ta_options(snapshot, student)
        logger.info("Homework list_ta_options student_id=%s elapsed_ms=%s", student.student_id, round((time_module.monotonic() - started_at) * 1000, 2))
        return options

    def list_date_options(self, *, student: StudentIdentity, ta_name: str) -> list[HomeworkDateOption]:
        started_at = time_module.monotonic()
        snapshot = self._load_snapshot()
        options = self._build_date_options(snapshot, student=student, ta_name=ta_name)
        logger.info(
            "Homework list_date_options student_id=%s ta_name=%s elapsed_ms=%s",
            student.student_id,
            ta_name,
            round((time_module.monotonic() - started_at) * 1000, 2),
        )
        return options

    def list_slot_options(self, *, student: StudentIdentity, ta_name: str, iso_date: str) -> list[HomeworkSlotOption]:
        started_at = time_module.monotonic()
        snapshot = self._load_snapshot()
        options = self._build_slot_options(snapshot, student=student, ta_name=ta_name, iso_date=iso_date)
        logger.info(
            "Homework list_slot_options student_id=%s ta_name=%s iso_date=%s elapsed_ms=%s",
            student.student_id,
            ta_name,
            iso_date,
            round((time_module.monotonic() - started_at) * 1000, 2),
        )
        return options

    def list_bookings(self, student: StudentIdentity) -> list[HomeworkBooking]:
        snapshot = self._load_snapshot()
        return self._list_bookings_from_snapshot(snapshot, student)

    def book_slot(self, *, student: StudentIdentity, ta_name: str, booking_key: str) -> HomeworkActionResult:
        started_at = time_module.monotonic()
        snapshot = self._load_snapshot(use_cache=False, force_refresh=True)
        slot = self._find_booking_key(snapshot, booking_key, include_empty=True)
        if slot is None or slot.ta_name != ta_name:
            return HomeworkActionResult(status="error", message="找不到指定的預約時段。")
        slot_options = self._build_slot_options(snapshot, student=student, ta_name=ta_name, iso_date=slot.iso_date)
        selected = next((option for option in slot_options if option.booking_key == booking_key), None)
        if selected is None or not selected.selectable:
            reason = selected.reason if selected is not None else "此時段目前不可預約。"
            return HomeworkActionResult(status="error", message=reason or "此時段目前不可預約。", violations=[reason] if reason else [])
        self.gateway.update_cell(slot.sheet_name, slot.row_index, slot.col_index, student.display_label)
        refreshed_snapshot = self._load_snapshot(use_cache=False, force_refresh=True)
        booked = self._find_booking_key(refreshed_snapshot, booking_key, include_empty=False)
        logger.info(
            "Homework book_slot student_id=%s ta_name=%s booking_key=%s elapsed_ms=%s",
            student.student_id,
            ta_name,
            booking_key,
            round((time_module.monotonic() - started_at) * 1000, 2),
        )
        return HomeworkActionResult(
            status="success",
            message=f"預約完成：{booked.ta_name} {booked.iso_date} {booked.time_slot}",
            booking=booked,
        )

    def cancel_booking(self, *, student: StudentIdentity, booking_key: str) -> HomeworkActionResult:
        started_at = time_module.monotonic()
        snapshot = self._load_snapshot(use_cache=False, force_refresh=True)
        booking = self._find_booking_key(snapshot, booking_key, include_empty=False)
        if booking is None or booking.student_id != student.student_id:
            return HomeworkActionResult(status="error", message="找不到你的預約資料。")
        deadline = datetime.combine(
            booking.booking_date - timedelta(days=1),
            time(hour=self.config.cancel_deadline_hour, tzinfo=_resolve_timezone(self.config.booking_timezone)),
        )
        if self.now_provider() > deadline:
            return HomeworkActionResult(status="error", message="取消失敗：需在預約日期前一天晚上9點前取消。")
        self.gateway.update_cell(booking.sheet_name, booking.row_index, booking.col_index, "")
        logger.info(
            "Homework cancel_booking student_id=%s booking_key=%s elapsed_ms=%s",
            student.student_id,
            booking_key,
            round((time_module.monotonic() - started_at) * 1000, 2),
        )
        return HomeworkActionResult(
            status="success",
            message=f"取消成功：{booking.ta_name} {booking.iso_date} {booking.time_slot}",
            booking=booking,
        )

    def _ta_names(self, *, use_cache: bool = True, force_refresh: bool = False) -> list[str]:
        if self.config.ta_order:
            return list(self.config.ta_order)
        if self.config.sheet_names:
            return list(self.config.sheet_names)
        return self.gateway.list_sheet_names(use_cache=use_cache, force_refresh=force_refresh)

    def _build_ta_options(self, snapshot: HomeworkSnapshot, student: StudentIdentity) -> list[HomeworkTaOption]:
        existing = list(snapshot.student_bookings_by_id.get(student.student_id, []))
        options: list[HomeworkTaOption] = []
        for ta_name in snapshot.sheet_names:
            reason = self._ta_reason(ta_name=ta_name, student=student, existing=existing, all_bookings=snapshot.bookings)
            options.append(
                HomeworkTaOption(
                    ta_name=ta_name,
                    display_name=self.config.ta_display_names.get(ta_name, ta_name),
                    selectable=reason == "",
                    reason=reason,
                    current_count=self._ta_student_count(ta_name, snapshot.bookings),
                    limit=self._limit_for_ta(ta_name),
                )
            )
        return options

    def _build_date_options(
        self,
        snapshot: HomeworkSnapshot,
        *,
        student: StudentIdentity,
        ta_name: str,
    ) -> list[HomeworkDateOption]:
        slots = snapshot.bookings_by_ta.get(ta_name, [])
        existing = list(snapshot.student_bookings_by_id.get(student.student_id, []))
        grouped: dict[str, list[HomeworkBooking]] = {}
        for slot in slots:
            grouped.setdefault(slot.iso_date, []).append(slot)
        options: list[HomeworkDateOption] = []
        for iso_date in sorted(grouped.keys()):
            reason = self._date_reason(
                student=student,
                ta_name=ta_name,
                iso_date=iso_date,
                existing=existing,
                slots=grouped[iso_date],
                all_bookings=snapshot.bookings,
            )
            available_slots = sum(
                1 for slot in grouped[iso_date] if not slot.value.strip() and slot.background_bookable
            )
            options.append(
                HomeworkDateOption(
                    iso_date=iso_date,
                    date_label=iso_date,
                    selectable=reason == "",
                    reason=reason,
                    available_slots=available_slots,
                )
            )
        return options

    def _build_slot_options(
        self,
        snapshot: HomeworkSnapshot,
        *,
        student: StudentIdentity,
        ta_name: str,
        iso_date: str,
    ) -> list[HomeworkSlotOption]:
        existing = list(snapshot.student_bookings_by_id.get(student.student_id, []))
        options: list[HomeworkSlotOption] = []
        for slot in snapshot.bookings_by_ta.get(ta_name, []):
            if slot.iso_date != iso_date:
                continue
            reason = self._date_reason(
                student=student,
                ta_name=ta_name,
                iso_date=iso_date,
                existing=existing,
                slots=[slot],
                all_bookings=snapshot.bookings,
            )
            if slot.value.strip():
                reason = "此時段已被預約"
            elif not slot.background_bookable:
                reason = "此時段不可預約"
            options.append(
                HomeworkSlotOption(
                    booking_key=slot.booking_key,
                    time_slot=slot.time_slot,
                    selectable=reason == "",
                    reason=reason,
                )
            )
        return options

    def _list_bookings_from_snapshot(self, snapshot: HomeworkSnapshot, student: StudentIdentity) -> list[HomeworkBooking]:
        bookings = list(snapshot.student_bookings_by_id.get(student.student_id, []))
        return sorted(bookings, key=lambda booking: (booking.iso_date, booking.time_slot, booking.ta_name))

    def _find_booking_key(
        self,
        snapshot: HomeworkSnapshot,
        booking_key: str,
        *,
        include_empty: bool,
    ) -> HomeworkBooking | None:
        pool = snapshot.bookings_with_empty if include_empty else snapshot.bookings
        return next((booking for booking in pool if booking.booking_key == booking_key), None)

    def _ta_reason(
        self,
        *,
        ta_name: str,
        student: StudentIdentity,
        existing: list[HomeworkBooking],
        all_bookings: list[HomeworkBooking],
    ) -> str:
        if student.student_id in self.config.ta_blacklists.get(ta_name, []):
            return "已被加入黑名單"
        if len(existing) >= self.config.max_demo_per_student:
            return "Demo 次數已滿"
        if self.config.same_ta_after_first_demo and existing and existing[0].ta_name != ta_name:
            return "您已預約其他助教"
        limit = self._limit_for_ta(ta_name)
        if limit is None:
            return ""
        unique_students = {booking.student_id for booking in all_bookings if booking.ta_name == ta_name and booking.student_id}
        if len(unique_students) >= limit and student.student_id not in unique_students:
            return "Demo人數已滿"
        return ""

    def _date_reason(
        self,
        *,
        student: StudentIdentity,
        ta_name: str,
        iso_date: str,
        existing: list[HomeworkBooking],
        slots: list[HomeworkBooking],
        all_bookings: list[HomeworkBooking],
    ) -> str:
        ta_reason = self._ta_reason(ta_name=ta_name, student=student, existing=existing, all_bookings=all_bookings)
        if ta_reason:
            return ta_reason
        same_day = next((booking for booking in existing if booking.iso_date == iso_date), None)
        if same_day is not None:
            return f"當日已登記 {same_day.time_slot}"
        target_date = _parse_iso_date(iso_date)
        if target_date is None:
            return "日期格式錯誤"
        if not any(not slot.value.strip() and slot.background_bookable for slot in slots):
            return "當日時段已滿"
        return ""

    def _ta_student_count(self, ta_name: str, bookings: list[HomeworkBooking]) -> int:
        return len({booking.student_id for booking in bookings if booking.ta_name == ta_name and booking.student_id})

    def _limit_for_ta(self, ta_name: str) -> int | None:
        if ta_name in self.config.ta_limits:
            return self.config.ta_limits[ta_name]
        return self.config.default_ta_limit

    def _load_snapshot(
        self,
        *,
        use_cache: bool = True,
        force_refresh: bool = False,
    ) -> HomeworkSnapshot:
        started_at = time_module.monotonic()
        target_sheet_names = self.config.sheet_names or self._ta_names(use_cache=use_cache, force_refresh=force_refresh)
        rows_by_sheet = self.gateway.list_sheet_rows(
            target_sheet_names,
            use_cache=use_cache,
            force_refresh=force_refresh,
        )
        bookings_with_empty: list[HomeworkBooking] = []
        for sheet_name, rows in rows_by_sheet.items():
            bookings_with_empty.extend(_parse_sheet_rows(sheet_name, rows, self.config, include_empty=True))
        bookings = [booking for booking in bookings_with_empty if booking.value.strip()]
        bookings_by_ta: dict[str, list[HomeworkBooking]] = defaultdict(list)
        student_bookings_by_id: dict[str, list[HomeworkBooking]] = defaultdict(list)
        for booking in bookings_with_empty:
            bookings_by_ta[booking.ta_name].append(booking)
        for booking in bookings:
            student_bookings_by_id[booking.student_id].append(booking)
        snapshot = HomeworkSnapshot(
            sheet_names=list(target_sheet_names),
            rows_by_sheet=rows_by_sheet,
            bookings=bookings,
            bookings_with_empty=bookings_with_empty,
            bookings_by_ta=dict(bookings_by_ta),
            student_bookings_by_id=dict(student_bookings_by_id),
        )
        logger.info(
            "Homework snapshot loaded sheets=%s bookings=%s bookings_with_empty=%s elapsed_ms=%s use_cache=%s force_refresh=%s",
            len(snapshot.sheet_names),
            len(snapshot.bookings),
            len(snapshot.bookings_with_empty),
            round((time_module.monotonic() - started_at) * 1000, 2),
            use_cache,
            force_refresh,
        )
        return snapshot


def _parse_sheet_rows(
    sheet_name: str,
    rows: list[list[object]],
    config: HomeworkDemoConfig,
    *,
    include_empty: bool,
) -> list[HomeworkBooking]:
    if not rows:
        return []
    start_row, start_col, sub_rows = _normalize_rows_for_slot_range(rows, config)
    if not sub_rows:
        return []
    header = sub_rows[0]
    results: list[HomeworkBooking] = []
    for relative_row_index, sub_row in enumerate(sub_rows[1:], start=1):
        absolute_row_index = start_row + relative_row_index
        time_slot = _safe_cell_value_from_row(sub_row, 0).strip()
        if not _looks_like_time_slot(time_slot):
            continue
        for relative_col_index in range(1, len(header)):
            raw_date = _safe_cell_value_from_row(header, relative_col_index).strip()
            iso_date = _normalize_date_label(raw_date, config.booking_year)
            if not iso_date:
                continue
            value = _safe_cell_value_from_row(sub_row, relative_col_index).strip()
            background_bookable = _is_background_bookable(
                _safe_cell_background_style_from_row(sub_row, relative_col_index)
            )
            if not include_empty and not value:
                continue
            student = parse_student_identity(value) if value else None
            results.append(
                HomeworkBooking(
                    ta_name=sheet_name,
                    sheet_name=sheet_name,
                    iso_date=iso_date,
                    date_label=iso_date,
                    booking_date=_parse_iso_date(iso_date),
                    time_slot=time_slot,
                    row_index=absolute_row_index,
                    col_index=start_col + relative_col_index,
                    booking_key=f"{sheet_name}|{absolute_row_index}|{start_col + relative_col_index}",
                    value=value,
                    student_id=student.student_id if student else "",
                    student_name=student.student_name if student else "",
                    background_bookable=background_bookable,
                )
            )
    return results


def _normalize_date_label(raw_date: str, year: int) -> str:
    value = str(raw_date or "").strip()
    if not value:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value
    parts = value.split("/")
    if len(parts) != 2:
        return ""
    try:
        month = int(parts[0])
        day = int(parts[1])
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _looks_like_time_slot(value: str) -> bool:
    normalized = str(value or "").strip()
    if not normalized:
        return False
    return bool(_TIME_SLOT_SEPARATOR_RE.search(normalized))


def _parse_iso_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _safe_cell(rows: list[list[object]], row_index: int, col_index: int) -> str:
    if row_index < 0 or row_index >= len(rows):
        return ""
    return _safe_cell_value_from_row(rows[row_index], col_index)


def _safe_cell_value_from_row(row: list[object], col_index: int) -> str:
    if col_index < 0 or col_index >= len(row):
        return ""
    cell = row[col_index]
    if isinstance(cell, dict):
        return str(cell.get("value") or "")
    return str(cell or "")


def _safe_cell_background_style_from_row(row: list[object], col_index: int) -> dict | None:
    if col_index < 0 or col_index >= len(row):
        return None
    cell = row[col_index]
    if not isinstance(cell, dict):
        return None
    style = cell.get("backgroundColorStyle")
    return style if isinstance(style, dict) else None


def _is_background_bookable(background_color_style: dict | None) -> bool:
    if not background_color_style:
        return True
    rgb_color = background_color_style.get("rgbColor")
    if not isinstance(rgb_color, dict):
        return False
    tolerance = 0.001
    red = float(rgb_color.get("red", 0.0))
    green = float(rgb_color.get("green", 0.0))
    blue = float(rgb_color.get("blue", 0.0))
    alpha = float(rgb_color.get("alpha", 1.0))
    return (
        abs(red - 1.0) <= tolerance
        and abs(green - 1.0) <= tolerance
        and abs(blue - 1.0) <= tolerance
        and abs(alpha - 1.0) <= tolerance
    )


def _column_letter(index: int) -> str:
    result = ""
    current = index
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _parse_slot_range(slot_range: str) -> dict[str, int | str]:
    match = re.fullmatch(r"\s*([A-Z]+)(\d+):([A-Z]+)(\d+)\s*", str(slot_range or "").upper())
    if not match:
        return {
            "range_start_row": 1,
            "range_start_col": 1,
            "header_row": 1,
            "time_col": 1,
            "date_start_col": 1,
            "date_end_col": 6,
            "slot_start_row": 1,
            "slot_end_row": 20,
            "fetch_range": "A1:F20",
        }
    start_col_letters, start_row, end_col_letters, end_row = match.groups()
    range_start_col = _column_index(start_col_letters)
    range_start_row = int(start_row)
    date_end_col = _column_index(end_col_letters)
    slot_end_row = int(end_row)
    fetch_range = f"{start_col_letters}{start_row}:{end_col_letters}{end_row}"
    return {
        "range_start_row": range_start_row,
        "range_start_col": range_start_col,
        "header_row": range_start_row,
        "time_col": range_start_col,
        "date_start_col": range_start_col,
        "date_end_col": date_end_col,
        "slot_start_row": range_start_row,
        "slot_end_row": slot_end_row,
        "fetch_range": fetch_range,
    }


def _column_index(letters: str) -> int:
    result = 0
    for char in letters:
        result = result * 26 + (ord(char) - 64)
    return result


def _resolve_timezone(name: str):
    try:
        return ZoneInfo(name)
    except Exception:
        return TAIPEI_TZ


def _normalize_rows_for_slot_range(rows: list[list[str]], config: HomeworkDemoConfig) -> tuple[int, int, list[list[str]]]:
    start_row = max(config.range_start_row - 1, 0)
    start_col = max(config.range_start_col - 1, 0)
    range_height = max(config.slot_end_row - config.range_start_row + 1, 0)
    range_width = max(config.date_end_col - config.range_start_col + 1, 0)
    max_width = max((len(row) for row in rows), default=0)

    # Google Sheets `values.get/batchGet` on a bounded range returns rows already
    # relative to that range. In that case, do not slice again by absolute columns.
    is_range_relative = (
        start_row > 0 or start_col > 0
    ) and max_width <= range_width and len(rows) <= range_height

    if is_range_relative:
        return 0, 0, rows[:range_height]

    end_row_exclusive = min(len(rows), config.slot_end_row)
    sub_rows = [
        row[start_col:config.date_end_col] if start_col < len(row) else []
        for row in rows[start_row:end_row_exclusive]
    ]
    return start_row, start_col, sub_rows
