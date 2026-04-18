"""Admin authentication utilities."""

from __future__ import annotations

from typing import List


def is_admin(user_id: str, admin_ids: list) -> bool:
    """Check if user is admin."""
    return user_id in admin_ids


def get_admin_ids() -> list:
    """Get admin IDs from config."""
    from config import load_config
    config = load_config()
    return config.get("line_bot", {}).get("admin_ids", [])


class AdminAuth:
    """Admin authentication class."""

    def __init__(self, admin_ids: list = None) -> None:
        self.admin_ids = admin_ids or []

    def check(self, user_id: str) -> bool:
        """Check admin access."""
        return user_id in self.admin_ids
