"""FastAPI entry point for queue LINE Bot."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import yaml
from fastapi import FastAPI, Request
from line_bot_sdk import (
    AbstractEventHandler,
    models as line_models,
    HttpResponse,
    HTTPClient,
)

from core.database import DatabaseManager
from core.queue_manager import QueueManager
from services.vip_service import VipService
from services.notifier import Notifier
from core.validators import validate_command, validate_user_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

db_manager: DatabaseManager | None = None
queue_manager: QueueManager | None = None
vip_service: VipService | None = None
notifier: Notifier | None = None

# Admin IDs (can be loaded from config)
ADMIN_IDS: list[str] = ["admin_xxxxx", "another_admin"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Initialize DB and services on startup."""
    global db_manager, queue_manager, vip_service, notifier
    db_manager = DatabaseManager()
    queue_manager = QueueManager(db_manager)
    vip_service = VipService(db_manager)
    notifier = Notifier()
    logger.info("Queue system started")
    yield
    logger.info("Queue system shutting down")


app = FastAPI(
    title="Queue System - LINE Bot",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/")
def health_check():
    """Health check endpoint."""
    return {"status": "ok", "system": "queue-linebot"}


@app.get("/health")
def health():
    """Simple health check."""
    return {"status": "healthy"}


@app.post("/api/line/webhook")
async def webhook(request: Request):
    """LINE Bot webhook endpoint.

    Receives LINE events and dispatches to appropriate handlers.
    """
    body_bytes = await request.body()
    body = body_bytes.decode("utf-8")
    signature = request.headers.get("x-line-signature", "")

    logger.info(f"Received webhook: {signature}")
    logger.info(f"Body: {body[:200]}")

    return {"status": "received"}


@app.post("/api/line/callback")
async def callback(request: Request):
    """LINE callback endpoint (for Buy-a-Coffee callback)."""
    body_bytes = await request.body()
    body = body_bytes.decode("utf-8")
    logger.info(f"Received callback: {body[:200]}")

    return {"status": "received"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
