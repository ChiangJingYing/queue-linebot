"""Helpers for editable dashboard settings backed by queue_config.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from config import get_defaults, load_config


LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
MATCH_FIELDS = {"display_name"}
HOT_RELOADABLE_SECTIONS = {
    "server": False,
    "queue": True,
    "vip": True,
    "registration": True,
    "logging": False,
    "web_ui": True,
    "line_bot": True,
}


class ConfigValidationError(ValueError):
    """Raised when dashboard settings payload is invalid."""


class FlowStyleList(list):
    """A YAML sequence that should be rendered in flow style."""


class QueueConfigDumper(yaml.SafeDumper):
    """Project dumper for preserving preferred YAML formatting."""


def _ensure_dict(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        raise ConfigValidationError(f"{path} 必須是物件")
    return value


def _as_bool(value: object) -> bool:
    return bool(value)


def _as_string(value: object, path: str, *, allow_empty: bool = False) -> str:
    text = str(value if value is not None else "").strip()
    if not allow_empty and not text:
        raise ConfigValidationError(f"{path} 不可為空")
    return text


def _as_int(value: object, path: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigValidationError(f"{path} 必須是整數") from exc
    if minimum is not None and number < minimum:
        raise ConfigValidationError(f"{path} 必須大於或等於 {minimum}")
    if maximum is not None and number > maximum:
        raise ConfigValidationError(f"{path} 必須小於或等於 {maximum}")
    return number


def _dedupe_strings(values: list[object]) -> list[str]:
    items: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value if value is not None else "").strip()
        if not text or text in seen:
            continue
        items.append(text)
        seen.add(text)
    return items


def _represent_flow_style_list(dumper: yaml.SafeDumper, data: FlowStyleList):
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


QueueConfigDumper.add_representer(FlowStyleList, _represent_flow_style_list)


def _normalize_special_serve_rules(value: object) -> dict:
    rules = _ensure_dict(value, "queue.special_serve_rules")
    match_field = _as_string(rules.get("match_field", "display_name"), "queue.special_serve_rules.match_field")
    if match_field not in MATCH_FIELDS:
        raise ConfigValidationError("queue.special_serve_rules.match_field 目前只支援 display_name")

    admins_input = rules.get("admins", [])
    admins_map: dict[str, dict[str, list[str]]] = {}
    if isinstance(admins_input, dict):
        iterable = [
            {"admin_id": admin_id, "targets": data.get("targets", []) if isinstance(data, dict) else []}
            for admin_id, data in admins_input.items()
        ]
    elif isinstance(admins_input, list):
        iterable = admins_input
    else:
        raise ConfigValidationError("queue.special_serve_rules.admins 必須是陣列或物件")

    for item in iterable:
        if not isinstance(item, dict):
            continue
        admin_id = _as_string(item.get("admin_id", ""), "queue.special_serve_rules.admins[].admin_id")
        targets_raw = item.get("targets", [])
        if not isinstance(targets_raw, list):
            raise ConfigValidationError("queue.special_serve_rules.admins[].targets 必須是陣列")
        admins_map[admin_id] = {"targets": _dedupe_strings(targets_raw)}

    return {
        "enabled": _as_bool(rules.get("enabled", False)),
        "match_field": match_field,
        "skip_message": _as_string(rules.get("skip_message", ""), "queue.special_serve_rules.skip_message", allow_empty=True),
        "no_next_reply": _as_string(rules.get("no_next_reply", ""), "queue.special_serve_rules.no_next_reply", allow_empty=True),
        "admins": admins_map,
    }


def _normalize_location_options(value: object) -> dict[str, list[str]]:
    if isinstance(value, dict):
        rows = [{"row": row, "columns": columns} for row, columns in value.items()]
    elif isinstance(value, list):
        rows = value
    else:
        raise ConfigValidationError("registration.location_options 必須是陣列或物件")

    normalized: dict[str, list[str]] = {}
    for row_item in rows:
        if not isinstance(row_item, dict):
            continue
        row = _as_string(row_item.get("row", ""), "registration.location_options[].row")
        columns_raw = row_item.get("columns", [])
        if not isinstance(columns_raw, list):
            raise ConfigValidationError("registration.location_options[].columns 必須是陣列")
        normalized[row] = _dedupe_strings(columns_raw)

    if not normalized:
        raise ConfigValidationError("registration.location_options 至少要有一列")
    return normalized


def editable_config_defaults() -> dict:
    defaults = get_defaults()
    return build_editable_config(defaults)


def build_editable_config(loaded_config: dict) -> dict:
    defaults = get_defaults()
    merged = load_config_data(defaults, loaded_config)
    loaded_queue = loaded_config.get("queue") if isinstance(loaded_config.get("queue"), dict) else None
    if loaded_queue:
        merged.setdefault("queue", {})
        for key in ("max_capacity",):
            if key in loaded_queue and loaded_queue[key] is None:
                merged["queue"][key] = None
    loaded_registration = loaded_config.get("registration") if isinstance(loaded_config.get("registration"), dict) else None
    if loaded_registration and isinstance(loaded_registration.get("location_options"), dict):
        merged.setdefault("registration", {})
        merged["registration"]["location_options"] = loaded_registration["location_options"]
    special_rules = merged["queue"]["special_serve_rules"]
    return {
        "server": {
            "host": str(merged["server"]["host"]),
            "port": int(merged["server"]["port"]),
            "debug": bool(merged["server"]["debug"]),
        },
        "queue": {
            "max_capacity": int(merged["queue"]["max_capacity"]) if merged["queue"].get("max_capacity") is not None else None,
            "special_serve_rules": {
                "enabled": bool(special_rules.get("enabled", False)),
                "match_field": str(special_rules.get("match_field", "display_name")),
                "skip_message": str(special_rules.get("skip_message", "")),
                "no_next_reply": str(special_rules.get("no_next_reply", "")),
                "admins": {
                    str(admin_id): {"targets": _dedupe_strings(data.get("targets", []) if isinstance(data, dict) else [])}
                    for admin_id, data in (special_rules.get("admins", {}) or {}).items()
                },
            },
        },
        "vip": {
            "enabled": bool(merged["vip"]["enabled"]),
            "coffee_price": int(merged["vip"]["coffee_price"]),
        },
        "registration": {
            "location_options": {
                str(row): _dedupe_strings(columns if isinstance(columns, list) else [])
                for row, columns in (merged["registration"]["location_options"] or {}).items()
            }
        },
        "logging": {
            "level": str(merged["logging"]["level"]),
            "log_file": str(merged["logging"]["log_file"]),
            "max_size_mb": int(merged["logging"]["max_size_mb"]),
            "backup_count": int(merged["logging"]["backup_count"]),
        },
        "web_ui": {
            "protect_read_routes": bool(merged["web_ui"]["protect_read_routes"]),
            "allow_query_token": bool(merged["web_ui"]["allow_query_token"]),
            "session_cookie_name": str(merged["web_ui"]["session_cookie_name"]),
        },
        "line_bot": {
            "push_on_served": bool(merged["line_bot"]["push_on_served"]),
        },
    }


def load_config_data(defaults: dict, loaded: dict) -> dict:
    merged = dict(defaults)
    for key, value in loaded.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = load_config_data(merged[key], value)
        else:
            merged[key] = value
    return merged


def _wrap_location_options_for_yaml(data: object) -> object:
    if isinstance(data, dict):
        wrapped: dict[object, object] = {}
        for key, value in data.items():
            if isinstance(value, list):
                wrapped[key] = FlowStyleList(value)
            else:
                wrapped[key] = _wrap_location_options_for_yaml(value)
        return wrapped
    if isinstance(data, list):
        return [_wrap_location_options_for_yaml(item) for item in data]
    return data


def normalize_editable_config(payload: object) -> dict:
    data = _ensure_dict(payload, "payload")
    server = _ensure_dict(data.get("server", {}), "server")
    queue = _ensure_dict(data.get("queue", {}), "queue")
    vip = _ensure_dict(data.get("vip", {}), "vip")
    registration = _ensure_dict(data.get("registration", {}), "registration")
    logging_config = _ensure_dict(data.get("logging", {}), "logging")
    web_ui = _ensure_dict(data.get("web_ui", {}), "web_ui")
    line_bot = _ensure_dict(data.get("line_bot", {}), "line_bot")

    log_level = _as_string(logging_config.get("level", "INFO"), "logging.level")
    if log_level not in LOG_LEVELS:
        raise ConfigValidationError("logging.level 不支援")

    return {
        "server": {
            "host": _as_string(server.get("host", ""), "server.host"),
            "port": _as_int(server.get("port", 0), "server.port", minimum=1, maximum=65535),
            "debug": _as_bool(server.get("debug", False)),
        },
        "queue": {
            "max_capacity": None if queue.get("max_capacity") in (None, "") else _as_int(queue.get("max_capacity"), "queue.max_capacity", minimum=1),
            "special_serve_rules": _normalize_special_serve_rules(
                queue.get(
                    "special_serve_rules",
                    {
                        "enabled": False,
                        "match_field": "display_name",
                        "skip_message": "",
                        "no_next_reply": "",
                        "admins": [],
                    },
                )
            ),
        },
        "vip": {
            "enabled": _as_bool(vip.get("enabled", False)),
            "coffee_price": _as_int(vip.get("coffee_price", 0), "vip.coffee_price", minimum=0),
        },
        "registration": {
            "location_options": _normalize_location_options(registration.get("location_options", [])),
        },
        "logging": {
            "level": log_level,
            "log_file": _as_string(logging_config.get("log_file", ""), "logging.log_file"),
            "max_size_mb": _as_int(logging_config.get("max_size_mb", 0), "logging.max_size_mb", minimum=1),
            "backup_count": _as_int(logging_config.get("backup_count", 0), "logging.backup_count", minimum=0),
        },
        "web_ui": {
            "protect_read_routes": _as_bool(web_ui.get("protect_read_routes", False)),
            "allow_query_token": _as_bool(web_ui.get("allow_query_token", False)),
            "session_cookie_name": _as_string(web_ui.get("session_cookie_name", ""), "web_ui.session_cookie_name"),
        },
        "line_bot": {
            "push_on_served": _as_bool(line_bot.get("push_on_served", False)),
        },
    }


class QueueConfigStore:
    """Persist editable config sections while preserving unknown keys."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load_raw(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except (OSError, yaml.YAMLError):
            return {}
        return data if isinstance(data, dict) else {}

    def load_text(self) -> str:
        if not self.path.exists():
            return ""
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def load_editable(self) -> dict:
        raw = self.load_raw()
        editable = build_editable_config(load_config(str(self.path)))
        raw_queue = raw.get("queue") if isinstance(raw.get("queue"), dict) else {}
        editable_queue = editable.get("queue", {})
        for key in ("max_capacity",):
            if key not in raw_queue:
                editable_queue[key] = None
        editable["queue"] = editable_queue
        return editable

    def save_raw_text(self, raw_yaml: str) -> dict:
        try:
            parsed = yaml.safe_load(raw_yaml) or {}
        except yaml.YAMLError as exc:
            raise ConfigValidationError("YAML 格式錯誤") from exc
        if not isinstance(parsed, dict):
            raise ConfigValidationError("YAML 根節點必須是物件")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(raw_yaml, encoding="utf-8")
        return {
            "config": self.load_editable(),
            "rawYaml": self.load_text(),
        }

    def save_editable(self, editable_config: dict) -> dict:
        current = self.load_raw()
        next_config = dict(current)

        next_config["server"] = {
            **(current.get("server", {}) if isinstance(current.get("server"), dict) else {}),
            **editable_config["server"],
        }

        current_queue = current.get("queue", {}) if isinstance(current.get("queue"), dict) else {}
        current_rules = current_queue.get("special_serve_rules", {}) if isinstance(current_queue.get("special_serve_rules"), dict) else {}
        next_queue = {
            **current_queue,
            "special_serve_rules": {
                **current_rules,
                **editable_config["queue"]["special_serve_rules"],
            },
        }
        for key in ("max_capacity",):
            value = editable_config["queue"][key]
            if value is None:
                next_queue.pop(key, None)
            else:
                next_queue[key] = value
        next_config["queue"] = next_queue

        next_config["vip"] = {
            **(current.get("vip", {}) if isinstance(current.get("vip"), dict) else {}),
            **editable_config["vip"],
        }

        current_registration = current.get("registration", {}) if isinstance(current.get("registration"), dict) else {}
        next_config["registration"] = {
            **current_registration,
            "location_options": editable_config["registration"]["location_options"],
        }

        next_config["logging"] = {
            **(current.get("logging", {}) if isinstance(current.get("logging"), dict) else {}),
            **editable_config["logging"],
        }

        current_web_ui = current.get("web_ui", {}) if isinstance(current.get("web_ui"), dict) else {}
        next_config["web_ui"] = {
            **current_web_ui,
            **editable_config["web_ui"],
        }

        current_line_bot = current.get("line_bot", {}) if isinstance(current.get("line_bot"), dict) else {}
        next_config["line_bot"] = {
            **current_line_bot,
            **editable_config["line_bot"],
        }

        dumped_config = dict(next_config)
        registration = dumped_config.get("registration", {})
        if isinstance(registration, dict) and isinstance(registration.get("location_options"), dict):
            dumped_config["registration"] = {
                **registration,
                "location_options": _wrap_location_options_for_yaml(registration["location_options"]),
            }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            yaml.dump(dumped_config, fh, Dumper=QueueConfigDumper, allow_unicode=True, sort_keys=False)

        return {
            "config": self.load_editable(),
            "rawYaml": self.load_text(),
        }
