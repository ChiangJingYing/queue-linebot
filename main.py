"""FastAPI entry point for queue LINE Bot."""

from __future__ import annotations

import base64
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import hashlib
import hmac
import json
import logging
import mimetypes
import os
import signal
import threading
import urllib.error
import urllib.request
from html import escape
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from contextlib import asynccontextmanager
from hmac import compare_digest
from typing import AsyncGenerator
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import StarletteHTTPException
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from bot.handler import LineBotHandler
from config import _resolve_config_path, load_config
from core.database import DatabaseManager
from core.queue_manager import QueueManager
from core.time_utils import TAIPEI_TZ, format_display_time, parse_timestamp
from services.notifier import Notifier
from services.background_dispatcher import ThreadedDispatcher
from services.telegram_commands import TelegramCommandService
from services.discord_commands import DiscordCommandService
from services.vip_service import VipService
from services.dashboard_announcement import DashboardAnnouncementService, GoogleCloudTTSService
from services.line_profile_lookup import fetch_line_profile_display_name
from services.homework_demo import (
    HomeworkBookingService,
    build_homework_gateway,
    build_homework_demo_config,
    extract_google_sheet_id,
    google_sheets_dependencies_status,
)
from services.web_ui_settings import (
    HOT_RELOADABLE_SECTIONS,
    ConfigValidationError,
    QueueConfigStore,
    editable_config_defaults,
    normalize_editable_config,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_FILE_PATH = _resolve_config_path()
config = load_config(str(CONFIG_FILE_PATH))
line_bot_config = config.get("line_bot", {})
telegram_bot_config = config.get("telegram_bot", {})
discord_bot_config = config.get("discord_bot", {})
queue_config = config.get("queue", {}) if isinstance(config.get("queue"), dict) else {}

CHANNEL_SECRET = line_bot_config.get("channel_secret", "")
CHANNEL_ACCESS_TOKEN = line_bot_config.get("channel_access_token", "")
TELEGRAM_BOT_TOKEN = telegram_bot_config.get("bot_token", "")
TELEGRAM_WEBHOOK_SECRET = telegram_bot_config.get("webhook_secret", "")
DISCORD_BOT_TOKEN = discord_bot_config.get("bot_token", "")
DISCORD_APPLICATION_ID = discord_bot_config.get("application_id", "")
DISCORD_PUBLIC_KEY = discord_bot_config.get("public_key", "")
ADMIN_IDS: list[str] = line_bot_config.get("admin_ids", ["admin_xxxxx", "another_admin"])
PLACEHOLDER_ADMIN_IDS = {"admin_xxxxx", "another_admin"}
ADMIN_RICH_MENU_ID = line_bot_config.get("admin_rich_menu_id", "")
ADMIN_RICH_MENU_PAGE2_ID = line_bot_config.get("admin_rich_menu_page2_id", "")
USER_RICH_MENU_ID = line_bot_config.get("user_rich_menu_id", "")
USER_RICH_MENU_PAGE2_ID = line_bot_config.get("user_rich_menu_page2_id", "")
LOCATION_OPTIONS = config.get("registration", {}).get("location_options", {"A": ["1", "2"], "B": ["1", "2"]})


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _read_template(name: str) -> str:
    return (TEMPLATES_DIR / name).read_text(encoding="utf-8")


def _render_dashboard_login_page(*, error_message: str = "", next_path: str = "/dashboard") -> str:
    template = _read_template("dashboard_login.html")
    return (
        template
        .replace("{error_message_block}", error_message)
        .replace("{next_path}", escape(next_path, quote=True))
    )


def _normalize_dashboard_next_path(next_path: str | None) -> str:
    candidate = str(next_path or "").strip()
    if candidate.startswith("//"):
        return "/dashboard"
    if candidate.startswith("/dashboard") or candidate.startswith("/settings"):
        return candidate
    if candidate in {"/", ""}:
        return "/dashboard"
    return "/dashboard"


def _render_dashboard_config_page(*, layout: dict, all_locations: list[str], auth_bootstrap: str) -> str:
    template = _read_template("dashboard_config.html")
    replacements = {
        '{layout.get("imageUrl", "")}': str(layout.get("imageUrl", "")),
        '{locations}': json.dumps(all_locations, ensure_ascii=False),
        '{initial_layout}': json.dumps(layout, ensure_ascii=False),
        '{auth_bootstrap}': auth_bootstrap,
    }
    for needle, value in replacements.items():
        template = template.replace(needle, value)
    return template


def _render_dashboard_settings_page(*, auth_bootstrap: str) -> str:
    template = _read_template("dashboard_settings.html")
    return template.replace("{auth_bootstrap}", auth_bootstrap)


def _render_dashboard_page(*, payload: dict, layout: dict, auth_bootstrap: str, markers_html: str) -> str:
    template = _read_template("dashboard.html")
    replacements = {
        "{payload['stats']['registered']}": str(payload["stats"]["registered"]),
        "{payload['stats']['queue']}": str(payload["stats"]["queue"]),
        "{payload['stats']['served']}": str(payload["stats"]["served"]),
        '{layout.get("imageUrl") or ""}': str(layout.get("imageUrl") or ""),
        "{''.join(markers_html)}": markers_html,
        '{initial_payload}': json.dumps(payload, ensure_ascii=False),
        '{auth_bootstrap}': auth_bootstrap,
    }
    for needle, value in replacements.items():
        template = template.replace(needle, value)
    return template


def _web_ui_config() -> dict:
    web_ui = config.get("web_ui", {})
    if not isinstance(web_ui, dict):
        return {}
    return web_ui


def _session_cookie_name() -> str:
    return str(_web_ui_config().get("session_cookie_name") or "queue_admin_session")


def _configured_web_ui_token() -> str:
    return str(_web_ui_config().get("admin_token") or "").strip()


def _session_secret() -> str:
    secret = str(_web_ui_config().get("session_secret") or "").strip()
    return secret or _configured_web_ui_token()


def _sign_web_ui_session(token: str) -> str:
    payload = token.strip().encode("utf-8")
    signature = hmac.new(_session_secret().encode("utf-8"), payload, hashlib.sha256).hexdigest()
    encoded_payload = base64.urlsafe_b64encode(payload).decode("ascii")
    return f"{encoded_payload}.{signature}"


def _unsign_web_ui_session(cookie_value: str) -> str:
    if not cookie_value or "." not in cookie_value:
        return ""
    encoded_payload, signature = cookie_value.split(".", 1)
    if not encoded_payload or not signature:
        return ""
    try:
        payload = base64.urlsafe_b64decode(encoded_payload.encode("ascii")).decode("utf-8")
    except Exception:
        return ""
    expected = hmac.new(_session_secret().encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not compare_digest(expected, signature):
        return ""
    return payload


def _extract_web_ui_token(request: Request) -> str:
    token = (request.headers.get("X-Admin-Token") or "").strip()
    if token:
        return token

    cookie_token = _unsign_web_ui_session((request.cookies.get(_session_cookie_name()) or "").strip())
    if cookie_token:
        return cookie_token

    web_ui = _web_ui_config()
    if web_ui.get("allow_query_token"):
        return (request.query_params.get("token") or "").strip()

    return ""


def _is_valid_web_ui_token(request: Request) -> bool:
    configured_token = _configured_web_ui_token()
    provided_token = _extract_web_ui_token(request)
    if not configured_token or not provided_token:
        return False
    return compare_digest(configured_token, provided_token)


def _should_protect_web_ui_reads() -> bool:
    return bool(_web_ui_config().get("protect_read_routes", False))


def _require_web_ui_auth(request: Request, *, protect_reads: bool = True, html_redirect: bool = False) -> None:
    configured_token = _configured_web_ui_token()
    if not configured_token:
        return
    if not protect_reads and not _should_protect_web_ui_reads():
        return
    if _is_valid_web_ui_token(request):
        return
    if html_redirect:
        next_path = quote(str(request.url.path or "/dashboard"), safe="/")
        if request.url.query:
            next_path = f"{next_path}%3F{quote(str(request.url.query), safe='=&')}"
        raise HTTPException(status_code=303, detail="Redirect", headers={"Location": f"/dashboard/login?next={next_path}"})
    raise HTTPException(status_code=401, detail="Unauthorized")


def _web_ui_bootstrap_script(request: Request) -> str:
    token = ""
    web_ui = _web_ui_config()
    if web_ui.get("allow_query_token"):
        token = (request.query_params.get("token") or "").strip()
    token_json = json.dumps(token, ensure_ascii=False)
    return (
        "          const AUTH_TOKEN_STORAGE_KEY = 'queue_admin_token';\n"
        f"          const bootToken = {token_json};\n"
        "          if (bootToken) localStorage.setItem('queue_admin_token', bootToken);\n\n"
        "          function getStoredAuthToken() {\n"
        "            try {\n"
        "              return localStorage.getItem('queue_admin_token') || '';\n"
        "            } catch (error) {\n"
        "              return bootToken || '';\n"
        "            }\n"
        "          }\n\n"
        "          function withAuthHeaders(init = {}) {\n"
        "            const token = getStoredAuthToken();\n"
        "            const headers = new Headers(init.headers || {});\n"
        "            if (token) headers.set('X-Admin-Token', token);\n"
        "            return { ...init, headers };\n"
        "          }\n\n"
        "          function withAuthUrl(url) {\n"
        "            const token = getStoredAuthToken();\n"
        "            if (!token) return url;\n"
        "            const next = new URL(url, window.location.origin);\n"
        "            if (!next.searchParams.has('token')) next.searchParams.set('token', token);\n"
        "            const path = next.pathname + next.search + next.hash;\n"
        "            if (next.origin === window.location.origin) return path;\n"
        "            return next.toString();\n"
        "          }\n"
    )


def _config_store() -> QueueConfigStore:
    return QueueConfigStore(CONFIG_FILE_PATH)


def _homework_credentials_path() -> Path:
    configured = str(os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")).strip()
    if configured:
        return Path(configured)
    return CONFIG_FILE_PATH.parent / "google-service-account.json"


def _validate_homework_google_credentials_json(credentials_json: str) -> dict:
    try:
        payload = json.loads(str(credentials_json or ""))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Google service account JSON 格式錯誤") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Google service account JSON 格式錯誤")
    required_keys = {"type", "client_email", "private_key", "token_uri"}
    missing = [key for key in required_keys if not str(payload.get(key) or "").strip()]
    if missing:
        raise HTTPException(status_code=400, detail=f"Google service account JSON 缺少必要欄位：{', '.join(missing)}")
    if str(payload.get("type") or "") != "service_account":
        raise HTTPException(status_code=400, detail="Google service account JSON type 必須為 service_account")
    return payload


def _validate_homework_demo_access(homework_payload: dict, *, force_validate: bool = False) -> dict:
    normalized_payload = dict(homework_payload or {})
    spreadsheet_id = extract_google_sheet_id(str(normalized_payload.get("spreadsheet_id") or ""))
    normalized_payload["spreadsheet_id"] = spreadsheet_id
    should_validate = bool(normalized_payload.get("enabled")) or force_validate
    if not should_validate:
        return {"spreadsheetId": spreadsheet_id, "sheetNames": []}
    if not spreadsheet_id:
        raise HTTPException(status_code=400, detail="Homework Demo 已啟用時必須提供 Google Sheet spreadsheet id 或 URL")
    dependencies_ready, dependency_message = google_sheets_dependencies_status()
    if not dependencies_ready:
        raise HTTPException(status_code=400, detail=dependency_message)

    credentials_path = _homework_credentials_path()
    if not credentials_path.exists():
        raise HTTPException(status_code=400, detail="尚未設定 Google service account JSON，請先在設定頁上傳")

    homework_config = build_homework_demo_config(normalized_payload)
    gateway = build_homework_gateway(homework_config)
    try:
        sheet_names = gateway.list_sheet_names(use_cache=False, force_refresh=True)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"無法存取 Google Sheet：{exc}") from exc
    return {
        "spreadsheetId": spreadsheet_id,
        "sheetNames": sheet_names,
    }


def _server_bind_config() -> tuple[str, int]:
    server_config = config.get("server", {}) if isinstance(config.get("server"), dict) else {}
    host = str(server_config.get("host") or "0.0.0.0").strip() or "0.0.0.0"
    try:
        port = int(server_config.get("port") or 8000)
    except (TypeError, ValueError):
        port = 8000
    if port < 1 or port > 65535:
        port = 8000
    return host, port


def _editable_settings_payload() -> dict:
    store = _config_store()
    return {
        "config": store.load_editable(),
        "rawYaml": store.load_text(),
        "defaults": editable_config_defaults(),
        "meta": _dashboard_settings_meta(),
    }


def _dashboard_settings_meta(*, homework_sheet_names: list[str] | None = None) -> dict:
    credentials_path = _homework_credentials_path()
    dependencies_ready, dependency_message = google_sheets_dependencies_status()
    return {
        "configPath": os.fspath(CONFIG_FILE_PATH),
        "hotReloadableSections": HOT_RELOADABLE_SECTIONS,
        "adminOptions": _resolve_admin_options(),
        "homeworkCredentialsPath": os.fspath(credentials_path),
        "homeworkCredentialsConfigured": credentials_path.exists(),
        "homeworkGoogleApiReady": dependencies_ready,
        "homeworkGoogleApiMessage": dependency_message,
        "homeworkLastValidatedSheetNames": list(homework_sheet_names or []),
    }


def _fetch_line_profile_display_name(user_id: str) -> str:
    return fetch_line_profile_display_name(channel_access_token=CHANNEL_ACCESS_TOKEN, user_id=user_id)


def _resolve_admin_options() -> list[dict[str, str]]:
    admin_records: dict[str, dict[str, str]] = {}

    for user_id in ADMIN_IDS:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id or normalized_user_id in PLACEHOLDER_ADMIN_IDS:
            continue
        admin_records[normalized_user_id] = {
            "user_id": normalized_user_id,
            "display_name": "",
        }

    if db_manager is not None:
        for admin in db_manager.get_all_admins():
            user_id = str(admin.get("user_id") or "").strip()
            display_name = str(admin.get("display_name") or "").strip()
            if not user_id:
                continue
            admin_records[user_id] = {
                "user_id": user_id,
                "display_name": display_name,
            }

    options: list[dict[str, str]] = []
    for admin in admin_records.values():
        user_id = admin["user_id"]
        display_name = admin["display_name"]
        line_display_name = _fetch_line_profile_display_name(user_id)
        preferred_name = line_display_name or display_name
        label = f"{preferred_name} ({user_id})" if preferred_name else user_id
        options.append(
            {
                "user_id": user_id,
                "display_name": display_name,
                "line_display_name": line_display_name,
                "label": label,
            }
        )
    return options


def _schedule_process_restart(*, delay_seconds: float = 0.25) -> None:
    def _restart_process() -> None:
        logger.warning("Settings UI requested process restart via SIGTERM")
        os.kill(os.getpid(), signal.SIGTERM)

    timer = threading.Timer(delay_seconds, _restart_process)
    timer.daemon = True
    timer.start()


def _runtime_location_options() -> dict[str, list[str]]:
    current_config = config.get("registration", {})
    if isinstance(current_config, dict) and isinstance(current_config.get("location_options"), dict):
        return current_config["location_options"]
    return {"A": ["1", "2"], "B": ["1", "2"]}


def _runtime_queue_config() -> dict:
    current_queue_config = config.get("queue", {})
    queue_settings = dict(current_queue_config) if isinstance(current_queue_config, dict) else {}
    raw_queue = _config_store().load_raw().get("queue")
    if isinstance(raw_queue, dict):
        for key in ("max_capacity", "timeout_minutes", "timeout_action"):
            if key not in raw_queue:
                queue_settings[key] = None
    return queue_settings


def _runtime_line_bot_config() -> dict:
    current_line_bot_config = config.get("line_bot", {})
    return current_line_bot_config if isinstance(current_line_bot_config, dict) else {}


def _apply_runtime_config(next_config: dict) -> None:
    global config, line_bot_config, queue_config, LOCATION_OPTIONS, notifier, line_handler, telegram_command_service, discord_command_service

    config = next_config
    line_bot_config = _runtime_line_bot_config()
    queue_config = _runtime_queue_config()
    LOCATION_OPTIONS = _runtime_location_options()

    if db_manager is None:
        return

    if queue_manager is not None:
        queue_manager.set_max_capacity(queue_config.get("max_capacity"))
        timeout_minutes = queue_config.get("timeout_minutes")
        db_manager.set_config("queue_timeout_minutes", "" if timeout_minutes is None else str(int(timeout_minutes)))
        db_manager.set_config("vip_enabled", "true" if bool(config.get("vip", {}).get("enabled", True)) else "false")
        db_manager.set_config("coffee_price", str(int(config.get("vip", {}).get("coffee_price", 60))))

    notifier = Notifier(
        CHANNEL_SECRET,
        CHANNEL_ACCESS_TOKEN,
        ADMIN_RICH_MENU_PAGE2_ID,
        discord_sender=_send_discord_text,
        telegram_sender=_send_telegram_text,
        db=db_manager,
        line_push_on_served=bool(line_bot_config.get("push_on_served", True)),
        dispatcher=notification_dispatcher,
    )

    if queue_manager is not None:
        queue_manager.notifier = notifier

    if queue_manager is not None and vip_service is not None:
        homework_service = None
        homework_config = build_homework_demo_config(config.get("homework_demo"))
        if homework_config.enabled and (homework_config.sheet_names or homework_config.spreadsheet_id):
            homework_service = HomeworkBookingService(
                config=homework_config,
                gateway=build_homework_gateway(homework_config),
            )
        line_handler = LineBotHandler(
            channel_secret=CHANNEL_SECRET,
            channel_access_token=CHANNEL_ACCESS_TOKEN,
            queue_manager=queue_manager,
            vip_service=vip_service,
            admin_ids=ADMIN_IDS,
            admin_rich_menu_id=ADMIN_RICH_MENU_ID,
            admin_rich_menu_page2_id=ADMIN_RICH_MENU_PAGE2_ID,
            user_rich_menu_id=USER_RICH_MENU_ID,
            user_rich_menu_page2_id=USER_RICH_MENU_PAGE2_ID,
            location_options=LOCATION_OPTIONS,
            announcement_service=dashboard_announcement_service,
            new_order_idle_seconds=int(config.get("tts", {}).get("new_order_idle_seconds", 300)),
            new_order_announcement_text=str(config.get("tts", {}).get("new_order_announcement_text", "您有新訂單")),
            telegram_sender=_send_telegram_text,
            notification_dispatcher=notification_dispatcher,
            line_display_name_resolver=_fetch_line_profile_display_name,
            special_serve_rules=queue_config.get("special_serve_rules"),
            homework_booking_service=homework_service,
        )
        telegram_command_service = TelegramCommandService(
            db=db_manager,
            queue_manager=queue_manager,
            channel_access_token=CHANNEL_ACCESS_TOKEN,
            telegram_sender=_send_telegram_text,
            notification_dispatcher=notification_dispatcher,
            line_display_name_resolver=_fetch_line_profile_display_name,
            location_options=LOCATION_OPTIONS,
            announcement_service=dashboard_announcement_service,
            special_serve_rules=queue_config.get("special_serve_rules"),
        )
        discord_command_service = DiscordCommandService(
            db=db_manager,
            location_options=LOCATION_OPTIONS,
            telegram_sender=_send_telegram_text,
            notification_dispatcher=notification_dispatcher,
            line_display_name_resolver=_fetch_line_profile_display_name,
        )


db_manager: DatabaseManager | None = None
queue_manager: QueueManager | None = None
vip_service: VipService | None = None
notifier: Notifier | None = None
notification_dispatcher: ThreadedDispatcher | None = None
line_handler: LineBotHandler | None = None
telegram_command_service: TelegramCommandService | None = None
discord_command_service: DiscordCommandService | None = None
dashboard_announcement_service: DashboardAnnouncementService | None = None


class DashboardLayoutStore:
    def __init__(self, root: str | Path = "dashboard_layout") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.layout_path = self.root / "layout.json"

    def load(self) -> dict:
        if not self.layout_path.exists():
            return {"imageUrl": "", "markers": []}
        try:
            data = json.loads(self.layout_path.read_text(encoding="utf-8"))
        except Exception:
            return {"imageUrl": "", "markers": []}
        if not isinstance(data, dict):
            return {"imageUrl": "", "markers": []}
        return {
            "imageUrl": data.get("imageUrl", ""),
            "markers": data.get("markers", []),
        }

    def save(self, payload: dict) -> dict:
        layout = {
            "imageUrl": payload.get("imageUrl", ""),
            "markers": payload.get("markers", []),
        }
        self.layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
        return layout

    def save_image(self, filename: str, content: bytes) -> str:
        ext = Path(filename or "layout.png").suffix or ".png"
        stored_name = f"{uuid4().hex}{ext}"
        target = self.root / stored_name
        target.write_bytes(content)
        image_url = f"/dashboard/assets/{stored_name}"
        current = self.load()
        self.save(
            {
                "imageUrl": image_url,
                "markers": current.get("markers", []),
            }
        )
        return image_url

    def resolve_asset(self, filename: str) -> Path:
        return self.root / Path(filename).name


dashboard_layout_store = DashboardLayoutStore()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Initialize DB and services on startup."""
    global db_manager, queue_manager, vip_service, notifier, notification_dispatcher, line_handler, telegram_command_service, discord_command_service, scheduler, dashboard_announcement_service
    from apscheduler.schedulers.background import BackgroundScheduler

    db_manager = DatabaseManager()
    notification_dispatcher = ThreadedDispatcher(max_workers=4)
    notifier = Notifier(
        CHANNEL_SECRET,
        CHANNEL_ACCESS_TOKEN,
        ADMIN_RICH_MENU_PAGE2_ID,
        discord_sender=_send_discord_text,
        telegram_sender=_send_telegram_text,
        db=db_manager,
        line_push_on_served=bool(line_bot_config.get("push_on_served", True)),
        dispatcher=notification_dispatcher,
    )
    queue_manager = QueueManager(db_manager, notifier)
    vip_service = VipService(db_manager)
    tts_config = config.get("tts", {}) if isinstance(config.get("tts"), dict) else {}
    dashboard_announcement_service = DashboardAnnouncementService(
        root="dashboard_announcements",
        public_base_path="/dashboard/audio",
        tts_service=GoogleCloudTTSService(
            enabled=bool(tts_config.get("enabled", False)),
            language_code=str(tts_config.get("language_code", "cmn-TW")),
            voice_name=str(tts_config.get("voice_name", "cmn-TW-Standard-A")),
            audio_encoding=str(tts_config.get("audio_encoding", "MP3")),
            speaking_rate=float(tts_config.get("speaking_rate", 1.0)),
            pitch=float(tts_config.get("pitch", 0.0)),
        ),
        announcement_template=str(tts_config.get("announcement_template", "來賓 {display_name} 請準備demo")),
        new_order_announcement_text=str(tts_config.get("new_order_announcement_text", "您有新訂單")),
    )
    homework_service = None
    homework_config = build_homework_demo_config(config.get("homework_demo"))
    if homework_config.enabled and (homework_config.sheet_names or homework_config.spreadsheet_id):
        homework_service = HomeworkBookingService(
            config=homework_config,
            gateway=build_homework_gateway(homework_config),
        )
    line_handler = LineBotHandler(
        channel_secret=CHANNEL_SECRET,
        channel_access_token=CHANNEL_ACCESS_TOKEN,
        queue_manager=queue_manager,
        vip_service=vip_service,
        admin_ids=ADMIN_IDS,
        admin_rich_menu_id=ADMIN_RICH_MENU_ID,
        admin_rich_menu_page2_id=ADMIN_RICH_MENU_PAGE2_ID,
        user_rich_menu_id=USER_RICH_MENU_ID,
        user_rich_menu_page2_id=USER_RICH_MENU_PAGE2_ID,
        location_options=LOCATION_OPTIONS,
        announcement_service=dashboard_announcement_service,
        new_order_idle_seconds=int(tts_config.get("new_order_idle_seconds", 300)),
        new_order_announcement_text=str(tts_config.get("new_order_announcement_text", "您有新訂單")),
        telegram_sender=_send_telegram_text,
        notification_dispatcher=notification_dispatcher,
        line_display_name_resolver=_fetch_line_profile_display_name,
        special_serve_rules=queue_config.get("special_serve_rules"),
        homework_booking_service=homework_service,
    )
    telegram_command_service = TelegramCommandService(
        db=db_manager,
        queue_manager=queue_manager,
        channel_access_token=CHANNEL_ACCESS_TOKEN,
        telegram_sender=_send_telegram_text,
        notification_dispatcher=notification_dispatcher,
        line_display_name_resolver=_fetch_line_profile_display_name,
        location_options=LOCATION_OPTIONS,
        announcement_service=dashboard_announcement_service,
        special_serve_rules=queue_config.get("special_serve_rules"),
    )
    discord_command_service = DiscordCommandService(
        db=db_manager,
        location_options=LOCATION_OPTIONS,
        telegram_sender=_send_telegram_text,
        notification_dispatcher=notification_dispatcher,
        line_display_name_resolver=_fetch_line_profile_display_name,
    )
    _apply_runtime_config(config)

    scheduler = BackgroundScheduler()
    scheduler.start()

    logger.info("Queue system started")
    yield
    logger.info("Queue system shutting down")
    scheduler.shutdown(wait=False)
    if notification_dispatcher is not None:
        notification_dispatcher.shutdown(wait=False)


app = FastAPI(
    title="Queue System - LINE Bot",
    version="2.0.0",
    lifespan=lifespan,
)


@app.exception_handler(404)
def not_found_redirect_handler(request: Request, exc: StarletteHTTPException):
    if request.method in {"GET", "HEAD"}:
        return RedirectResponse(url="/dashboard", status_code=307)
    return HTMLResponse(content="Not Found", status_code=404)


@app.get("/")
def health_check():
    return RedirectResponse(url="/dashboard", status_code=307)


@app.get("/health")
def health():
    return {"status": "healthy"}




def _send_discord_text(user_id: str, text: str) -> bool:
    if not DISCORD_BOT_TOKEN:
        logger.info("DISCORD_BOT_TOKEN 缺失，無法實際推送給 %s", user_id)
        return False

    discord_headers = {
        "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "DiscordBot (https://example.com, 1.0)",
    }
    dm_url = "https://discord.com/api/v10/users/@me/channels"
    message_url = None
    try:
        payload = json.dumps({"recipient_id": user_id}).encode("utf-8")
        request = urllib.request.Request(
            dm_url,
            data=payload,
            headers=discord_headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode("utf-8"))
        channel_id = str(body.get("id") or "").strip()
        if not channel_id:
            logger.error("Discord 建立 DM 成功但未返回 channel id user_id=%s body=%s", user_id, json.dumps(body, ensure_ascii=False))
            return False
        message_url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        message_payload = json.dumps({"content": text}).encode("utf-8")
        message_request = urllib.request.Request(
            message_url,
            data=message_payload,
            headers=discord_headers,
            method="POST",
        )
        with urllib.request.urlopen(message_request, timeout=10):
            return True
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        logger.error(
            "Discord 推播 HTTPError user_id=%s url=%s status=%s body=%s",
            user_id,
            message_url or dm_url,
            exc.code,
            detail,
        )
        logger.exception("Discord 推播失敗 user_id=%s url=%s", user_id, message_url or dm_url)
        return False
    except Exception:
        logger.exception("Discord 推播失敗 user_id=%s url=%s", user_id, message_url or dm_url)
        return False


def _parse_timestamp(value: str | None) -> datetime | None:
    dt = parse_timestamp(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TAIPEI_TZ)
    return dt.astimezone(TAIPEI_TZ)


def _build_dashboard_payload() -> dict:
    if db_manager is None:
        raise HTTPException(status_code=500, detail="資料庫尚未初始化")

    rows = sorted(str(row) for row in LOCATION_OPTIONS.keys())
    cols = sorted({str(col) for values in LOCATION_OPTIONS.values() for col in values})

    grid: dict[str, dict[str, dict]] = {
        row: {
            col: {
                "name": "",
                "location": f"{row}-{col}",
                "status": "empty",
                "statusLabel": "空位",
            }
            for col in cols
        }
        for row in rows
    }

    active_queue_entries = db_manager.get_all_queue()
    active_queue_user_ids = {entry.user_id for entry in active_queue_entries}
    status_labels = {
        "empty": "空位",
        "registered": "已註冊",
        "queued": "排隊中",
        "served": "已叫號",
        "locked": "已鎖定",
    }
    profiles = db_manager.get_all_user_profiles()

    blink_window = 30  # seconds after serve until blink stops and lock state takes over
    now = datetime.now(TAIPEI_TZ)

    for profile in profiles:
        if not profile.location or "-" not in profile.location:
            continue
        row_key, col_key = profile.location.split("-", 1)
        if row_key not in grid or col_key not in grid[row_key]:
            continue

        cell = grid[row_key][col_key]
        cell["name"] = profile.display_name
        cell["status"] = "registered"
        cell["recently_served"] = False

        if profile.user_id in active_queue_user_ids:
            cell["status"] = "queued"
        else:
            latest = db_manager.get_latest_queue_entry_for_user(profile.user_id)
            latest_joined_at = _parse_timestamp(latest.join_time if latest else None)
            profile_updated_at = _parse_timestamp(profile.updated_at)
            served_after_registration = bool(
                latest
                and latest.served_time
                and not latest.cancel_time
                and latest_joined_at
                and profile_updated_at
                and latest_joined_at >= profile_updated_at
            )
            if served_after_registration:
                serve_dt = _parse_timestamp(latest.served_time)
                is_still_locked = latest.release_time is None
                if serve_dt and is_still_locked and (now - serve_dt).total_seconds() <= blink_window:
                    cell["status"] = "served"
                    cell["recently_served"] = True
                elif is_still_locked:
                    cell["status"] = "locked"
                    cell["recently_served"] = False
                else:
                    cell["status"] = "registered"
                    cell["recently_served"] = False

        cell["statusLabel"] = status_labels[cell["status"]]

    stats = queue_manager.get_queue_stats()
    served_recent = db_manager.get_recent_served(limit=5)
    served_recent_payload = [
        {
            "user_id": item.get("user_id") or "",
            "display_name": item.get("display_name") or item.get("user_id") or "",
            "location": item.get("location") or "",
            "served_time": format_display_time(item.get("served_time")),
            "queue_type": item.get("queue_type") or "",
        }
        for item in served_recent
    ]

    profile_map = {profile.user_id: profile for profile in profiles}
    active_queue_payload = [
        {
            "user_id": entry.user_id,
            "display_name": (profile_map.get(entry.user_id).display_name if profile_map.get(entry.user_id) else entry.user_id),
            "location": (profile_map.get(entry.user_id).location if profile_map.get(entry.user_id) else ""),
            "queue_type": entry.queue_type,
            "queue_number": entry.queue_number,
            "join_time": format_display_time(entry.join_time),
        }
        for entry in active_queue_entries
    ]

    return {
        "rows": rows,
        "cols": cols,
        "grid": grid,
        "version": hashlib.md5(json.dumps({"rows": rows, "cols": cols, "grid": grid, "active_queue": active_queue_payload, "announcement": (dashboard_announcement_service.get_latest() if dashboard_announcement_service else None)}, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
        "legend": status_labels,
        "stats": {
            "registered": stats["registered"],
            "queue": stats["queue"],
            "served": stats["served"],
        },
        "served_recent": served_recent_payload,
        "active_queue": active_queue_payload,
        "announcement": dashboard_announcement_service.get_latest() if dashboard_announcement_service else None,
    }


@app.get("/dashboard/data")
def dashboard_data(request: Request) -> dict:
    _require_web_ui_auth(request, protect_reads=False)
    payload = _build_dashboard_payload()
    payload["layout"] = dashboard_layout_store.load()
    return payload


@app.post("/api/queue/reset")
def reset_queue(request: Request) -> dict:
    _require_web_ui_auth(request)
    if queue_manager is None:
        raise HTTPException(status_code=503, detail="Queue manager 尚未初始化")

    result = queue_manager.clear_all_queue()
    return {
        "status": "reset",
        "removed_count": result.get("removed_count", 0),
        "removed_users": result.get("removed_users", []),
        "cleared_profiles": result.get("cleared_profiles", 0),
        "cleared_served": result.get("cleared_served", 0),
    }


def _all_locations() -> list[str]:
    return [f"{row}-{col}" for row, cols in LOCATION_OPTIONS.items() for col in cols]


@app.get("/dashboard/layout")
def dashboard_layout(request: Request) -> dict:
    _require_web_ui_auth(request, protect_reads=False)
    return dashboard_layout_store.load()


@app.post("/dashboard/layout")
def save_dashboard_layout(request: Request, payload: dict) -> dict:
    _require_web_ui_auth(request)
    current_layout = dashboard_layout_store.load()
    markers = payload.get("markers", [])
    normalized_markers = []
    for marker in markers:
        if not isinstance(marker, dict):
            continue
        location = str(marker.get("location", "")).strip()
        if not location:
            continue
        normalized_markers.append(
            {
                "location": location,
                "x": max(0.0, min(100.0, float(marker.get("x", 0)))),
                "y": max(0.0, min(100.0, float(marker.get("y", 0)))),
                "label": str(marker.get("label", "")).strip(),
            }
        )
    return dashboard_layout_store.save({
        "imageUrl": str(payload.get("imageUrl", current_layout.get("imageUrl", ""))).strip(),
        "markers": normalized_markers,
    })


@app.post("/dashboard/layout/reset")
def reset_dashboard_layout(request: Request) -> dict:
    _require_web_ui_auth(request)
    layout = dashboard_layout_store.save({
        "imageUrl": dashboard_layout_store.load().get("imageUrl", ""),
        "markers": [],
    })
    return {"status": "reset", **layout}


@app.post("/dashboard/layout/image")
async def upload_dashboard_layout_image(request: Request, file: UploadFile = File(...)) -> dict:
    _require_web_ui_auth(request)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="圖片內容為空")
    image_url = dashboard_layout_store.save_image(file.filename or "layout.png", content)
    image_url_with_version = f"{image_url}?v={uuid4().hex}"
    layout = dashboard_layout_store.load()
    layout["imageUrl"] = image_url_with_version
    dashboard_layout_store.save(layout)
    return {"imageUrl": image_url_with_version}


@app.get("/dashboard/assets/{filename}")
def dashboard_asset(filename: str, request: Request):
    _require_web_ui_auth(request, protect_reads=False)
    target = dashboard_layout_store.resolve_asset(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="找不到圖片")
    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(target, media_type=media_type or "application/octet-stream")


@app.get("/dashboard/audio/{filename}")
def dashboard_audio_asset(filename: str, request: Request):
    _require_web_ui_auth(request, protect_reads=False)
    if dashboard_announcement_service is None:
        raise HTTPException(status_code=404, detail="找不到音訊")
    target = dashboard_announcement_service.resolve_audio_asset(filename)
    if not target.exists():
        raise HTTPException(status_code=404, detail="找不到音訊")
    media_type, _ = mimetypes.guess_type(target.name)
    return FileResponse(target, media_type=media_type or "audio/mpeg")


@app.get("/dashboard/login", response_class=HTMLResponse)
def dashboard_login_page(request: Request) -> str:
    next_path = _normalize_dashboard_next_path(request.query_params.get("next"))
    return _render_dashboard_login_page(next_path=next_path)


@app.post("/dashboard/login")
def dashboard_login(token: str = Form(...), next_path: str = Form("/dashboard", alias="next")):
    configured_token = _configured_web_ui_token()
    redirect_target = _normalize_dashboard_next_path(next_path)
    if not configured_token or not compare_digest(configured_token, token.strip()):
        return HTMLResponse(
            content=_render_dashboard_login_page(
                error_message='<p class="error">登入失敗，請確認 admin token。</p>',
                next_path=redirect_target,
            ),
            status_code=200,
        )

    response = RedirectResponse(url=redirect_target, status_code=303)
    response.set_cookie(
        key=_session_cookie_name(),
        value=_sign_web_ui_session(configured_token),
        httponly=True,
        samesite="lax",
    )
    return response


@app.post("/dashboard/logout")
def dashboard_logout():
    response = RedirectResponse(url="/dashboard/login", status_code=303)
    response.delete_cookie(_session_cookie_name())
    return response


@app.get("/settings", response_class=HTMLResponse)
def dashboard_settings_page(request: Request) -> str:
    _require_web_ui_auth(request, protect_reads=True, html_redirect=True)
    return _render_dashboard_settings_page(auth_bootstrap=_web_ui_bootstrap_script(request))


@app.get("/settings/data")
def dashboard_settings_data(request: Request) -> dict:
    _require_web_ui_auth(request, protect_reads=True)
    return _editable_settings_payload()


@app.post("/settings")
def save_dashboard_settings(request: Request, payload: dict) -> dict:
    _require_web_ui_auth(request)
    try:
        normalized = normalize_editable_config(payload)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    validation_result = _validate_homework_demo_access(normalized.get("homework_demo", {}))
    normalized["homework_demo"]["spreadsheet_id"] = validation_result["spreadsheetId"]

    saved = _config_store().save_editable(normalized)
    next_config = load_config(str(CONFIG_FILE_PATH))
    _apply_runtime_config(next_config)
    credentials_path = _homework_credentials_path()
    return {
        "status": "saved",
        "config": saved["config"],
        "rawYaml": saved["rawYaml"],
        "defaults": editable_config_defaults(),
        "meta": _dashboard_settings_meta(homework_sheet_names=validation_result["sheetNames"]),
    }


@app.post("/settings/homework/credentials")
def save_homework_credentials(request: Request, payload: dict) -> dict:
    _require_web_ui_auth(request)
    credentials_json = str(payload.get("credentialsJson") or "")
    parsed = _validate_homework_google_credentials_json(credentials_json)
    credentials_path = _homework_credentials_path()
    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    credentials_path.write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "saved",
        "message": "Google service account JSON 已更新",
        "meta": _dashboard_settings_meta(),
    }


@app.post("/settings/homework/validate")
def validate_homework_settings(request: Request, payload: dict) -> dict:
    _require_web_ui_auth(request)
    result = _validate_homework_demo_access(dict(payload or {}), force_validate=True)
    return {
        "status": "ok",
        "spreadsheetId": result["spreadsheetId"],
        "sheetNames": result["sheetNames"],
    }


@app.post("/settings/raw")
def save_dashboard_settings_raw(request: Request, payload: dict) -> dict:
    _require_web_ui_auth(request)
    raw_yaml = str(payload.get("rawYaml") or "")
    try:
        saved = _config_store().save_raw_text(raw_yaml)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    next_config = load_config(str(CONFIG_FILE_PATH))
    _apply_runtime_config(next_config)
    credentials_path = _homework_credentials_path()
    return {
        "status": "saved",
        "config": saved["config"],
        "rawYaml": saved["rawYaml"],
        "defaults": editable_config_defaults(),
        "meta": _dashboard_settings_meta(),
    }


@app.post("/settings/restart")
def restart_settings_runtime(request: Request) -> dict:
    _require_web_ui_auth(request)
    _schedule_process_restart()
    return {
        "status": "restarting",
        "message": "Restart requested. The container should come back automatically if restart policy is enabled.",
    }


@app.get("/dashboard/config", response_class=HTMLResponse)
def dashboard_config_page(request: Request) -> str:
    _require_web_ui_auth(request, protect_reads=False, html_redirect=True)
    layout = dashboard_layout_store.load()
    return _render_dashboard_config_page(
        layout=layout,
        all_locations=_all_locations(),
        auth_bootstrap=_web_ui_bootstrap_script(request),
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> str:
    _require_web_ui_auth(request, protect_reads=False, html_redirect=True)
    payload = _build_dashboard_payload()
    layout = dashboard_layout_store.load()
    markers_html = []
    for marker in layout.get("markers", []):
        location = marker.get("location", "")
        row, _, col = location.partition("-")
        cell = payload.get("grid", {}).get(row, {}).get(col)
        if not cell:
            continue
        markers_html.append(
            f'<div class="marker" data-location="{location}" data-x="{marker.get("x", 0)}" data-y="{marker.get("y", 0)}" style="visibility:hidden">'
            f'<div class="dot {cell["status"]}"></div>'
            f'<div class="tag">{marker.get("label") or location}<br>{cell.get("name") or cell.get("statusLabel")}</div>'
            f'</div>'
        )
    return _render_dashboard_page(
        payload=payload,
        layout=layout,
        auth_bootstrap=_web_ui_bootstrap_script(request),
        markers_html=''.join(markers_html),
    )


@app.post("/api/line/webhook")
async def webhook(request: Request):
    if line_handler is None:
        raise HTTPException(status_code=503, detail="LINE 處理器尚未初始化")

    body_bytes = await request.body()
    body = body_bytes.decode("utf-8")
    signature = request.headers.get("x-line-signature", "")

    logger.info("Received webhook: %s", signature)
    logger.info("Body: %s", body[:200])

    if CHANNEL_SECRET and not _verify_line_signature(signature, body, CHANNEL_SECRET):
        raise HTTPException(status_code=400, detail="LINE 簽章驗證失敗")

    try:
        payload = json.loads(body or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON 格式錯誤") from exc

    processed_events = 0
    replies_sent = 0

    for event in payload.get("events", []):
        handler_event = _normalize_event(event)
        if handler_event is None:
            continue

        processed_events += 1
        reply_actions = line_handler.handle_event(handler_event)
        if reply_actions:
            replies_sent += _send_replies(reply_actions)

    return {
        "status": "received",
        "processed_events": processed_events,
        "replies_sent": replies_sent,
    }


@app.post("/api/line/callback")
async def callback(request: Request):
    if vip_service is None:
        raise HTTPException(status_code=503, detail="VIP 服務尚未初始化")

    body_bytes = await request.body()
    body = body_bytes.decode("utf-8")
    logger.info("Received callback: %s", body[:200])

    try:
        payload = json.loads(body or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON 格式錯誤") from exc

    user_id = payload.get("userId")
    coffee_id = payload.get("coffeeId")
    amount = payload.get("amount")

    if not user_id:
        raise HTTPException(status_code=400, detail="缺少 userId")

    expected_amount = config.get("vip", {}).get("coffee_price", 60)
    if amount is not None:
        try:
            if int(amount) < int(expected_amount):
                raise HTTPException(status_code=400, detail="金額低於最低要求")
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="金額格式錯誤") from exc

    result = vip_service.record_purchase(
        user_id=user_id,
        platform="webhook",
        coffee_id=coffee_id,
        verified=True,
    )

    return {"status": "verified", **result}


@app.post("/api/discord/interactions")
async def discord_interactions(request: Request):
    if discord_command_service is None:
        raise HTTPException(status_code=503, detail="Discord 處理器尚未初始化")
    if not DISCORD_PUBLIC_KEY:
        raise HTTPException(status_code=503, detail="Discord public key 尚未設定")

    signature = request.headers.get("x-signature-ed25519", "")
    timestamp = request.headers.get("x-signature-timestamp", "")
    body_bytes = await request.body()

    if not _verify_discord_signature(signature, timestamp, body_bytes, DISCORD_PUBLIC_KEY):
        raise HTTPException(status_code=401, detail="Discord signature 驗證失敗")

    try:
        payload = json.loads(body_bytes.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON 格式錯誤") from exc

    logger.info("Discord interaction payload type=%s data=%s", payload.get("type"), json.dumps(payload.get("data") or {}, ensure_ascii=False)[:1000])

    if payload.get("type") == 1:
        return {"type": 1}

    extracted = _extract_discord_input(payload)
    if extracted is None:
        return {"type": 4, "data": {"content": "目前尚未支援此 Discord interaction。", "flags": 64}}

    user_id, input_value = extracted
    channel_id = str(payload.get("channel_id") or "").strip()
    if db_manager is not None and user_id:
        db_manager.set_config(f"discord_user:{user_id}", "1")
        if channel_id:
            db_manager.set_config(f"discord_channel:{user_id}", channel_id)

    result = discord_command_service.handle_interaction(user_id=user_id, input_value=input_value)
    response_payload = _discord_response_message(result, ephemeral=payload.get("type") == 2)
    logger.info("Discord interaction user_id=%s input=%s result=%s response=%s", user_id, input_value, json.dumps(result, ensure_ascii=False)[:1000], json.dumps(response_payload, ensure_ascii=False)[:1000])
    return response_payload


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request):
    if telegram_command_service is None:
        raise HTTPException(status_code=503, detail="Telegram 處理器尚未初始化")

    secret_token = request.headers.get("x-telegram-bot-api-secret-token", "")
    if TELEGRAM_WEBHOOK_SECRET and secret_token != TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Telegram secret token 驗證失敗")

    body_bytes = await request.body()
    body = body_bytes.decode("utf-8")
    logger.info("Received telegram webhook: %s", body[:200])

    try:
        payload = json.loads(body or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON 格式錯誤") from exc

    message = _normalize_telegram_update(payload)
    if message is None:
        return {
            "status": "received",
            "processed_updates": 0,
            "replies_sent": 0,
        }

    db_manager.set_config(f"telegram_user:{message['user_id']}", "1")
    result = telegram_command_service.handle_text(user_id=message["user_id"], text=message["text"])
    reply_message = result.get("message")
    reply_markup = _legacy_telegram_reply_markup(result.get("reply_markup"))
    replies_sent = 0
    if reply_message:
        if _send_telegram_text(message["chat_id"], str(reply_message), reply_markup=reply_markup):
            replies_sent = 1

    return {
        "status": "received",
        "processed_updates": 1,
        "replies_sent": replies_sent,
    }


def _verify_discord_signature(signature: str, timestamp: str, body: bytes, public_key: str) -> bool:
    if not signature or not timestamp or not public_key:
        return False
    try:
        verifier = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key))
        verifier.verify(bytes.fromhex(signature), timestamp.encode("utf-8") + body)
        return True
    except (ValueError, InvalidSignature, TypeError):
        return False


def _discord_response_message(result: dict, *, ephemeral: bool = False) -> dict:
    if result.get("status") == "modal":
        modal = result.get("modal") or {}
        components = []
        for row in modal.get("components", []):
            row_components = row.get("components", []) if isinstance(row, dict) else row
            components.append(
                {
                    "type": 1,
                    "components": [
                        {
                            "type": 4,
                            "custom_id": item["custom_id"],
                            "label": item["label"],
                            "style": 1 if item.get("style") == "paragraph" else 1,
                            "min_length": item.get("min_length", 1),
                            "max_length": item.get("max_length", 100),
                            "required": bool(item.get("required", True)),
                            **({"placeholder": item["placeholder"]} if item.get("placeholder") else {}),
                        }
                        for item in row_components
                    ],
                }
            )
        return {
            "type": 9,
            "data": {
                "custom_id": str(modal.get("custom_id") or ""),
                "title": str(modal.get("title") or "設定資料"),
                "components": components,
            },
        }

    data = {
        "content": str(result.get("message") or ""),
    }
    components = result.get("components")
    if components:
        data["components"] = components
    if ephemeral:
        data["flags"] = 64
    return {"type": 4, "data": data}


def _flatten_discord_command_options(options: list[dict] | None) -> list[str]:
    flattened: list[str] = []
    for option in options or []:
        if not isinstance(option, dict):
            continue
        value = option.get("value")
        if value is not None:
            text = str(value).strip()
            if text:
                flattened.append(text)
        nested = option.get("options")
        if isinstance(nested, list):
            flattened.extend(_flatten_discord_command_options(nested))
    return flattened


def _extract_discord_input(payload: dict) -> tuple[str, str] | None:
    interaction_type = payload.get("type")
    if interaction_type == 2:
        member = payload.get("member") or {}
        user = member.get("user") or payload.get("user") or {}
        user_id = str(user.get("id") or "").strip()
        data = payload.get("data") or {}
        command_name = str(data.get("name") or "").strip()
        options = _flatten_discord_command_options(data.get("options"))
        if user_id and command_name:
            suffix = f" {' '.join(options)}" if options else ""
            return user_id, f"/{command_name}{suffix}"
        return None

    if interaction_type == 3:
        member = payload.get("member") or {}
        user = member.get("user") or payload.get("user") or {}
        user_id = str(user.get("id") or "").strip()
        data = payload.get("data") or {}
        custom_id = str(data.get("custom_id") or "").strip()
        if user_id and custom_id:
            return user_id, custom_id
        return None

    if interaction_type == 5:
        member = payload.get("member") or {}
        user = member.get("user") or payload.get("user") or {}
        user_id = str(user.get("id") or "").strip()
        data = payload.get("data") or {}
        custom_id = str(data.get("custom_id") or "").strip()
        if custom_id != "register:submit" or not user_id:
            return None
        for row in data.get("components", []):
            for item in row.get("components", []):
                if str(item.get("custom_id") or "") == "student_id":
                    value = str(item.get("value") or "").strip()
                    return user_id, f"register:submit:{value}"
        return user_id, "register:submit:"

    return None


    if event.get("type") != "message":
        return None

    message = event.get("message") or {}
    if message.get("type") != "text":
        return None

    source = event.get("source") or {}
    user_id = source.get("userId")
    reply_token = event.get("replyToken", "")
    if not user_id or not reply_token:
        return None

    class _Message:
        def __init__(self, text: str) -> None:
            self.type = "text"
            self.text = text

    class _Source:
        def __init__(self, user_id: str) -> None:
            self.userId = user_id

    class _Event:
        def __init__(self, text: str, user_id: str, reply_token: str) -> None:
            self.message = _Message(text)
            self.source = _Source(user_id)
            self.reply_token = reply_token
            self.replyToken = reply_token

    return _Event(message.get("text", ""), user_id, reply_token)


def _verify_line_signature(signature: str, body: str, channel_secret: str) -> bool:
    if not signature:
        return False

    try:
        from linebot.v3.webhooks import SignatureValidator

        return SignatureValidator(channel_secret).validate(body, signature)
    except ImportError:
        try:
            import base64
            import hashlib
            import hmac

            digest = hmac.new(
                channel_secret.encode("utf-8"),
                body.encode("utf-8"),
                hashlib.sha256,
            ).digest()
            expected = base64.b64encode(digest).decode("utf-8")
            return compare_digest(expected, signature)
        except Exception:
            return False


def _normalize_event(event: dict):
    source = event.get("source") or {}
    user_id = source.get("userId")
    reply_token = event.get("replyToken", "")
    if not user_id or not reply_token:
        return None

    text = ""
    if event.get("type") == "message":
        message = event.get("message") or {}
        if message.get("type") != "text":
            return None
        text = str(message.get("text", ""))
    elif event.get("type") == "postback":
        postback = event.get("postback") or {}
        text = str(postback.get("data") or "").strip()
        if not text:
            return None
    else:
        return None

    class _Message:
        def __init__(self, text: str) -> None:
            self.type = "text"
            self.text = text

    class _Source:
        def __init__(self, user_id: str) -> None:
            self.userId = user_id

    class _Event:
        def __init__(self, text: str, user_id: str, reply_token: str) -> None:
            self.message = _Message(text)
            self.source = _Source(user_id)
            self.reply_token = reply_token
            self.replyToken = reply_token

    return _Event(text, user_id, reply_token)


def _normalize_telegram_update(payload: dict) -> dict | None:
    callback_query = payload.get("callback_query") or {}
    if isinstance(callback_query, dict) and callback_query:
        data = str(callback_query.get("data") or "").strip()
        message = callback_query.get("message") or {}
        sender = callback_query.get("from") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        user_id = sender.get("id")
        if data and chat_id is not None and user_id is not None:
            return {
                "chat_id": str(chat_id),
                "user_id": str(user_id),
                "text": data,
            }

    message = payload.get("message") or payload.get("edited_message") or {}
    if not isinstance(message, dict):
        return None

    text = str(message.get("text") or "").strip()
    if not text:
        return None

    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = chat.get("id")
    user_id = sender.get("id")
    if chat_id is None or user_id is None:
        return None

    return {
        "chat_id": str(chat_id),
        "user_id": str(user_id),
        "text": text,
    }


def _legacy_telegram_reply_markup(reply_markup: dict | None) -> dict | None:
    if not isinstance(reply_markup, dict):
        return reply_markup

    inline_keyboard = reply_markup.get("inline_keyboard")
    if not isinstance(inline_keyboard, list):
        return reply_markup

    legacy_rows: list[list[dict]] = []
    changed = False
    for row in inline_keyboard:
        if not isinstance(row, list):
            legacy_rows.append(row)
            continue
        legacy_row: list[dict] = []
        for button in row:
            if not isinstance(button, dict):
                legacy_row.append(button)
                continue
            callback_data = button.get("callback_data")
            if isinstance(callback_data, str):
                if callback_data.startswith("register:group:"):
                    callback_data = callback_data.removeprefix("register:group:")
                    changed = True
                elif callback_data.startswith("register:item:"):
                    callback_data = callback_data.removeprefix("register:item:")
                    changed = True
            legacy_row.append({**button, **({"callback_data": callback_data} if isinstance(callback_data, str) else {})})
        legacy_rows.append(legacy_row)

    if not changed:
        return reply_markup
    return {**reply_markup, "inline_keyboard": legacy_rows}


def _send_telegram_text(chat_id: str, text: str, reply_markup: dict | None = None) -> bool:
    reply_markup = _legacy_telegram_reply_markup(reply_markup)
    if not TELEGRAM_BOT_TOKEN:
        logger.info("Telegram bot token 缺失；已產生回覆但未送出")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    request_payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None:
        request_payload["reply_markup"] = reply_markup
    payload = json.dumps(request_payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            status = getattr(response, "status", 200)
            return int(status) < 400
    except urllib.error.HTTPError as exc:
        logger.warning("Telegram sendMessage failed: %s", exc)
        return False
    except Exception as exc:
        logger.warning("Telegram sendMessage error: %s", exc)
        return False


def _send_replies(reply_actions: list) -> int:
    if not reply_actions:
        return 0

    if not CHANNEL_ACCESS_TOKEN:
        logger.info("LINE access token 缺失；已產生回覆動作但未送出")
        return len(reply_actions)

    sent = 0
    for action in reply_actions:
        reply_token = getattr(action, "replyToken", None)
        payload_messages = None
        if isinstance(action, dict):
            reply_token = action.get("replyToken", reply_token)
            payload_messages = _line_message_payloads_from_action(action)
        if not reply_token or not payload_messages:
            continue
        try:
            payload = json.dumps({"replyToken": reply_token, "messages": payload_messages}, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                "https://api.line.me/v2/bot/message/reply",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                status = int(getattr(response, "status", 200))
                if status >= 400:
                    logger.warning("LINE reply_message failed status=%s", status)
        except Exception as exc:
            logger.warning("LINE reply_message error: %s", exc)
        sent += 1

    return sent


def _line_message_payloads_from_action(action: dict) -> list[dict]:
    raw_messages = action.get("messages")
    if isinstance(raw_messages, list) and raw_messages:
        return raw_messages

    text = action.get("text")
    if text is None:
        return []

    message = {"type": "text", "text": str(text)}
    quick_options = action.get("quickReply", {}).get("items", [])
    if quick_options:
        items = []
        for option in quick_options:
            action_payload = option.get("action", option) if isinstance(option, dict) else option
            if not isinstance(action_payload, dict):
                continue
            items.append(
                {
                    "type": "action",
                    "action": {
                        "type": "message",
                        "label": str(action_payload.get("label") or action_payload.get("text") or "操作"),
                        "text": str(action_payload.get("text") or action_payload.get("label") or ""),
                    },
                }
            )
        if items:
            message["quickReply"] = {"items": items}
    return [message]


if __name__ == "__main__":
    import uvicorn

    host, port = _server_bind_config()
    uvicorn.run(app, host=host, port=port)
