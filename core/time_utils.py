"""Shared time formatting helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

TAIPEI_TZ = timezone(timedelta(hours=8))


def now_in_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace(" ", "T"))
        except ValueError:
            return None


def format_display_time(value: str | None, *, include_date: bool = True) -> str:
    dt = parse_timestamp(value)
    if dt is None:
        return value or ""
    if dt.tzinfo is None:
        # 修正：如果沒有時區，假設它是本地/台北時間，而不是誤認為 UTC
        dt = dt.replace(tzinfo=TAIPEI_TZ)
    else:
        # 如果已有時區，則正確轉為台北時間
        dt = dt.astimezone(TAIPEI_TZ)
    return dt.strftime("%Y-%m-%d %H:%M" if include_date else "%H:%M")
