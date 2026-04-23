"""Configuration for queue system."""

import os
import yaml


def load_config(path: str = "queue_config.yaml") -> dict:
    """Load configuration from YAML file."""
    defaults = get_defaults()

    if not os.path.exists(path):
        return defaults

    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return defaults

    if not isinstance(loaded, dict):
        return defaults

    merged = _deep_merge(defaults, loaded)

    registration = loaded.get("registration") if isinstance(loaded.get("registration"), dict) else None
    if registration and isinstance(registration.get("location_options"), dict):
        merged.setdefault("registration", {})
        merged["registration"]["location_options"] = registration["location_options"]

    return merged


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override values into base config."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def get_defaults() -> dict:
    """Return default configuration."""
    return {
        "server": {
            "host": "0.0.0.0",
            "port": 8000,
            "debug": False,
        },
        "queue": {
            "max_capacity": 50,
            "timeout_minutes": 30,
            "timeout_action": "remove",
        },
        "vip": {
            "enabled": True,
            "coffee_price": 60,
            "coffee_url": "https://buymeacoffee.com/yourname",
        },
        "line_bot": {
            "channel_secret": os.getenv("LINE_CHANNEL_SECRET", ""),
            "channel_access_token": os.getenv("LINE_CHANNEL_TOKEN", ""),
            "admin_ids": ["admin_xxxxx"],
            "admin_rich_menu_id": os.getenv("LINE_ADMIN_RICH_MENU_ID", ""),
            "admin_rich_menu_page2_id": os.getenv("LINE_ADMIN_RICH_MENU_PAGE2_ID", ""),
            "user_rich_menu_id": os.getenv("LINE_USER_RICH_MENU_ID", ""),
        },
        "registration": {
            "location_options": {
                "1": ["1", "2", "3"],
                "2": ["1", "2", "3", "4"],
            },
        },
        "logging": {
            "level": "INFO",
            "log_file": "logs/queue_events.log",
            "max_size_mb": 10,
            "backup_count": 5,
        },
        "web_ui": {
            "admin_token": os.getenv("WEB_UI_ADMIN_TOKEN", ""),
            "protect_read_routes": False,
            "allow_query_token": False,
            "session_cookie_name": "queue_admin_session",
        },
    }
