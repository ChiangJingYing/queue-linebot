from __future__ import annotations

import builtins

from services.line_profile_lookup import fetch_line_profile_display_name, is_probable_line_user_id


def test_is_probable_line_user_id_matches_line_user_ids():
    assert is_probable_line_user_id("U1234567890abcdef1234567890abcdef") is True
    assert is_probable_line_user_id("u1234567890abcdef1234567890abcdef") is True
    assert is_probable_line_user_id("8630157037") is False
    assert is_probable_line_user_id("telegram_user:123456") is False
    assert is_probable_line_user_id("discord_user_123456") is False


def test_fetch_line_profile_display_name_skips_non_line_ids(monkeypatch):
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name.startswith("linebot"):
            raise AssertionError("linebot SDK should not be imported for non-LINE ids")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    result = fetch_line_profile_display_name(
        channel_access_token="token-123",
        user_id="8630157037",
    )

    assert result == ""
