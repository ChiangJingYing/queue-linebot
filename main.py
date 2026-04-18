"""FastAPI entry point for queue LINE Bot."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from hmac import compare_digest
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from bot.handler import LineBotHandler
from config import load_config
from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.notifier import Notifier
from services.vip_service import VipService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = load_config()
line_bot_config = config.get("line_bot", {})

CHANNEL_SECRET = line_bot_config.get("channel_secret", "")
CHANNEL_ACCESS_TOKEN = line_bot_config.get("channel_access_token", "")
ADMIN_IDS: list[str] = line_bot_config.get("admin_ids", ["admin_xxxxx", "another_admin"])
ADMIN_RICH_MENU_ID = line_bot_config.get("admin_rich_menu_id", "")
USER_RICH_MENU_ID = line_bot_config.get("user_rich_menu_id", "")
LOCATION_OPTIONS = config.get("registration", {}).get("location_options", {"A": ["1", "2"], "B": ["1", "2"]})


db_manager: DatabaseManager | None = None
queue_manager: QueueManager | None = None
vip_service: VipService | None = None
notifier: Notifier | None = None
line_handler: LineBotHandler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Initialize DB and services on startup."""
    global db_manager, queue_manager, vip_service, notifier, line_handler, scheduler
    from apscheduler.schedulers.background import BackgroundScheduler

    db_manager = DatabaseManager()
    notifier = Notifier(CHANNEL_SECRET, CHANNEL_ACCESS_TOKEN)
    queue_manager = QueueManager(db_manager, notifier)
    vip_service = VipService(db_manager)
    line_handler = LineBotHandler(
        channel_secret=CHANNEL_SECRET,
        channel_access_token=CHANNEL_ACCESS_TOKEN,
        queue_manager=queue_manager,
        vip_service=vip_service,
        admin_ids=ADMIN_IDS,
        admin_rich_menu_id=ADMIN_RICH_MENU_ID,
        user_rich_menu_id=USER_RICH_MENU_ID,
        location_options=LOCATION_OPTIONS,
    )

    scheduler = BackgroundScheduler()
    from scheduler import register_timeout_job
    register_timeout_job(scheduler, queue_manager, notifier)
    scheduler.start()

    logger.info("Queue system started")
    yield
    logger.info("Queue system shutting down")
    scheduler.shutdown(wait=False)


