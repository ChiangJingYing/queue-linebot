"""Queue manager - core queue business logic."""

from __future__ import annotations

from typing import Optional

from .database import DatabaseManager
from .models import QueueEntry
from .validators import validate_user_id


class QueueManager:
    """Manages queue operations (join, cancel, serve, skip)."""

    def __init__(self, db: DatabaseManager | None = None) -> None:
        self.db = db or DatabaseManager()

    # -- join --

    def join(self, user_id: str, queue_type: str = "regular") -> dict:
        """Add user to queue. Returns status dict."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "Invalid user ID."}

        if queue_type == "vip":
            if not self.db.is_vip_enabled():
                return {"status": "error", "message": "VIP queue is disabled."}
            if not self.db.is_vip_purchased(valid_id):
                return {"status": "error", "message": "No VIP purchase found. Please buy coffee first."}

        entry = self.db.join_queue(valid_id, queue_type)

        if queue_type == "regular":
            max_cap = self.db.get_queue_max_capacity()
            if len(self.db.get_regular_queue()) >= max_cap:
                self.db.cancel_queue(valid_id)
                return {"status": "error", "message": "Queue is full."}

        self.db.log_event("join", valid_id, queue_type)

        return {
            "status": "success",
            "queue_number": entry.queue_number,
            "position": len(self.db.get_all_queue()) - len(
                [e for e in self.db.get_all_queue() if e.queue_number > entry.queue_number]
            ),
            "total_in_queue": len(self.db.get_all_queue()),
        }

    # -- cancel --

    def cancel(self, user_id: str) -> dict:
        """Cancel user's queue entry."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "Invalid user ID."}

        entry = self.db.cancel_queue(valid_id)
        if entry is None:
            return {"status": "error", "message": "Not in queue."}

        self.db.log_event("cancel", valid_id, entry.queue_type)

        return {
            "status": "cancelled",
            "id": valid_id,
            "removed_position": entry.queue_number,
            "new_total": len(self.db.get_all_queue()),
        }

    # -- serve --

    def serve_next(self) -> dict:
        """Serve head of queue."""
        all_q = self.db.get_all_queue()
        if not all_q:
            return {"status": "error", "message": "Queue is empty."}

        head = all_q[0]
        served = self.db.serve_queue(head.user_id)
        if served is None:
            return {"status": "error", "message": "Failed to serve."}

        self.db.log_event("serve", head.user_id, head.queue_type)

        return {"status": "served", "id": head.user_id, "queue_number": head.queue_number}

    def serve_specific(self, user_id: str) -> dict:
        """Serve a specific user."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "Invalid user ID."}

        served = self.db.serve_queue(valid_id)
        if served is None:
            return {"status": "error", "message": "Not in queue."}

        self.db.log_event("serve", valid_id, served.queue_type)

        return {"status": "served", "id": valid_id, "queue_number": served.queue_number}

    # -- skip --

    def skip_next(self) -> dict:
        """Skip head of queue."""
        all_q = self.db.get_all_queue()
        if not all_q:
            return {"status": "error", "message": "Queue is empty."}

        head = all_q[0]
        skipped = self.db.skip_queue(head.user_id)
        if skipped is None:
            return {"status": "error", "message": "Failed to skip."}

        self.db.log_event("skip", head.user_id, head.queue_type)

        return {"status": "skipped", "id": head.user_id, "queue_number": head.queue_number}

    def skip_specific(self, user_id: str) -> dict:
        """Skip a specific user."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "Invalid user ID."}

        skipped = self.db.skip_queue(valid_id)
        if skipped is None:
            return {"status": "error", "message": "Not in queue."}

        self.db.log_event("skip", valid_id, skipped.queue_type)

        return {"status": "skipped", "id": valid_id, "queue_number": skipped.queue_number}

    # -- status --

    def get_status(self) -> dict:
        """Get aggregated queue status."""
        regular = self.db.get_regular_queue()
        vip = self.db.get_vip_queue()

        reg_head = regular[0].user_id if regular else ""
        vip_head = vip[0].user_id if vip else ""

        return {
            "regular_count": len(regular),
            "regular_next": f"user_{reg_head}" if reg_head else "",
            "regular_head": f"user_{reg_head}" if reg_head else "",
            "vip_count": len(vip),
            "vip_next": f"user_{vip_head}" if vip_head else "",
            "vip_enabled": self.db.is_vip_enabled(),
        }

    def get_queue(self) -> list:
        """Get full queue list (admin view)."""
        return self.db.get_all_queue()

    # -- config --

    def set_max_capacity(self, n: int) -> dict:
        """Set max queue capacity."""
        self.db.set_config("queue_max_capacity", str(n))
        return {"status": "ok", "max_capacity": n}

    def get_max_capacity(self) -> int:
        """Get max queue capacity."""
        return self.db.get_queue_max_capacity()
