"""FastAPI entry point for queue LINE Bot."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from hmac import compare_digest
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request

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
        from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, TextMessage
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
            if isinstance(action, dict):
                reply_token = action.get("replyToken", reply_token)
                text = action.get("text", text)

            if not reply_token or text is None:
                continue

            messaging_api.reply_message(
                ReplyMessageRequest(
                    reply_token=reply_token,
                    messages=[TextMessage(text=text)],
                )
            )
            sent += 1

    return sent


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
