"""VIP service - Buy-a-Coffee integration."""

from __future__ import annotations

from typing import Optional

from core.database import DatabaseManager


class VipService:
    """Manages VIP / coffee purchase logic."""

    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def verify_purchase(self, user_id: str) -> bool:
        """Check if user has a verified coffee purchase."""
        return self.db.is_vip_purchased(user_id)

    def toggle_vip(self, enabled: bool) -> dict:
        """Enable/disable VIP queue."""
        self.db.set_config("vip_enabled", "true" if enabled else "false")
        return {
            "vip_enabled": enabled,
            "message": f"VIP 隊列已{'啟用' if enabled else '停用'}",
        }

    def get_vip_status(self) -> dict:
        """Get current VIP status."""
        enabled = self.db.is_vip_enabled()
        count = len([q for q in self.db.get_all_queue() if q.queue_type == "vip"])
        return {"enabled": enabled, "count": count}

    def record_purchase(
        self,
        user_id: str,
        platform: str = "line",
        coffee_id: Optional[str] = None,
        verified: bool = False,
    ) -> dict:
        """Record a coffee purchase."""
        self.db.add_vip_purchase(
            user_id,
            platform=platform,
            coffee_id=coffee_id,
            verified=verified,
        )
        self.db.log_event("vip_purchase", user_id, "vip")
        return {
            "status": "purchased",
            "user_id": user_id,
            "verified": verified,
        }
