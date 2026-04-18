"""SQLite database manager for queue system."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import List, Optional

from .models import QueueEntry, VipPurchase, QueueEvent


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
                    user_id TEXT UNIQUE NOT NULL,
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

    def get_vip_purchases(self) -> list:
        """Get all VIP purchase records."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM vip_purchases ORDER BY purchased_at DESC"
            ).fetchall()
            return [VipPurchase(**dict(r)) for r in rows]

    def add_vip_purchase(
        self, user_id: str, platform: str = "line", coffee_id: Optional[str] = None
    ) -> VipPurchase:
        """Record a VIP purchase."""
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO vip_purchases (user_id, platform, coffee_id, purchased_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (user_id, platform, coffee_id),
            )
            conn.commit()
            return VipPurchase(
                user_id=user_id, platform=platform, coffee_id=coffee_id
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