app = FastAPI(
    title="Queue System - LINE Bot",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/")
def health_check():
    return {"status": "ok", "system": "queue-linebot"}


@app.get("/health")
def health():
    return {"status": "healthy"}


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.fromisoformat(value.replace(" ", "T"))
        except ValueError:
            return None


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

    active_queue = {entry.user_id for entry in db_manager.get_all_queue()}
    status_labels = {
        "empty": "空位",
        "registered": "已註冊",
        "queued": "排隊中",
        "served": "已叫號",
    }
    profiles = db_manager.get_all_user_profiles()

    for profile in profiles:
        if not profile.location or "-" not in profile.location:
            continue
        row_key, col_key = profile.location.split("-", 1)
        if row_key not in grid or col_key not in grid[row_key]:
            continue

        cell = grid[row_key][col_key]
        cell["name"] = profile.display_name
        cell["status"] = "registered"

        if profile.user_id in active_queue:
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
                cell["status"] = "served"

        cell["statusLabel"] = status_labels[cell["status"]]

    digest_source = json.dumps({"rows": rows, "cols": cols, "grid": grid}, ensure_ascii=False, sort_keys=True)
    version = hashlib.md5(digest_source.encode("utf-8")).hexdigest()
    return {
        "rows": rows,
        "cols": cols,
        "grid": grid,
        "version": version,
        "legend": status_labels,
    }


@app.get("/dashboard/data")
def dashboard_data() -> dict:
    return _build_dashboard_payload()


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> str:
    payload = _build_dashboard_payload()
    rows = payload["rows"]
    cols = payload["cols"]

    header = "".join(f"<th>{c}</th>" for c in cols)

    def _cell_markup(cell: dict) -> str:
        color = {
            "empty": "empty",
            "registered": "blue",
            "queued": "yellow",
            "served": "green",
        }.get(cell["status"], "empty")
        name = cell["name"] or "空位"
        return (
            f'<div class="lamp {color}"></div>'
            f'<div class="label">{name}</div>'
            f'<div class="sub">{cell["location"]}</div>'
            f'<div class="status">{cell.get("statusLabel", cell["status"])}</div>'
        )

    body = "".join(
        "<tr><th>{row}</th>{cells}</tr>".format(
            row=r,
            cells="".join(
                f'<td data-row="{r}" data-col="{c}">{_cell_markup(payload["grid"][r][c])}</td>'
                for c in cols
            ),
        )
        for r in rows
    )
    initial_payload = json.dumps(payload, ensure_ascii=False)

    return f"""
    <html>
      <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
        <title>位置看板</title>
        <style>
          body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#0f172a; color:#e2e8f0; padding:24px; }}
          h1 {{ margin-bottom: 8px; }}
          .legend {{ display:flex; flex-wrap:wrap; gap:16px; margin-bottom:16px; }}
          .legend span {{ display:flex; align-items:center; gap:8px; }}
          .lamp {{ width:14px; height:14px; border-radius:999px; display:inline-block; box-shadow:0 0 12px currentColor; margin:0 auto 8px; }}
          .empty {{ background:#64748b; color:#64748b; }}
          .blue {{ background:#38bdf8; color:#38bdf8; }}
          .yellow {{ background:#facc15; color:#facc15; }}
          .green {{ background:#22c55e; color:#22c55e; }}
          table {{ border-collapse:collapse; width:100%; background:#111827; }}
          th, td {{ border:1px solid #334155; padding:14px; text-align:center; min-width:100px; }}
          th {{ background:#1e293b; }}
          .label {{ font-weight:700; }}
          .sub {{ color:#94a3b8; font-size:12px; margin-top:4px; }}
          .status {{ font-size:12px; margin-top:6px; color:#cbd5e1; }}
          .pulse {{ animation:pulse .5s ease-in-out 2; }}
          @keyframes pulse {{ 0% {{ transform:scale(1); }} 50% {{ transform:scale(1.04); }} 100% {{ transform:scale(1); }} }}
        </style>
      </head>
      <body>
        <h1>位置看板</h1>
        <div class=\"legend\">
          <span><i class=\"lamp empty\"></i> 空位</span>
          <span><i class=\"lamp blue\"></i> 已註冊</span>
          <span><i class=\"lamp yellow\"></i> 排隊中</span>
          <span><i class=\"lamp green\"></i> 已叫號</span>
        </div>
        <table>
          <thead><tr><th></th>{header}</tr></thead>
          <tbody>{body}</tbody>
        </table>
        <script>
          const COLOR_MAP = {{ empty: 'empty', registered: 'blue', queued: 'yellow', served: 'green' }};
          let currentVersion = null;
          let previousGrid = null;

          function renderCell(cell, container) {{
            const color = COLOR_MAP[cell.status] || 'empty';
            const name = cell.name || '空位';
            container.classList.add('pulse');
            container.innerHTML = `
              <div class="lamp ${{color}}"></div>
              <div class="label">${{name}}</div>
              <div class="sub">${{cell.location}}</div>
              <div class="status">${{cell.statusLabel || cell.status}}</div>
            `;
            setTimeout(() => container.classList.remove('pulse'), 600);
          }}

          function syncChangedCells(payload) {{
            for (const row of payload.rows) {{
              for (const col of payload.cols) {{
                const nextCell = payload.grid[row][col];
                const prevCell = previousGrid?.[row]?.[col];
                if (JSON.stringify(prevCell) === JSON.stringify(nextCell)) continue;
                const target = document.querySelector(`td[data-row="${{row}}"][data-col="${{col}}"]`);
                if (target) renderCell(nextCell, target);
              }}
            }}
            previousGrid = payload.grid;
            currentVersion = payload.version;
          }}

          function render(payload) {{
            syncChangedCells(payload);
          }}

          async function pollDashboard() {{
            try {{
              const response = await fetch('/dashboard/data', {{ cache: 'no-store' }});
              const payload = await response.json();
              if (payload.version !== currentVersion) render(payload);
            }} catch (error) {{
              console.error('dashboard poll failed', error);
            }}
          }}

          render({initial_payload});
          setInterval(pollDashboard, 3000);
        </script>
      </body>
    </html>
    """


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


def _send_replies(reply_actions: list) -> int:
    if not reply_actions:
        return 0

    try:
        from linebot.v3.messaging import (
            ApiClient,
            Configuration,
            MessagingApi,
            ReplyMessageRequest,
            TextMessage,
            QuickReply,
            QuickReplyItem,
            MessageAction,
        )
    except Exception:
        logger.info("LINE SDK 無法使用或已損毀；已產生回覆動作但未送出")
        return len(reply_actions)

    if not CHANNEL_ACCESS_TOKEN:
        logger.info("LINE access token 缺失；已產生回覆動作但未送出")
        return len(reply_actions)

    sent = 0
    configuration = Configuration(access_token=CHANNEL_ACCESS_TOKEN)

    with ApiClient(configuration) as api_client:
        messaging_api = MessagingApi(api_client)
        for action in reply_actions:
            reply_token = getattr(action, "replyToken", None)
            text = getattr(action, "text", None)
            quick_options = []
            if isinstance(action, dict):
                reply_token = action.get("replyToken", reply_token)
                text = action.get("text", text)
                quick_options = action.get("quickReply", [])

            if not reply_token or text is None:
                continue

            message = TextMessage(text=text)
            if quick_options:
                try:
                    message = TextMessage(
                        text=text,
                        quick_reply=QuickReply(
                            items=[
                                QuickReplyItem(
                                    action=MessageAction(
                                        label=(option.get("label") if isinstance(option, dict) else option),
                                        text=(option.get("text") if isinstance(option, dict) else option),
                                    )
                                )
                                for option in quick_options
                            ]
                        ),
                    )
                except Exception:
                    message = TextMessage(text=text)

            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[message],
                )
            )
            sent += 1

    return sent


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
