"""Queue manager - core queue business logic."""

from __future__ import annotations

from datetime import datetime

from .database import DatabaseManager
from .validators import validate_user_id


class QueueManager:
    """Manages queue operations (join, cancel, serve, skip)."""

    def __init__(
        self,
        db: DatabaseManager | None = None,
        notifier: object | None = None,
    ) -> None:
        self.db = db or DatabaseManager()
        self.notifier = notifier

    # -- join --

    def join(self, user_id: str, queue_type: str = "regular") -> dict:
        """Add user to queue. Returns status dict."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        existing = self.db.get_active_queue_entry(valid_id)
        if existing is not None:
            return {
                "status": "error",
                "message": f"你已在排隊中（號碼 #{existing.queue_number}），請勿重複加入。",
            }

        if queue_type == "vip":
            if not self.db.is_vip_enabled():
                return {"status": "error", "message": "VIP 隊列目前已停用。"}
            if not self.db.is_vip_purchased(valid_id):
                return {"status": "error", "message": "尚未找到 VIP 購買紀錄，請先購買咖啡。"}

        entry = self.db.join_queue(valid_id, queue_type)

        if queue_type == "regular":
            max_cap = self.db.get_queue_max_capacity()
            if len(self.db.get_regular_queue()) > max_cap:
                self.db.cancel_queue(valid_id)
                return {"status": "error", "message": "隊列已滿，請稍後再試。"}

        self.db.log_event("join", valid_id, queue_type)

        # Push notification to user
        if self.notifier:
            self.notifier.notify_join_success(valid_id, entry.queue_number)

        all_queue = self.db.get_all_queue()
        return {
            "status": "success",
            "queue_number": entry.queue_number,
            "position": len(all_queue) - len([e for e in all_queue if e.queue_number > entry.queue_number]),
            "total_in_queue": len(all_queue),
        }

    # -- cancel --

    def cancel(self, user_id: str) -> dict:
        """Cancel user's queue entry."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        entry = self.db.cancel_queue(valid_id)
        if entry is None:
            return {"status": "error", "message": "你目前不在隊列中。"}

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
            return {"status": "error", "message": "目前隊列是空的。"}

        head = all_q[0]
        served = self.db.serve_queue(head.user_id)
        if served is None:
            return {"status": "error", "message": "叫號失敗，請稍後再試。"}

        self.db.log_event("serve", head.user_id, head.queue_type)

        return {"status": "served", "id": head.user_id, "queue_number": served.queue_number}

    def serve_specific(self, user_id: str) -> dict:
        """Serve a specific user."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        served = self.db.serve_queue(valid_id)
        if served is None:
            return {"status": "error", "message": "該使用者目前不在隊列中。"}

        self.db.log_event("serve", valid_id, served.queue_type)

        return {"status": "served", "id": valid_id, "queue_number": served.queue_number}

    # -- skip --

    def skip_next(self) -> dict:
        """Skip head of queue."""
        all_q = self.db.get_all_queue()
        if not all_q:
            return {"status": "error", "message": "目前隊列是空的。"}

        head = all_q[0]
        skipped = self.db.skip_queue(head.user_id)
        if skipped is None:
            return {"status": "error", "message": "跳過失敗，請稍後再試。"}

        self.db.log_event("skip", head.user_id, head.queue_type)

        # Push notification to skipped user
        if self.notifier:
            self.notifier.notify_skip(head.user_id)

        return {"status": "skipped", "id": head.user_id, "queue_number": head.queue_number}

    def skip_specific(self, user_id: str) -> dict:
        """Skip a specific user."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        skipped = self.db.skip_queue(valid_id)
        if skipped is None:
            return {"status": "error", "message": "該使用者目前不在隊列中。"}

        self.db.log_event("skip", valid_id, skipped.queue_type)

        # Push notification to skipped user
        if self.notifier:
            self.notifier.notify_skip(valid_id)

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
            "regular_next": reg_head,
            "regular_head": reg_head,
            "vip_count": len(vip),
            "vip_next": vip_head,
            "vip_enabled": self.db.is_vip_enabled(),
        }

    def get_queue(self) -> list:
        """Get full queue list (admin view)."""
        return self.db.get_all_queue()

    def get_history(self, user_id: str) -> list:
        """Get queue history for a user."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return []
        return self.db.get_user_history(valid_id)

    def get_stats(self) -> dict:
        """Get daily/admin statistics for queue operations."""
        today = datetime.now().date()
        all_rows = self.db.get_queue_rows_for_export(limit=1000)

        joined_today = 0
        served_count = 0
        skipped_count = 0
        served_waits = []
        vip_joined_today = 0
        vip_served_count = 0
        vip_active_count = len(self.db.get_vip_queue())

        for row in all_rows:
            join_time = row.get("join_time")
            served_time = row.get("served_time")
            cancel_time = row.get("cancel_time")
            queue_type = row.get("queue_type")

            join_dt = datetime.fromisoformat(join_time) if join_time else None
            served_dt = datetime.fromisoformat(served_time) if served_time else None
            cancel_dt = datetime.fromisoformat(cancel_time) if cancel_time else None

            if join_dt and join_dt.date() == today:
                joined_today += 1
                if queue_type == "vip":
                    vip_joined_today += 1

            if served_dt and served_dt.date() == today:
                served_count += 1
                if join_dt:
                    served_waits.append((served_dt - join_dt).total_seconds() / 60)
                if queue_type == "vip":
                    vip_served_count += 1

            if cancel_dt and cancel_dt.date() == today:
                skipped_count += 1

        average_wait = sum(served_waits) / len(served_waits) if served_waits else 0.0

        return {
            "joined_today": joined_today,
            "served_count": served_count,
            "skipped_count": skipped_count,
            "average_wait_minutes": average_wait,
            "vip": {
                "enabled": self.db.is_vip_enabled(),
                "active_count": vip_active_count,
                "joined_today": vip_joined_today,
                "served_count": vip_served_count,
            },
        }

    def clear_vip_queue(self) -> dict:
        """Clear all active VIP queue entries and log each removal."""
        removed_users = []
        for entry in list(self.db.get_vip_queue()):
            cancelled = self.db.cancel_queue(entry.user_id)
            if cancelled is not None:
                removed_users.append(entry.user_id)
                self.db.log_event("vip_clear", entry.user_id, entry.queue_type, "管理員清空 VIP 隊列")

        return {
            "status": "cleared",
            "removed_count": len(removed_users),
            "removed_users": removed_users,
        }

    def clear_all_queue(self) -> dict:
        """Clear all active queue entries regardless of queue type."""
        removed_entries = self.db.clear_all_queue()
        removed_users = [entry.user_id for entry in removed_entries]
        cleared_profiles = self.db.clear_all_user_profiles()
        for entry in removed_entries:
            self.db.log_event("clear", entry.user_id, entry.queue_type, "管理員清空全部隊列")
        return {
            "status": "cleared",
            "removed_count": len(removed_users),
            "removed_users": removed_users,
            "cleared_profiles": cleared_profiles,
        }

    def register_name(self, user_id: str, display_name: str) -> dict:
        """Register or update the user's display name."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        normalized_name = display_name.strip()
        if not normalized_name:
            return {"status": "error", "message": "名稱不可為空白。"}

        profile = self.db.upsert_user_profile(valid_id, normalized_name)
        return {
            "status": "success",
            "user_id": profile.user_id,
            "display_name": profile.display_name,
            "verified": profile.verified,
        }

    def verify_user(self, user_id: str, verified: bool = True) -> dict:
        """Verify or unverify a user's identity profile."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        profile = self.db.get_user_profile(valid_id)
        if profile is None:
            return {"status": "error", "message": "尚未找到該使用者的名稱註冊資料。"}

        updated = self.db.verify_user_profile(valid_id, verified)
        return {
            "status": "success",
            "user_id": valid_id,
            "display_name": updated.display_name if updated else profile.display_name,
            "verified": bool(updated.verified) if updated else verified,
        }

    def ping_user(self, user_id: str | None = None) -> dict:
        """Send a manual ping to the specified or next queued user."""
        target_id = user_id
        if not target_id:
            all_q = self.db.get_all_queue()
            if not all_q:
                return {"status": "error", "message": "目前隊列是空的。"}
            target_id = all_q[0].user_id

        valid_id = validate_user_id(target_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        entry = self.db.get_active_queue_entry(valid_id)
        if entry is None:
            return {"status": "error", "message": "該使用者目前不在隊列中。"}

        display_name = self.db.get_display_name(valid_id)
        if self.notifier:
            self.notifier.notify_user(valid_id, f"📣 {display_name}，輪到你注意隊列狀態了。")
        self.db.log_event("ping", valid_id, entry.queue_type, "管理員手動提醒")
        return {"status": "success", "user_id": valid_id, "display_name": display_name}

    def get_user_history(self, user_id: str, limit: int = 20) -> list[dict]:
        """Get event history for a specific user."""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return []

        events = self.db.get_event_history(valid_id, limit=limit)
        return [
            {
                "event_type": event.event_type,
                "user_id": event.user_id,
                "queue_type": event.queue_type,
                "details": event.details,
                "created_at": event.created_at,
            }
            for event in events
        ]

    def export_queue_csv(self, limit: int = 20) -> str:
        """Export queue rows as CSV text."""
        return self.db.export_queue_csv(limit=limit)

    # -- config --

    def set_max_capacity(self, n: int) -> dict:
        """Set max queue capacity."""
        self.db.set_config("queue_max_capacity", str(n))
        return {"status": "ok", "max_capacity": n}

    def get_max_capacity(self) -> int:
        """Get max queue capacity."""
        return self.db.get_queue_max_capacity()

