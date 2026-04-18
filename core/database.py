"""SQLite database manager for queue system."""

from __future__ import annotations

import csv
import io
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import List, Optional

from .models import QueueEntry, VipPurchase, QueueEvent, UserProfile


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
            defaults = [
                ("queue_max_capacity", "50"),
                ("queue_timeout_minutes", "30"),
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

    def _migrate_user_profiles_add_location(self) -> None:
        """Ensure user_profiles has a location column."""
        with self._connection() as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(user_profiles)").fetchall()]
            if "location" not in columns:
                conn.execute("ALTER TABLE user_profiles ADD COLUMN location TEXT NOT NULL DEFAULT ''")
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

    def get_queue_max_capacity(self) -> int:
        """Get queue max capacity from config."""
        val = self.get_config("queue_max_capacity")
        return int(val) if val else 50

    def get_queue_timeout_minutes(self) -> int:
        """Get timeout minutes from config."""
        val = self.get_config("queue_timeout_minutes")
        return int(val) if val else 30

    def is_vip_enabled(self) -> bool:
        """Check if VIP queue is enabled."""
        val = self.get_config("vip_enabled")
        return val.lower() == "true" if val else True

    def get_active_queue_entry(self, user_id: str) -> Optional[QueueEntry]:
        """Get active queue entry for user, if any."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM queues WHERE user_id = ? AND served = 0 AND cancel_time IS NULL LIMIT 1",
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
            join_time = datetime.now().isoformat()
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
            cancel_time = datetime.now().isoformat()
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
            served_time = datetime.now().isoformat()
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
                "role = CASE WHEN excluded.role != '' THEN excluded.role ELSE user_profiles.role END, "
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

    def clear_all_user_profiles(self) -> int:
        """Delete all registered user profiles."""
        with self._connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM user_profiles").fetchone()
            total = int(row["cnt"]) if row else 0
            conn.execute("DELETE FROM user_profiles")
            conn.commit()
            return total

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
