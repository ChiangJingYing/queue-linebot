"""Tests for admin application system."""

from unittest.mock import patch

import pytest

from main import _line_message_payloads_from_action


class TestAdminApplicationsDB:
    """Test admin_applications table operations."""

    def test_create_table(self, db_manager):
        """Table exists after init."""
        with db_manager._connection() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        table_names = [r["name"] for r in rows]
        assert "admin_applications" in table_names

    def test_add_application(self, db_manager):
        result = db_manager.add_admin_application("Uuser123", "John")
        assert result["status"] == "success"

    def test_add_duplicate_application(self, db_manager):
        """Duplicate application should be rejected."""
        db_manager.add_admin_application("Uuser456", "Jane")
        result = db_manager.add_admin_application("Uuser456", "Jane again")
        assert result["status"] == "duplicate"

    def test_get_pending_applications(self, db_manager):
        """Get all pending applications."""
        db_manager.add_admin_application("Uuser123", "John")
        db_manager.add_admin_application("Uuser456", "Jane")
        pending = db_manager.get_pending_applications()
        assert len(pending) == 2

    def test_approve_application(self, db_manager):
        """Approve an application."""
        db_manager.add_admin_application("Uuser123", "John")
        result = db_manager.approve_admin_application("Uuser123", "Uadmin001")
        assert result["status"] == "success"

    def test_approved_admin_reregister_keeps_admin_role(self, db_manager):
        db_manager.add_admin_application("Uuser123", "John")
        db_manager.approve_admin_application("Uuser123", "Uadmin001")

        profile = db_manager.upsert_user_profile("Uuser123", "B12345678", location="A-1")

        assert profile.role == "admin"
        assert profile.display_name == "B12345678"
        assert profile.location == "A-1"

    def test_approve_nonexistent(self, db_manager):
        """Approving non-existent application should fail."""
        result = db_manager.approve_admin_application("Unonexistent", "Uadmin001")
        assert result["status"] == "error"

    def test_approve_already_approved(self, db_manager):
        """Approving already approved application should fail."""
        db_manager.add_admin_application("Uuser123", "John")
        db_manager.approve_admin_application("Uuser123", "Uadmin001")
        result = db_manager.approve_admin_application("Uuser123", "Uadmin002")
        assert result["status"] == "error"

    def test_reject_application(self, db_manager):
        """Reject an application."""
        db_manager.add_admin_application("Uuser123", "John")
        result = db_manager.reject_admin_application("Uuser123", "Uadmin001")
        assert result["status"] == "success"

    def test_reject_nonexistent(self, db_manager):
        """Rejecting non-existent application should fail."""
        result = db_manager.reject_admin_application("Unonexistent", "Uadmin001")
        assert result["status"] == "error"

    def test_reject_already_processed(self, db_manager):
        """Rejecting already approved application should fail."""
        db_manager.add_admin_application("Uuser123", "John")
        db_manager.approve_admin_application("Uuser123", "Uadmin001")
        result = db_manager.reject_admin_application("Uuser123", "Uadmin002")
        assert result["status"] == "error"

    def test_get_all_admins(self, db_manager):
        """Get all approved admins."""
        db_manager.add_admin_application("Uuser123", "John")
        db_manager.approve_admin_application("Uuser123", "Uadmin001")
        admins = db_manager.get_all_admins()
        admin_ids = [a["user_id"] for a in admins]
        assert "Uuser123" in admin_ids

    def test_is_admin(self, db_manager):
        """Check if user is admin."""
        assert not db_manager.is_admin("Uuser123")
        db_manager.add_admin_application("Uuser123", "John")
        db_manager.approve_admin_application("Uuser123", "Uadmin001")
        assert db_manager.is_admin("Uuser123")

    def test_pending_count(self, db_manager):
        """Count pending applications."""
        assert db_manager.get_pending_count() == 0
        db_manager.add_admin_application("Uuser123", "John")
        assert db_manager.get_pending_count() == 1

    def test_application_order_by_created_at(self, db_manager):
        """Applications returned in order of created_at."""
        db_manager.add_admin_application("Uuser2", "B")
        db_manager.add_admin_application("Uuser1", "A")
        pending = db_manager.get_pending_applications()
        # Should be ordered by applied_at DESC (newest first)
        assert len(pending) == 2

    def test_application_with_empty_name(self, db_manager):
        """Empty display name should be rejected."""
        result = db_manager.add_admin_application("Uuser123", "")
        assert result["status"] == "error"

    def test_application_with_whitespace_only_name(self, db_manager):
        """Whitespace-only display name should be rejected."""
        result = db_manager.add_admin_application("Uuser123", "   ")
        assert result["status"] == "error"


