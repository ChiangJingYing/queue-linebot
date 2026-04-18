"""VIP service tests."""

import pytest

from services.vip_service import VipService


class TestVipStatus:
    """Tests for VIP status."""

    def test_vip_enabled_by_default(self, queue_manager):
        """VIP is enabled by default."""
        vip = VipService(queue_manager.db)
        status = vip.get_vip_status()
        assert status["enabled"] is True

    def test_vip_toggle_disable(self, queue_manager):
        """Disable VIP."""
        vip = VipService(queue_manager.db)
        result = vip.toggle_vip(False)
        assert result["vip_enabled"] is False
        assert "停用" in result["message"]

        status = vip.get_vip_status()
        assert status["enabled"] is False

    def test_vip_toggle_enable(self, queue_manager):
        """Enable VIP after disable."""
        vip = VipService(queue_manager.db)
        vip.toggle_vip(False)
        result = vip.toggle_vip(True)
        assert result["vip_enabled"] is True

    def test_vip_count_empty(self, queue_manager):
        """VIP count when empty."""
        vip = VipService(queue_manager.db)
        status = vip.get_vip_status()
        assert status["count"] == 0


class TestVipPurchase:
    """Tests for VIP purchase."""

    def test_vip_can_purchase_twice(self, queue_manager):
        """Duplicate purchases are blocked by unique user constraint."""
        import sqlite3
        vip = VipService(queue_manager.db)
        vip.record_purchase("alice", "line", "coffee_1")

        with pytest.raises(sqlite3.IntegrityError):
            vip.record_purchase("alice", "line", "coffee_2")

    def test_vip_not_purchased(self, queue_manager):
        """User without purchase."""
        vip = VipService(queue_manager.db)
        assert vip.verify_purchase("nonexistent") is False


