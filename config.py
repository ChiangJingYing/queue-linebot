"""Configuration for queue system."""

import os
import yaml


def load_config(path: str = "queue_config.yaml") -> dict:
    """Load configuration from YAML file."""
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        return get_defaults()


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
        },
        "logging": {
            "level": "INFO",
            "log_file": "logs/queue_events.log",
            "max_size_mb": 10,
            "backup_count": 5,
        },
    }
