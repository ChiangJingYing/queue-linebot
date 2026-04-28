"""Tests for queue stats aggregation."""

import pytest


class TestQueueStats:
    """Test QueueManager.get_queue_stats()."""

    def test_returns_registered_count_zero(self, queue_manager):
        """Registered count should be 0 when no profiles exist."""
        stats = queue_manager.get_queue_stats()
        assert "registered" in stats
        assert stats["registered"] == 0

    def test_registered_count_increases_after_profile(self, queue_manager):
        """Registered count should go up when a profile is created."""
        queue_manager.register_name("u1", "User One", "A-1")
        stats = queue_manager.get_queue_stats()
        assert stats["registered"] == 1

    def test_registered_count_excludes_no_location(self, queue_manager):
        """Profiles without location should NOT count as registered."""
        queue_manager.register_name("u2", "No Location")
        stats = queue_manager.get_queue_stats()
        assert stats["registered"] == 0

    def test_registered_count_multiple_users(self, queue_manager):
        """Registered count should reflect all users with location."""
        queue_manager.register_name("a1", "A", "A-1")
        queue_manager.register_name("a2", "B", "A-2")
        queue_manager.register_name("a3", "C")  # no location
        stats = queue_manager.get_queue_stats()
        assert stats["registered"] == 2

    def test_queue_count_is_zero_empty(self, queue_manager):
        """Queue count should be 0 when no one is in queue."""
        stats = queue_manager.get_queue_stats()
        assert "queue" in stats
        assert stats["queue"] == 0

    def test_queue_count_includes_regular(self, queue_manager):
        """Queue count should include regular queue entries."""
        queue_manager.join("b1", "regular")
        stats = queue_manager.get_queue_stats()
        assert stats["queue"] == 1

    def test_queue_count_includes_vip(self, queue_manager):
        """Queue count should include VIP entries."""
        # VIP requires purchase record with verified=True
        queue_manager.db.set_config("vip_enabled", "true")
        queue_manager.db.add_vip_purchase("v1", "line", "coffee1", True)
        queue_manager.join("v1", "vip")
        stats = queue_manager.get_queue_stats()
        assert stats["queue"] == 1

    def test_queue_count_mixed(self, queue_manager):
        """Queue count should be sum of regular + vip."""
        queue_manager.db.set_config("vip_enabled", "true")
        queue_manager.db.add_vip_purchase("v2", "line", "coffee2", True)
        queue_manager.join("r1", "regular")
        queue_manager.join("r2", "regular")
        queue_manager.join("v2", "vip")
        stats = queue_manager.get_queue_stats()
        assert stats["queue"] == 3

    def test_queue_count_excludes_cancelled(self, queue_manager):
        """Cancelled entries should NOT count toward queue."""
        queue_manager.join("c1", "regular")
        queue_manager.cancel("c1")
        stats = queue_manager.get_queue_stats()
        assert stats["queue"] == 0

    def test_queue_count_excludes_served(self, queue_manager):
        """Served entries should NOT count toward queue."""
        queue_manager.join("s1", "regular")
        queue_manager.serve_specific("s1")
        stats = queue_manager.get_queue_stats()
        assert stats["queue"] == 0

    def test_served_count_excludes_cancelled(self, queue_manager):
        """Cancelled entries should NOT count toward served."""
        queue_manager.join("cx1", "regular")
        queue_manager.cancel("cx1")
        stats = queue_manager.get_queue_stats()
        assert stats["served"] == 0

    def test_served_count_is_zero_empty(self, queue_manager):
        """Served count should be 0 when no one has been served."""
        stats = queue_manager.get_queue_stats()
        assert "served" in stats
        assert stats["served"] == 0

    def test_served_count_increases_after_serve(self, queue_manager):
        """Served count should increase after serving."""
        queue_manager.join("sv1", "regular")
        queue_manager.serve_specific("sv1")
        stats = queue_manager.get_queue_stats()
        assert stats["served"] >= 1

    def test_served_count_accumulates(self, queue_manager):
        """Served count should accumulate across multiple serves."""
        queue_manager.join("sv2", "regular")
        queue_manager.join("sv3", "regular")
        queue_manager.serve_specific("sv2")
        queue_manager.serve_specific("sv3")
        stats = queue_manager.get_queue_stats()
        assert stats["served"] == 2

    def test_all_keys_present(self, queue_manager):
        """Stats dict must contain registered, queue, served."""
        stats = queue_manager.get_queue_stats()
        assert "registered" in stats
        assert "queue" in stats
        assert "served" in stats
        assert len(stats) == 3
