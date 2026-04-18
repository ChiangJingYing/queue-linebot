"""ID validation utilities."""

from __future__ import annotations

import re
from typing import Optional


def validate_user_id(user_id: str) -> Optional[str]:
    """Validate a user ID.

    Rules:
    - Must not be empty or whitespace-only
    - Max 100 characters
    - Only alphanumeric, underscore, hyphen

    Returns stripped user_id on success, None on failure.
    """
    if not user_id or not user_id.strip():
        return None
    user_id = user_id.strip()
    if len(user_id) > 100:
        return None
    if not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
        return None
    return user_id


def validate_command(text: str) -> tuple[str, list[str]]:
    """Parse a command string into (command, args_list).

    E.g. '/join user_12345' -> ('/join', ['user_12345'])
    """
    if not text or not text.strip():
        return ("", [])
    text = text.strip()
    if not text.startswith("/"):
        return ("", [])
    parts = text[1:].split()
    command = "/" + parts[0].lower() if parts else ""
    args = [a for a in parts[1:]]
    return (command, args)
