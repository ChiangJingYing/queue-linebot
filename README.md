# queue-linebot

A lightweight queue management system with a LINE Bot-style command handler, SQLite persistence, VIP queue support, scheduled timeout/reminder checks, and a tested Python service layer.

## Features

- Regular and VIP queues
- Queue join / cancel / serve / skip flows
- SQLite-backed persistence
- Queue capacity and timeout configuration
- VIP purchase tracking
- Scheduler helpers for timeout cleanup and reminders
- LINE-style bot command handler
- Comprehensive pytest coverage

## Requirements

- Python 3.11+
- pip

## Installation

```bash
git clone <your-repo-url>
cd queue-linebot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Google Cloud TTS dependency

This project supports dashboard voice announcements via Google Cloud Text-to-Speech.
The Python SDK is included in `requirements.txt` and `pyproject.toml`.

## Rich Menu 上傳

已提供兩套 6 格 Rich Menu 定義：

- `rich_menus/user_rich_menu.json`
- `rich_menus/admin_rich_menu.json`

可使用腳本上傳並自動寫回設定：

```bash
python scripts/upload_rich_menus.py \
  --admin-image assets/admin-rich-menu.png \
  --user-image assets/user-rich-menu.png \
  --write-config
```

執行後會：
- 建立 admin / user rich menu
- 上傳對應圖片
- 輸出 rich menu id
- 若加上 `--write-config`，會回寫 `queue_config.yaml` 的：
  - `line_bot.admin_rich_menu_id`
  - `line_bot.user_rich_menu_id`

圖片需自行準備，建議尺寸 `2500x1686`。

## Running the app

Before starting, copy `.env.example` to `.env` and fill in the required values.

```bash
cp .env.example .env
```

Start the FastAPI server:

```bash
python main.py
```

Or with uvicorn directly:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Environment variables

### Required for LINE bot

- `LINE_CHANNEL_SECRET`
- `LINE_CHANNEL_TOKEN`

### Recommended for dashboard login

- `WEB_UI_ADMIN_TOKEN`
- `WEB_UI_SESSION_SECRET`

### Optional for Google Cloud TTS dashboard announcements

- `GOOGLE_CLOUD_TTS_ENABLED=true`
- `GOOGLE_CLOUD_TTS_LANGUAGE_CODE=cmn-TW`
- `GOOGLE_CLOUD_TTS_VOICE_NAME=cmn-TW-Standard-A`
- `GOOGLE_CLOUD_TTS_AUDIO_ENCODING=MP3`
- `GOOGLE_CLOUD_TTS_SPEAKING_RATE=1.0`
- `GOOGLE_CLOUD_TTS_PITCH=0.0`
- `DASHBOARD_ANNOUNCEMENT_TEMPLATE=來賓 {display_name} 請準備demo`
- `GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/google-service-account.json`

### Recommended Traditional Chinese voice preset

For a stable default, this repo currently recommends:

- language code: `cmn-TW`
- voice name: `cmn-TW-Standard-A`
- audio encoding: `MP3`
- speaking rate: `1.0`
- pitch: `0.0`

## Dashboard audio announcement flow

When an admin runs:

- `/admin/serve`
- `/admin/serve [user_id]`

The system now:

1. serves the queue entry normally,
2. builds an announcement text from `display_name`,
3. stores the latest dashboard announcement payload,
4. generates audio through Google Cloud TTS when enabled,
5. exposes the audio through `/dashboard/audio/{filename}`,
6. lets the dashboard page poll and play the latest announcement after audio is enabled in the browser.

If Google Cloud credentials or SDK are missing, the queue serve flow still works and only the audio generation is skipped.

Health endpoints:

- `GET /`
- `GET /health`

## Running tests

Run the full test suite:

```bash
python -m pytest tests/ -v
```

Run with coverage:

```bash
python -m pytest tests/ -v --cov=core --cov=services
```

## Project structure

```text
queue-linebot/
├── bot/                # Bot command handling and push helpers
├── core/               # Database, models, validation, queue manager
├── scheduler/          # Timeout/reminder scheduled tasks
├── services/           # Notifier and VIP service
├── tests/              # Unit/integration tests
├── main.py             # FastAPI entry point
├── requirements.txt    # Python dependencies
└── queue_config.yaml   # Runtime config sample
```

## Command interface

### User commands

- `/join` — join the regular queue as yourself
- `/join vip` — join the VIP queue as yourself
- `/join [user_id] [regular|vip]` — join for a specific user id
- `/cancel` — cancel your queue entry
- `/status` — show current queue counts
- `/history` — show your queue history
- `/remind N` — request a reminder when your position reaches `N`
- `/coffee` — show VIP purchase link
- `/help` — show available commands

### Admin commands

- `/admin/serve` — serve the next queue entry
- `/admin/serve [user_id]` — serve a specific user
- `/admin/skip` — skip the next queue entry
- `/admin/skip [user_id]` — skip a specific user
- `/admin/status` — show detailed queue status
- `/admin/config max [N]` — update max queue capacity

## Python API overview

### `core.queue_manager.QueueManager`

Primary business-logic entry point.

- `join(user_id, queue_type="regular") -> dict`
- `cancel(user_id) -> dict`
- `serve_next() -> dict`
- `serve_specific(user_id) -> dict`
- `skip_next() -> dict`
- `skip_specific(user_id) -> dict`
- `get_status() -> dict`
- `get_history(user_id) -> list`
- `get_queue() -> list[QueueEntry]`
- `set_max_capacity(n) -> dict`
- `get_max_capacity() -> int`

### `core.database.DatabaseManager`

Persistence layer for queue entries, events, config, and VIP purchases.

Key helpers:

- `join_queue(...)`
- `cancel_queue(...)`
- `serve_queue(...)`
- `skip_queue(...)`
- `get_regular_queue()`
- `get_vip_queue()`
- `get_all_queue()`
- `get_user_history(user_id)`
- `add_vip_purchase(...)`
- `is_vip_purchased(user_id)`
- `get_queue_timeout_minutes()`
- `get_queue_max_capacity()`

### `services.notifier.Notifier`

Notification abstraction used by the handler and scheduler.

- `notify_user(user_id, message)`
- `notify_served(user_id, queue_number)`
- `notify_skip(user_id)`
- `notify_queue_updated(user_id, position)`
- `notify_join_success(user_id, queue_number)`

### `services.vip_service.VipService`

VIP queue operations.

- `verify_purchase(user_id)`
- `toggle_vip(enabled)`
- `get_vip_status()`
- `record_purchase(user_id, platform="line", coffee_id=None)`

### `scheduler.timeout_task`

- `check_timeouts(queue_manager, notifier)`
- `check_reminders(queue_manager, notifier)`
- `register_timeout_job(scheduler, queue_manager, notifier)`

### `scheduler.reminder_task`

- `check_reminders(queue_manager, notifier)`

## Notes

- `services.notifier.Notifier` now attempts real LINE push delivery when the LINE SDK and access token are available, and falls back to deterministic stub strings in local/test environments.
- The webhook endpoint now parses LINE events, validates signatures when a channel secret is configured, and dispatches text-message commands through `bot.handler.LineBotHandler`.
- Reminder scheduling assumes queue entries can expose `reminder_position` / `reminder_sent` attributes.
- SQLite is the default persistence backend via `queue.db`.
