"""SQLite database manager for queue system."""

from __future__ import annotations

import csv
import io
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Iterable, List, Optional

from .models import (
    AdminNotificationPreference,
    HomeworkCancelApplication,
    HomeworkUserProfile,
    QueueEntry,
    QueueEvent,
    UserProfile,
    VipPurchase,
)
from .time_utils import now_in_taipei


class DatabaseManager:
    """Manages SQLite database operations."""

    def __init__(self, db_path: str = "queue.db") -> None:
        self.db_path = db_path
        self.init_db()

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self) -> None:
        """Initialize database tables."""
        with self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    queue_type TEXT NOT NULL DEFAULT 'regular',
                    queue_number INTEGER NOT NULL,
                    join_time TEXT NOT NULL,
                    cancel_time TEXT,
                    served_time TEXT,
                    served INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vip_purchases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT UNIQUE NOT NULL,
                    platform TEXT NOT NULL DEFAULT 'line',
                    coffee_id TEXT,
                    purchased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    verified INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS queue_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    user_id TEXT,
                    queue_type TEXT,
                    details TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS server_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT '',
                    verified INTEGER NOT NULL DEFAULT 0,
                    role TEXT NOT NULL DEFAULT 'user',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS homework_user_profiles (
                    user_id TEXT PRIMARY KEY,
                    student_id TEXT NOT NULL,
                    student_name TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS homework_cancel_applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    student_user_id TEXT NOT NULL,
                    student_id TEXT NOT NULL,
                    student_name TEXT NOT NULL,
                    booking_key TEXT NOT NULL,
                    sheet_name TEXT NOT NULL,
                    booking_date TEXT NOT NULL,
                    time_slot TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    review_reason TEXT NOT NULL DEFAULT '',
                    reviewed_by TEXT NOT NULL DEFAULT '',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_homework_cancel_applications_status
                ON homework_cancel_applications(status, booking_key)
            """)
            defaults = [
                ("queue_max_capacity", "50"),
                ("queue_timeout_minutes", "30"),
                ("queue_enabled", "true"),
                ("vip_enabled", "true"),
                ("coffee_price", "60"),
            ]
            for key, val in defaults:
                conn.execute(
                    "INSERT OR IGNORE INTO server_config (key, value) VALUES (?, ?)",
                    (key, val),
                )
            conn.commit()

        self._migrate_queues_remove_user_unique()
        self._migrate_user_profiles_add_location()
        self._migrate_admin_applications()
        self._migrate_admin_notification_preferences()
        self._migrate_queues_add_release_time()

    def _migrate_queues_remove_user_unique(self) -> None:
        """Remove legacy UNIQUE constraint on queues.user_id so users can rejoin later."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'queues'"
            ).fetchone()
            create_sql = (row["sql"] or "") if row else ""
            normalized = " ".join(create_sql.lower().split())
            if "user_id text unique not null" not in normalized:
                return

            conn.execute("ALTER TABLE queues RENAME TO queues_legacy")
            conn.execute("""
                CREATE TABLE queues (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    queue_type TEXT NOT NULL DEFAULT 'regular',
                    queue_number INTEGER NOT NULL,
                    join_time TEXT NOT NULL,
                    cancel_time TEXT,
                    served_time TEXT,
                    served INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute(
                "INSERT INTO queues (id, user_id, queue_type, queue_number, join_time, cancel_time, served_time, served, created_at) "
                "SELECT id, user_id, queue_type, queue_number, join_time, cancel_time, served_time, served, created_at FROM queues_legacy"
            )
            conn.execute("DROP TABLE queues_legacy")
            conn.commit()

    def _migrate_queues_add_release_time(self) -> None:
        """Add release_time column to queues table for the 'called but not yet released' state."""
        with self._connection() as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(queues)").fetchall()]
            if "release_time" not in columns:
                conn.execute("ALTER TABLE queues ADD COLUMN release_time TEXT")
                conn.commit()

    def _migrate_user_profiles_add_location(self) -> None:
        """Ensure user_profiles has a location column."""
        with self._connection() as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(user_profiles)").fetchall()]
            if "location" not in columns:
                conn.execute("ALTER TABLE user_profiles ADD COLUMN location TEXT NOT NULL DEFAULT ''")
                conn.commit()

    def _migrate_admin_applications(self) -> None:
        """Ensure admin_applications table exists."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'admin_applications'"
            ).fetchone()
            if row is not None:
                return
            conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_applications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    applied_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    reviewed_by TEXT,
                    reviewed_at TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_admin_app_status
                ON admin_applications(status)
            """)
            conn.commit()

    def _migrate_admin_notification_preferences(self) -> None:
        """Ensure per-admin Telegram notification preference table exists."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'admin_notification_preferences'"
            ).fetchone()
            if row is not None:
                return
            conn.execute("""
                CREATE TABLE IF NOT EXISTS admin_notification_preferences (
                    user_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, category)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_admin_notify_category_enabled
                ON admin_notification_preferences(category, enabled)
            """)
            conn.commit()

    def get_config(self, key: str) -> Optional[str]:
        """Get a config value by key."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT value FROM server_config WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else None

    def set_config(self, key: str, value: str) -> None:
        """Set or update a config value."""
        with self._connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO server_config (key, value, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP)",
                (key, value),
            )
            conn.commit()

    def get_queue_max_capacity(self) -> int | None:
        """Get queue max capacity from config."""
        val = self.get_config("queue_max_capacity")
        return int(val) if val else None

    def get_queue_timeout_minutes(self) -> int | None:
        """Get timeout minutes from config."""
        val = self.get_config("queue_timeout_minutes")
        return int(val) if val else None

    def is_queue_enabled(self) -> bool:
        """Check if queue joining is enabled."""
        val = self.get_config("queue_enabled")
        return val.lower() == "true" if val else True

    def is_vip_enabled(self) -> bool:
        """Check if VIP queue is enabled."""
        val = self.get_config("vip_enabled")
        return val.lower() == "true" if val else True

    def get_active_queue_entry(self, user_id: str) -> Optional[QueueEntry]:
        """Get active queue entry for user, if any.

        Returns an entry if the user is either:
        - Still waiting in the queue (served=0, no cancel_time)
        - Already called but not yet released (served=1, served_time set, release_time IS NULL)
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM queues WHERE user_id = ? "
                "AND cancel_time IS NULL "
                "AND (served = 0 OR (served = 1 AND served_time IS NOT NULL AND release_time IS NULL)) "
                "ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            return QueueEntry(**dict(row))

    def get_called_entry(self, user_id: str) -> Optional[QueueEntry]:
        """Get the entry for a user that has been called but not yet released."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM queues WHERE user_id = ? "
                "AND served = 1 AND served_time IS NOT NULL "
                "AND release_time IS NULL AND cancel_time IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            return QueueEntry(**dict(row))

    def join_queue(self, user_id: str, queue_type: str = "regular") -> QueueEntry:
        """Add user to queue. Returns new QueueEntry."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COALESCE(MAX(queue_number), 0) + 1 AS next_num "
                "FROM queues WHERE queue_type = ? AND served = 0",
                (queue_type,),
            ).fetchone()
            queue_number = row["next_num"]
            join_time = now_in_taipei().isoformat()
            try:
                conn.execute(
                    "INSERT INTO queues (user_id, queue_type, queue_number, join_time) "
                    "VALUES (?, ?, ?, ?)",
                    (user_id, queue_type, queue_number, join_time),
                )
                conn.commit()
                return QueueEntry(
                    id=0,
                    user_id=user_id,
                    queue_type=queue_type,
                    queue_number=queue_number,
                    join_time=join_time,
                )
            except sqlite3.IntegrityError:
                # User already in queue — return existing entry
                existing = conn.execute(
                    "SELECT * FROM queues WHERE user_id = ? AND served = 0",
                    (user_id,),
                ).fetchone()
                if existing is None:
                    raise
                return QueueEntry(
                    id=existing["id"],
                    user_id=existing["user_id"],
                    queue_type=existing["queue_type"],
                    queue_number=existing["queue_number"],
                    join_time=existing["join_time"],
                    cancel_time=existing["cancel_time"],
                    served_time=existing["served_time"],
                    served=existing["served"],
                )

    def cancel_queue(self, user_id: str) -> Optional[QueueEntry]:
        """Cancel user's queue entry. Returns updated QueueEntry or None."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM queues WHERE user_id = ? AND served = 0 "
                "AND cancel_time IS NULL",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            cancel_time = now_in_taipei().isoformat()
            conn.execute(
                "UPDATE queues SET cancel_time = ?, served = 1 WHERE user_id = ?",
                (cancel_time, user_id),
            )
            conn.commit()
            return QueueEntry(
                id=row["id"],
                user_id=row["user_id"],
                queue_type=row["queue_type"],
                queue_number=row["queue_number"],
                join_time=row["join_time"],
                cancel_time=cancel_time,
            )

    def serve_queue(self, user_id: str) -> Optional[QueueEntry]:
        """Mark user as served. Returns updated QueueEntry or None."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM queues WHERE user_id = ? AND served = 0",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            served_time = now_in_taipei().isoformat()
            conn.execute(
                "UPDATE queues SET served = 1, served_time = ? WHERE user_id = ?",
                (served_time, user_id),
            )
            conn.commit()
            return QueueEntry(
                id=row["id"],
                user_id=row["user_id"],
                queue_type=row["queue_type"],
                queue_number=row["queue_number"],
                join_time=row["join_time"],
                served_time=served_time,
                served=True,
            )

    def release_queue(self, user_id: str) -> Optional[QueueEntry]:
        """Release a user that was called but hasn't been released yet.

        This marks the queue entry as fully completed by setting release_time.
        After this, the user is free to join the queue again.
        Returns the updated QueueEntry, or None if no matching entry found.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM queues WHERE user_id = ? "
                "AND served = 1 AND served_time IS NOT NULL "
                "AND release_time IS NULL AND cancel_time IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            release_time = now_in_taipei().isoformat()
            conn.execute(
                "UPDATE queues SET release_time = ? WHERE id = ?",
                (release_time, row["id"]),
            )
            conn.commit()
            return QueueEntry(
                id=row["id"],
                user_id=row["user_id"],
                queue_type=row["queue_type"],
                queue_number=row["queue_number"],
                join_time=row["join_time"],
                served_time=row["served_time"],
                served=True,
            )

    def get_called_queue(self) -> list:
        """Get all entries that have been called but not yet released."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM queues "
                "WHERE served = 1 AND served_time IS NOT NULL "
                "AND release_time IS NULL AND cancel_time IS NULL "
                "ORDER BY served_time ASC"
            ).fetchall()
            return [QueueEntry(**dict(r)) for r in rows]

    def find_called_user_by_location(self, location: str) -> Optional[QueueEntry]:
        """Find a called-but-not-released queue entry by the user's location."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT q.* FROM queues q "
                "JOIN user_profiles up ON q.user_id = up.user_id "
                "WHERE q.served = 1 AND q.served_time IS NOT NULL "
                "AND q.release_time IS NULL AND q.cancel_time IS NULL "
                "AND up.location = ? "
                "ORDER BY q.served_time ASC LIMIT 1",
                (location,),
            ).fetchone()
            if row is None:
                return None
            return QueueEntry(**dict(row))

    def find_user_profile_by_location(self, location: str) -> Optional["UserProfile"]:
        """Find a registered user profile by location."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE location = ? LIMIT 1",
                (location,),
            ).fetchone()
            if row is None:
                return None
            return UserProfile(**dict(row))

    def force_release_queue(self, user_id: str) -> Optional[QueueEntry]:
        """Force release the most recent active queue entry for a user, regardless of served state.

        Unlike release_queue(), this does NOT require served=1. It will set release_time on
        whatever the most recent non-cancelled, non-released entry is. Also ensures served=1
        and served_time is set so the entry is treated as completed.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM queues WHERE user_id = ? "
                "AND release_time IS NULL AND cancel_time IS NULL "
                "ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            now = now_in_taipei().isoformat()
            conn.execute(
                "UPDATE queues SET release_time = ?, served = 1, served_time = COALESCE(served_time, ?) WHERE id = ?",
                (now, now, row["id"]),
            )
            conn.commit()
            return QueueEntry(
                id=row["id"],
                user_id=row["user_id"],
                queue_type=row["queue_type"],
                queue_number=row["queue_number"],
                join_time=row["join_time"],
                served_time=row["served_time"] or now,
                served=True,
            )

    def skip_queue(self, user_id: str) -> Optional[QueueEntry]:
        """Skip (cancel) user's queue without serving."""
        return self.cancel_queue(user_id)

    def get_regular_queue(self) -> list:
        """Get all active regular queue entries."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM queues WHERE queue_type = 'regular' AND served = 0 "
                "AND cancel_time IS NULL ORDER BY join_time ASC"
            ).fetchall()
            return [QueueEntry(**dict(r)) for r in rows]

    def get_vip_queue(self) -> list:
        """Get all active VIP queue entries."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM queues WHERE queue_type = 'vip' AND served = 0 "
                "AND cancel_time IS NULL ORDER BY join_time ASC"
            ).fetchall()
            return [QueueEntry(**dict(r)) for r in rows]

    def get_all_queue(self) -> list:
        """Get all active queue entries (regular + vip)."""
        return self.get_regular_queue() + self.get_vip_queue()

    def clear_all_queue(self) -> list[QueueEntry]:
        """Cancel all active queue entries and return removed items."""
        removed = []
        for entry in list(self.get_all_queue()):
            cancelled = self.cancel_queue(entry.user_id)
            if cancelled is not None:
                removed.append(cancelled)
        return removed
    
    def clear_all_admin_applications(self) -> int:
        """Delete all admin applications."""
        with self._connection() as conn:
            result = conn.execute("DELETE FROM admin_applications")
            conn.commit()
            return result.rowcount

    def clear_served_queue(self) -> int:
        """Delete all served or cancelled queue records."""
        with self._connection() as conn:
            result = conn.execute(
                "DELETE FROM queues WHERE served = 1 OR cancel_time IS NOT NULL OR served_time IS NOT NULL"
            )
            conn.commit()
            return result.rowcount

    def clear_all_queue_records(self) -> int:
        """Delete all queue records regardless of state."""
        with self._connection() as conn:
            result = conn.execute("DELETE FROM queues")
            conn.commit()
            return result.rowcount

    def upsert_user_profile(
        self,
        user_id: str,
        display_name: str,
        location: str = "",
        verified: bool = False,
        role: str = "user",
    ) -> UserProfile:
        """Create or update a user profile."""
        now = datetime.now().isoformat(timespec="microseconds")
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO user_profiles (user_id, display_name, location, verified, role, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "display_name = excluded.display_name, "
                "location = CASE WHEN excluded.location != '' THEN excluded.location ELSE user_profiles.location END, "
                "verified = CASE WHEN excluded.verified = 1 THEN 1 ELSE user_profiles.verified END, "
                "role = CASE "
                "WHEN user_profiles.role = 'admin' THEN 'admin' "
                "WHEN excluded.role != '' THEN excluded.role "
                "ELSE user_profiles.role END, "
                "updated_at = excluded.updated_at",
                (user_id, display_name, location, 1 if verified else 0, role, now, now),
            )
            conn.commit()
        profile = self.get_user_profile(user_id)
        assert profile is not None
        return profile

    def get_user_profile(self, user_id: str) -> Optional[UserProfile]:
        """Get user profile by LINE user ID."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return UserProfile(**dict(row)) if row else None

    def verify_user_profile(self, user_id: str, verified: bool = True) -> Optional[UserProfile]:
        """Mark a user profile as verified/unverified."""
        now = datetime.now().isoformat(timespec="microseconds")
        with self._connection() as conn:
            conn.execute(
                "UPDATE user_profiles SET verified = ?, updated_at = ? WHERE user_id = ?",
                (1 if verified else 0, now, user_id),
            )
            conn.commit()
        return self.get_user_profile(user_id)

    def get_display_name(self, user_id: str) -> str:
        """Resolve display name for status/admin output."""
        profile = self.get_user_profile(user_id)
        if profile and profile.display_name:
            if profile.location:
                return f"{profile.display_name}（{profile.location}）"
            return profile.display_name
        return user_id

    def upsert_homework_user_profile(
        self,
        user_id: str,
        student_id: str,
        student_name: str,
    ) -> HomeworkUserProfile:
        """Create or update the homework-specific user binding."""
        now = datetime.now().isoformat(timespec="microseconds")
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO homework_user_profiles (user_id, student_id, student_name, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET "
                "student_id = excluded.student_id, "
                "student_name = excluded.student_name, "
                "updated_at = excluded.updated_at",
                (user_id, student_id, student_name, now, now),
            )
            conn.commit()
        profile = self.get_homework_user_profile(user_id)
        assert profile is not None
        return profile

    def get_homework_user_profile(self, user_id: str) -> Optional[HomeworkUserProfile]:
        """Get homework-specific profile by LINE user id."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM homework_user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return HomeworkUserProfile(**dict(row)) if row else None

    def create_homework_cancel_application(
        self,
        *,
        student_user_id: str,
        student_id: str,
        student_name: str,
        booking_key: str,
        sheet_name: str,
        booking_date: str,
        time_slot: str,
        reason: str,
    ) -> HomeworkCancelApplication | None:
        """Create one pending late-cancel application unless one already exists."""
        cleaned_reason = str(reason or "").strip()
        if not cleaned_reason:
            return None
        now = now_in_taipei().isoformat()
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT * FROM homework_cancel_applications "
                "WHERE booking_key = ? AND status = 'pending' "
                "ORDER BY id DESC LIMIT 1",
                (booking_key,),
            ).fetchone()
            if existing is not None:
                return None
            cursor = conn.execute(
                "INSERT INTO homework_cancel_applications ("
                "student_user_id, student_id, student_name, booking_key, sheet_name, booking_date, time_slot, reason, status, review_reason, reviewed_by, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', '', '', ?)",
                (student_user_id, student_id, student_name, booking_key, sheet_name, booking_date, time_slot, cleaned_reason, now),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM homework_cancel_applications WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
        return HomeworkCancelApplication(**dict(row)) if row else None

    def get_homework_cancel_application(self, application_id: int) -> dict | None:
        """Get one homework cancel application by id."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM homework_cancel_applications WHERE id = ?",
                (application_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_pending_homework_cancel_applications(self) -> list[dict]:
        """List all pending homework cancel applications."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM homework_cancel_applications WHERE status = 'pending' ORDER BY id ASC"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_pending_homework_cancel_application_by_booking_key(self, booking_key: str) -> dict | None:
        """Get pending application for a booking, if any."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM homework_cancel_applications "
                "WHERE booking_key = ? AND status = 'pending' "
                "ORDER BY id DESC LIMIT 1",
                (booking_key,),
            ).fetchone()
            return dict(row) if row else None

    def approve_homework_cancel_application(self, application_id: int, reviewed_by: str) -> dict | None:
        """Mark a pending application as approved."""
        now = now_in_taipei().isoformat()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM homework_cancel_applications WHERE id = ? AND status = 'pending'",
                (application_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE homework_cancel_applications "
                "SET status = 'approved', reviewed_by = ?, reviewed_at = ? "
                "WHERE id = ?",
                (reviewed_by, now, application_id),
            )
            conn.commit()
        return self.get_homework_cancel_application(application_id)

    def reject_homework_cancel_application(self, application_id: int, reviewed_by: str, review_reason: str) -> dict | None:
        """Mark a pending application as rejected with reason."""
        cleaned_reason = str(review_reason or "").strip()
        if not cleaned_reason:
            return None
        now = now_in_taipei().isoformat()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM homework_cancel_applications WHERE id = ? AND status = 'pending'",
                (application_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE homework_cancel_applications "
                "SET status = 'rejected', review_reason = ?, reviewed_by = ?, reviewed_at = ? "
                "WHERE id = ?",
                (cleaned_reason, reviewed_by, now, application_id),
            )
            conn.commit()
        return self.get_homework_cancel_application(application_id)

    def mark_homework_cancel_application_invalid(
        self,
        application_id: int,
        *,
        reviewed_by: str,
        review_reason: str,
    ) -> dict | None:
        """Mark an application invalid when its booking can no longer be processed."""
        cleaned_reason = str(review_reason or "").strip() or "申請已失效"
        now = now_in_taipei().isoformat()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM homework_cancel_applications WHERE id = ? AND status = 'pending'",
                (application_id,),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE homework_cancel_applications "
                "SET status = 'invalid', review_reason = ?, reviewed_by = ?, reviewed_at = ? "
                "WHERE id = ?",
                (cleaned_reason, reviewed_by, now, application_id),
            )
            conn.commit()
        return self.get_homework_cancel_application(application_id)

    def get_verified_profiles(self) -> list[UserProfile]:
        """List verified user profiles."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM user_profiles WHERE verified = 1 ORDER BY updated_at DESC, user_id ASC"
            ).fetchall()
            return [UserProfile(**dict(r)) for r in rows]

    def get_all_user_profiles(self) -> list[UserProfile]:
        """List all registered user profiles."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM user_profiles ORDER BY location ASC, display_name ASC, user_id ASC"
            ).fetchall()
            return [UserProfile(**dict(r)) for r in rows]

    def get_latest_queue_entry_for_user(self, user_id: str) -> Optional[QueueEntry]:
        """Get the latest queue record for a user."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM queues WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            return QueueEntry(**dict(row)) if row else None

    def clear_all_user_profiles(self, keep_user_ids: Iterable[str] | None = None) -> tuple[int, int]:
        """Delete registered user profiles while preserving admin roles.

        All profiles with role='admin' are retained so admin authorization keeps
        working, but their dashboard-visible registration fields are cleared.
        Non-admin profiles are deleted.

        Returns:
            (cleared_count, kept_admin_count)
        """
        _ = {str(user_id) for user_id in (keep_user_ids or set()) if str(user_id).strip()}  # backward-compatible noop
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT user_id, role FROM user_profiles"
            ).fetchall()

            cleared_count = 0
            kept_admin_count = 0
            now = datetime.now().isoformat(timespec="microseconds")
            for row in rows:
                user_id = row["user_id"]
                role = row["role"]
                if role == "admin":
                    conn.execute(
                        "UPDATE user_profiles SET display_name = '', location = '', verified = 0, updated_at = ? WHERE user_id = ?",
                        (now, user_id),
                    )
                    kept_admin_count += 1
                    continue
                conn.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))
                cleared_count += 1

            conn.commit()
            return cleared_count, kept_admin_count

    def get_user_history(self, user_id: str) -> list:
        """Get queue history for a user, newest first."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT user_id, queue_type, queue_number, join_time, cancel_time, served_time, served "
                "FROM queues WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                (user_id,),
            ).fetchall()

            history = []
            for row in rows:
                if row["served_time"]:
                    status = "served"
                    time_value = row["served_time"]
                elif row["cancel_time"]:
                    status = "cancelled"
                    time_value = row["cancel_time"]
                elif row["served"]:
                    status = "closed"
                    time_value = row["join_time"]
                else:
                    status = "active"
                    time_value = row["join_time"]

                history.append(
                    SimpleNamespace(
                        user_id=row["user_id"],
                        queue_type=row["queue_type"],
                        queue_number=row["queue_number"],
                        status=status,
                        time=time_value,
                    )
                )
            return history

    def add_admin_application(self, user_id: str, display_name: str) -> dict:
        """Submit an admin application. Returns {status, message}."""
        display_name = display_name.strip()
        if not display_name:
            return {"status": "error", "message": "display name cannot be empty."}
        with self._connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO admin_applications (user_id, display_name, status) "
                    "VALUES (?, ?, 'pending')",
                    (user_id, display_name),
                )
                conn.commit()
                return {"status": "success", "message": "Application submitted."}
            except sqlite3.IntegrityError:
                return {"status": "duplicate", "message": "Duplicate application."}

    def get_pending_applications(self) -> list[dict]:
        """Get all pending admin applications ordered by applied_at DESC."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT user_id, display_name, status, applied_at, reviewed_by, reviewed_at "
                "FROM admin_applications WHERE status = 'pending' "
                "ORDER BY applied_at DESC, id ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_pending_applications_for_review(self, line_display_name_resolver=None) -> list[dict]:
        """Get pending admin applications with display names resolved for review UIs."""
        pending = self.get_pending_applications()
        items: list[dict] = []
        for app in pending:
            user_id = str(app.get("user_id") or "").strip()
            line_display_name = ""
            if callable(line_display_name_resolver) and user_id:
                try:
                    line_display_name = str(line_display_name_resolver(user_id) or "").strip()
                except Exception:
                    line_display_name = ""
            application_display_name = str(app.get("display_name") or "").strip()
            profile = self.get_user_profile(user_id) if user_id else None
            profile_display_name = str(getattr(profile, "display_name", "") or "").strip()
            resolved_display_name = line_display_name or application_display_name or profile_display_name or user_id
            items.append(
                {
                    **app,
                    "application_display_name": application_display_name,
                    "line_display_name": line_display_name,
                    "profile_display_name": profile_display_name,
                    "resolved_display_name": resolved_display_name,
                }
            )
        return items

    def get_pending_count(self) -> int:
        """Count pending admin applications."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM admin_applications WHERE status = 'pending'"
            ).fetchone()
            return int(row["cnt"])

    def approve_admin_application(self, user_id: str, reviewed_by: str) -> dict:
        """Approve an admin application. Returns {status, message}."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id FROM admin_applications WHERE user_id = ? AND status = 'pending' LIMIT 1",
                (user_id,),
            ).fetchone()
            if row is None:
                return {"status": "error", "message": "Application not found or already processed."}
            now = now_in_taipei().isoformat()
            conn.execute(
                "UPDATE admin_applications SET status = 'approved', reviewed_by = ?, reviewed_at = ? WHERE user_id = ?",
                (reviewed_by, now, user_id),
            )
            conn.commit()
            # Update user_profiles role to admin
            self.upsert_user_profile(user_id, "", verified=False, role="admin")
            return {"status": "success", "message": "Application approved."}

    def reject_admin_application(self, user_id: str, reviewed_by: str) -> dict:
        """Reject an admin application. Returns {status, message}."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT id FROM admin_applications WHERE user_id = ? AND status = 'pending' LIMIT 1",
                (user_id,),
            ).fetchone()
            if row is None:
                return {"status": "error", "message": "Application not found or already processed."}
            now = now_in_taipei().isoformat()
            conn.execute(
                "UPDATE admin_applications SET status = 'rejected', reviewed_by = ?, reviewed_at = ? WHERE user_id = ?",
                (reviewed_by, now, user_id),
            )
            conn.commit()
            return {"status": "success", "message": "Application rejected."}

    def is_admin(self, user_id: str) -> bool:
        """Check if a user has admin role in user_profiles."""
        profile = self.get_user_profile(user_id)
        return profile is not None and getattr(profile, "role", "") == "admin"

    def get_all_admins(self) -> list[dict]:
        """Get all approved admins (from user_profiles with role='admin')."""
        profiles = self.get_all_user_profiles()
        return [
            {"user_id": p.user_id, "display_name": p.display_name}
            for p in profiles
            if getattr(p, "role", "") == "admin"
        ]

    def get_admin_notification_preferences(self, user_id: str) -> dict[str, bool]:
        """Get all Telegram notification preferences for one admin.

        Missing categories default to False.
        """
        from services.telegram_admin_notifications import TELEGRAM_NOTIFICATION_CATEGORIES

        prefs = {category: False for category in TELEGRAM_NOTIFICATION_CATEGORIES}
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT category, enabled FROM admin_notification_preferences WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        for row in rows:
            category = row["category"]
            if category in prefs:
                prefs[category] = bool(row["enabled"])
        return prefs

    def set_admin_notification_preference(self, user_id: str, category: str, enabled: bool) -> AdminNotificationPreference:
        """Upsert one Telegram notification preference for an admin."""
        from services.telegram_admin_notifications import TELEGRAM_NOTIFICATION_CATEGORIES

        if category not in TELEGRAM_NOTIFICATION_CATEGORIES:
            raise ValueError(f"Unknown notification category: {category}")
        now = datetime.now().isoformat(timespec="microseconds")
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO admin_notification_preferences (user_id, category, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id, category) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at",
                (user_id, category, 1 if enabled else 0, now, now),
            )
            conn.commit()
        return AdminNotificationPreference(user_id=user_id, category=category, enabled=enabled, created_at=now, updated_at=now)

    def set_all_admin_notification_preferences(self, user_id: str, enabled: bool) -> dict[str, bool]:
        """Set every Telegram notification category for one admin."""
        from services.telegram_admin_notifications import TELEGRAM_NOTIFICATION_CATEGORIES

        for category in TELEGRAM_NOTIFICATION_CATEGORIES:
            self.set_admin_notification_preference(user_id, category, enabled)
        return self.get_admin_notification_preferences(user_id)

    def get_admins_to_notify(self, category: str) -> list[str]:
        """Return admin user_ids that enabled the given Telegram notification category."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT p.user_id "
                "FROM admin_notification_preferences p "
                "JOIN user_profiles u ON u.user_id = p.user_id "
                "WHERE p.category = ? AND p.enabled = 1 AND u.role = 'admin' "
                "ORDER BY p.user_id ASC",
                (category,),
            ).fetchall()
        return [row["user_id"] for row in rows]

    def get_event_history(self, user_id: str, limit: int = 20) -> list[QueueEvent]:
        """Get queue event history for a user, newest first."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM queue_events WHERE user_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [QueueEvent(**dict(r)) for r in rows]

    def get_vip_purchases(self) -> list:
        """Get all VIP purchase records."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM vip_purchases ORDER BY purchased_at DESC"
            ).fetchall()
            return [VipPurchase(**dict(r)) for r in rows]

    def add_vip_purchase(
        self,
        user_id: str,
        platform: str = "line",
        coffee_id: Optional[str] = None,
        verified: bool = False,
    ) -> VipPurchase:
        """Record a VIP purchase. Raises IntegrityError on duplicate."""
        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO vip_purchases (user_id, platform, coffee_id, purchased_at, verified) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)",
                (user_id, platform, coffee_id, 1 if verified else 0),
            )
            inserted = conn.total_changes
            if inserted == 0:
                raise sqlite3.IntegrityError(
                    f"Duplicate vip_purchase for user_id={user_id}"
                )
            conn.commit()
            return VipPurchase(
                user_id=user_id,
                platform=platform,
                coffee_id=coffee_id,
                verified=verified,
            )

    def is_vip_purchased(self, user_id: str) -> bool:
        """Check if user has made a VIP purchase."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM vip_purchases WHERE user_id = ? AND verified = 1 LIMIT 1",
                (user_id,),
            ).fetchone()
            return row is not None

    def log_event(
        self, event_type: str, user_id: Optional[str] = None,
        queue_type: Optional[str] = None, details: str = ""
    ) -> QueueEvent:
        """Log a queue event."""
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO queue_events (event_type, user_id, queue_type, details) "
                "VALUES (?, ?, ?, ?)",
                (event_type, user_id, queue_type, details),
            )
            conn.commit()
            return QueueEvent(
                event_type=event_type, user_id=user_id,
                queue_type=queue_type, details=details
            )

    def get_queue_rows_for_export(self, limit: int = 20) -> list[dict]:
        """Get recent queue rows for export/reporting."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT user_id, queue_type, queue_number, join_time, cancel_time, "
                "served_time, served FROM queues ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_recent_served(self, limit: int = 5) -> list[dict]:
        """Get recently served queue rows, newest first."""
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT q.user_id,
                       q.queue_type,
                       q.served_time,
                       up.display_name,
                       up.location
                FROM queues q
                LEFT JOIN user_profiles up ON up.user_id = q.user_id
                WHERE q.served = 1 AND q.served_time IS NOT NULL
                ORDER BY q.served_time DESC, q.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def export_queue_csv(self, limit: int = 20) -> str:
        """Export recent queue rows as CSV text."""
        rows = self.get_queue_rows_for_export(limit=limit)
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "user_id",
                "queue_type",
                "queue_number",
                "join_time",
                "cancel_time",
                "served_time",
                "served",
            ],
        )
        writer.writeheader()
        for row in reversed(rows):
            writer.writerow(row)
        return output.getvalue().strip()
