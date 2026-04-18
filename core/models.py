"""Pydantic data models for the queue system."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class QueueEntry:
    """A single entry in a queue."""

    id: int = 0
    user_id: str = ""
    queue_type: str = "regular"
    queue_number: int = 0
    join_time: str = ""
    cancel_time: str | None = None
    served_time: str | None = None
    served: bool = False
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    reminder_position: int | None = None
    reminder_sent: bool = False


@dataclass
class VipPurchase:
    """Record of a Buy-a-Coffee purchase."""

    id: int = 0
    user_id: str = ""
    platform: str = "line"
    coffee_id: str | None = None
    purchased_at: str = ""
    verified: bool = False


@dataclass
class QueueEvent:
    """Event log entry."""

    id: int = 0
    event_type: str = ""
    user_id: str | None = None
    queue_type: str | None = None
    details: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class QueueStatus:
    """Aggregated queue status."""

    regular_count: int = 0
    regular_next: str = ""
    regular_head: str = ""
    vip_count: int = 0
    vip_next: str = ""
    vip_enabled: bool = True


@dataclass
class UserProfile:
    """Registered LINE user profile."""

    user_id: str = ""
    display_name: str = ""
    location: str = ""
    verified: bool = False
    role: str = "user"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

