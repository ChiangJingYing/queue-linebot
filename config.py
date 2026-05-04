"""Configuration for queue system."""

from pathlib import Path
import os
import yaml


DEFAULT_CONFIG_PATHS = (
    Path("config/queue_config.yaml"),
    Path("queue_config.yaml"),
)


def _parse_admin_ids(value: str | None) -> list[str]:
    if not value:
        return ["admin_xxxxx"]
    items = [item.strip() for item in value.split(",")]
    parsed = [item for item in items if item]
    return parsed or ["admin_xxxxx"]


def _resolve_config_path(path: str | None = None) -> Path:
    if path:
        return Path(path)
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            return candidate
    return DEFAULT_CONFIG_PATHS[0]


def load_config(path: str | None = None) -> dict:
    """Load configuration from YAML file."""
    defaults = get_defaults()
    config_path = _resolve_config_path(path)

    if not config_path.exists():
        return defaults

    try:
        with config_path.open("r", encoding="utf-8") as f:
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
        if value is None:
            continue
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
            "admin_ids": _parse_admin_ids(os.getenv("LINE_ADMIN_IDS")),
            "admin_rich_menu_id": os.getenv("LINE_ADMIN_RICH_MENU_ID", ""),
            "admin_rich_menu_page2_id": os.getenv("LINE_ADMIN_RICH_MENU_PAGE2_ID", ""),
            "user_rich_menu_id": os.getenv("LINE_USER_RICH_MENU_ID", ""),
            "push_on_served": os.getenv("LINE_PUSH_ON_SERVED", "true").lower() == "true",
        },
        "telegram_bot": {
            "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
            "webhook_secret": os.getenv("TELEGRAM_WEBHOOK_SECRET", ""),
        },
        "discord_bot": {
            "bot_token": os.getenv("DISCORD_BOT_TOKEN", ""),
            "application_id": os.getenv("DISCORD_APPLICATION_ID", ""),
            "public_key": os.getenv("DISCORD_PUBLIC_KEY", ""),
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
            "session_secret": os.getenv("WEB_UI_SESSION_SECRET", ""),
        },
        "tts": {
            "enabled": os.getenv("GOOGLE_CLOUD_TTS_ENABLED", "false").lower() == "true",
            "language_code": os.getenv("GOOGLE_CLOUD_TTS_LANGUAGE_CODE", "cmn-TW"),
            "voice_name": os.getenv("GOOGLE_CLOUD_TTS_VOICE_NAME", "cmn-TW-Standard-A"),
            "audio_encoding": os.getenv("GOOGLE_CLOUD_TTS_AUDIO_ENCODING", "MP3"),
            "speaking_rate": float(os.getenv("GOOGLE_CLOUD_TTS_SPEAKING_RATE", "1.0")),
            "pitch": float(os.getenv("GOOGLE_CLOUD_TTS_PITCH", "0.0")),
            "announcement_template": os.getenv("DASHBOARD_ANNOUNCEMENT_TEMPLATE", "來賓 {display_name} 請準備demo"),
            "new_order_idle_seconds": int(os.getenv("NEW_ORDER_IDLE_SECONDS", "300")),
            "new_order_announcement_text": os.getenv("NEW_ORDER_ANNOUNCEMENT_TEXT", "您有新訂單"),
        },
    }