class TestAdminApplyHandler:
    """Test admin apply command handlers."""

    def test_apply_command(self, handler):
        result = handler._handle_admin_apply("Uapplicant123", "replytoken")
        assert len(result) == 1
        text = result[0]["text"]
        assert "已提交" in text

    def test_apply_duplicate(self, handler):
        """Duplicate application should be rejected."""
        handler._handle_admin_apply("Uapplicant456", "replytoken")
        result = handler._handle_admin_apply("Uapplicant456", "replytoken2")
        text = result[0]["text"]
        assert "重複" in text

    def test_apply_list_empty(self, handler):
        result = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001")
        assert len(result) == 1
        text = result[0]["text"]
        assert "沒有" in text

    def test_apply_list_with_items(self, handler):
        """Apply list should show pending applications."""
        handler.queue_manager.db.add_admin_application("Uuser123", "John")
        handler.queue_manager.db.add_admin_application("Uuser456", "Jane")
        handler.queue_manager.db.upsert_user_profile("Uuser123", "B12345678", verified=True, role="user")
        result = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001")
        assert len(result) == 1
        text = result[0]["text"]
        assert "John" in text
        assert "B12345678" not in text

    def test_apply_list_uses_application_display_name_when_profile_name_missing(self, handler):
        handler.queue_manager.db.add_admin_application("Uuser123", "John")

        result = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001")

        assert len(result) == 1
        text = result[0]["text"]
        assert "Uuser123 (John)" in text

    def test_apply_list_prefers_line_profile_name_over_application_display_name(self, handler):
        line_user_id = "U" + "a" * 32
        handler.queue_manager.db.add_admin_application(line_user_id, "John")
        handler.queue_manager.db.upsert_user_profile(line_user_id, "B12345678", verified=True, role="user")
        handler.channel_access_token = "line-token"

        with patch("bot.handler_admin.fetch_line_profile_display_name", return_value="LINE Alice"):
            result = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001")

        assert len(result) == 1
        text = result[0]["text"]
        assert "LINE Alice" in text
        assert "John" not in text
        assert "B12345678" not in text

    def test_apply_list_uses_line_profile_name_when_pending_user_has_no_profile(self, handler):
        line_user_id = "U" + "a" * 32
        handler.queue_manager.db.add_admin_application(line_user_id, "John")
        handler.channel_access_token = "line-token"

        with patch("bot.handler_admin.fetch_line_profile_display_name", return_value="LINE Alice"):
            result = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001")

        assert len(result) == 1
        text = result[0]["text"]
        assert "LINE Alice" in text
        assert f"{line_user_id} (John)" not in text

    def test_apply_list_falls_back_to_application_display_name_when_line_profile_missing(self, handler):
        line_user_id = "U" + "a" * 32
        handler.queue_manager.db.add_admin_application(line_user_id, "John")
        handler.queue_manager.db.upsert_user_profile(line_user_id, "B12345678", verified=True, role="user")
        handler.channel_access_token = "line-token"

        with patch("bot.handler_admin.fetch_line_profile_display_name", return_value=""):
            result = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001")

        assert len(result) == 1
        text = result[0]["text"]
        assert f"{line_user_id} (John)" in text
        assert "B12345678" not in text

    def test_apply_approve(self, handler):
        """Approving an application."""
        handler.queue_manager.db.add_admin_application("Uuser123", "John")
        result = handler._handle_admin_apply_approve("Uadmin001", "Uuser123", "replytoken")
        assert len(result) == 1
        text = result[0]["text"]
        assert "已批准" in text

    def test_apply_approve_nonexistent(self, handler):
        """Approving non-existent application."""
        result = handler._handle_admin_apply_approve("Uadmin001", "Unonexistent", "replytoken")
        text = result[0]["text"]
        assert "找不到" in text

    def test_apply_reject(self, handler):
        """Rejecting an application."""
        handler.queue_manager.db.add_admin_application("Uuser123", "John")
        result = handler._handle_admin_apply_reject("Uadmin001", "Uuser123", "replytoken")
        assert len(result) == 1
        text = result[0]["text"]
        assert "已拒絕" in text

    def test_apply_reject_nonexistent(self, handler):
        """Rejecting non-existent application."""
        result = handler._handle_admin_apply_reject("Uadmin001", "Unonexistent", "replytoken")
        text = result[0]["text"]
        assert "找不到" in text

    def test_apply_reject_already_approved(self, handler):
        """Rejecting already approved application."""
        handler.queue_manager.db.add_admin_application("Uuser123", "John")
        handler.queue_manager.db.approve_admin_application("Uuser123", "Uadmin001")
        result = handler._handle_admin_apply_reject("Uadmin002", "Uuser123", "replytoken")
        text = result[0]["text"]
        assert "已處理" in text

    def test_apply_list_pagination(self, handler):
        """Pagination should work with many applications."""
        for i in range(15):
            handler.queue_manager.db.add_admin_application(f"Uuser{i:03d}", f"User{i}")
        result = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001")
        assert len(result) == 1
        # Should have quick reply items for pagination
        action = result[0]
        assert "quickReply" in action
        items = action["quickReply"]["items"]
        assert len(items) <= 13
        assert any(item["action"]["text"] == "/admin/apply list page+2" for item in items)

    def test_apply_list_page_navigation(self, handler):
        """Page navigation should work."""
        for i in range(15):
            handler.queue_manager.db.add_admin_application(f"Uuser{i:03d}", f"User{i}")
        # Page 2 (page=2)
        result = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001", page=2)
        assert len(result) == 1
        items = result[0]["quickReply"]["items"]
        assert len(items) <= 13
        assert any(item["action"]["text"] == "/admin/apply list page-1" for item in items)

    def test_apply_list_quick_reply_labels_are_line_safe(self, handler):
        """LINE quick reply message action labels must stay within 20 chars."""
        line_user_id = "U" + "a" * 32
        handler.queue_manager.db.add_admin_application(line_user_id, "A very very long display name")

        result = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001")

        items = result[0]["quickReply"]["items"]
        assert items
        for item in items:
            label = item["action"]["label"]
            assert len(label) <= 20
            assert line_user_id not in label
        assert any(item["action"]["text"] == f"/admin/apply approve {line_user_id}" for item in items)

    def test_apply_list_line_payload_quick_reply_labels_are_line_safe(self, handler):
        """Final LINE reply payload should keep quick reply labels API-safe."""
        line_user_id = "U" + "a" * 32
        handler.queue_manager.db.add_admin_application(line_user_id, "A very very long display name")

        [action] = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001")
        [message] = _line_message_payloads_from_action(action)

        items = message["quickReply"]["items"]
        for item in items:
            label = item["action"]["label"]
            assert len(label) <= 20
            assert line_user_id not in label
        assert any(item["action"]["text"] == f"/admin/apply approve {line_user_id}" for item in items)

    def test_apply_list_page_minus_one(self, handler):
        """Page -1 should go to last page."""
        for i in range(15):
            handler.queue_manager.db.add_admin_application(f"Uuser{i:03d}", f"User{i}")
        result = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001", page=-1)
        assert len(result) == 1

    def test_apply_list_no_pending(self, handler):
        """Empty list should not have quick reply items."""
        result = handler._handle_admin_apply_list(reply_token="replytoken", user_id="Uadmin001")
        assert len(result) == 1

    def test_approved_user_becomes_admin(self, handler):
        """Approved applicant should pass admin auth checks."""
        handler.queue_manager.db.add_admin_application("new_admin", "新管理員")
        handler.queue_manager.db.approve_admin_application("new_admin", "Uadmin001")

        assert handler._is_admin("new_admin") is True
