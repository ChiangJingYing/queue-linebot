"""Helpers for resolving LINE user profile data via Messaging API."""

from __future__ import annotations

import logging
import re


logger = logging.getLogger(__name__)
LINE_USER_ID_PATTERN = re.compile(r"^U[0-9a-f]{32}$", re.IGNORECASE)


def is_probable_line_user_id(user_id: str) -> bool:
    """Return True when the id matches LINE userId's common format."""
    normalized_user_id = str(user_id or "").strip()
    return bool(LINE_USER_ID_PATTERN.fullmatch(normalized_user_id))


def fetch_line_profile_display_name(*, channel_access_token: str, user_id: str) -> str:
    """Fetch a LINE user's display name, returning empty string on any failure."""
    normalized_user_id = str(user_id or "").strip()
    normalized_token = str(channel_access_token or "").strip()
    if not normalized_user_id or not normalized_token:
        return ""
    if not is_probable_line_user_id(normalized_user_id):
        logger.debug("Skip LINE profile lookup for non-LINE user id: %s", normalized_user_id)
        return ""

    try:
        from linebot.v3.messaging import ApiClient, Configuration, MessagingApi
    except Exception:
        logger.debug("LINE SDK 無法使用；略過 profile lookup")
        return ""

    try:
        configuration = Configuration(access_token=normalized_token)
        with ApiClient(configuration) as api_client:
            profile = MessagingApi(api_client).get_profile(normalized_user_id)
    except Exception as exc:
        logger.debug("LINE profile lookup failed for %s: %s", normalized_user_id, exc)
        return ""

    return str(getattr(profile, "display_name", "") or "").strip()
