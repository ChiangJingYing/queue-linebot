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

## Environment and config precedence

The app loads settings in this order:

1. built-in defaults
2. environment variables from `.env` / Docker `env_file`
3. `queue_config.yaml` overrides

That means:

- **secrets and tokens** should usually stay in `.env`
- **non-sensitive runtime options** should usually go in `queue_config.yaml`
- if a YAML section is left empty, defaults/env values are now preserved instead of being overwritten with `null`

### Put these in `.env`

Sensitive values and deploy-specific credentials belong in `.env`:

```env
LINE_CHANNEL_SECRET=xxx
LINE_CHANNEL_TOKEN=xxx
LINE_ADMIN_RICH_MENU_ID=xxx
LINE_ADMIN_RICH_MENU_PAGE2_ID=xxx
LINE_USER_RICH_MENU_ID=xxx
TELEGRAM_BOT_TOKEN=1234567890:your_bot_token
TELEGRAM_WEBHOOK_SECRET=your-telegram-webhook-secret
WEB_UI_ADMIN_TOKEN=xxx
WEB_UI_SESSION_SECRET=xxx
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/google-service-account.json
```

Optional TTS-related environment variables can also stay in `.env` when you want deploy-time control:

```env
LINE_ADMIN_IDS=YOUR_ADMIN_USER_ID[,ANOTHER_ADMIN_USER_ID]
GOOGLE_CLOUD_TTS_ENABLED=false
GOOGLE_CLOUD_TTS_LANGUAGE_CODE=cmn-TW
GOOGLE_CLOUD_TTS_VOICE_NAME=cmn-TW-Standard-A
GOOGLE_CLOUD_TTS_AUDIO_ENCODING=MP3
GOOGLE_CLOUD_TTS_SPEAKING_RATE=1.0
GOOGLE_CLOUD_TTS_PITCH=0.0
DASHBOARD_ANNOUNCEMENT_TEMPLATE=來賓 {display_name} 請準備demo
NEW_ORDER_IDLE_SECONDS=300
NEW_ORDER_ANNOUNCEMENT_TEXT=您有新訂單
# or NEW_ORDER_ANNOUNCEMENT_TEXT=/app/audio/new-order.mp3
```

`LINE_ADMIN_IDS` uses comma-separated values.

`DASHBOARD_ANNOUNCEMENT_TEMPLATE` now supports two modes:

- text template mode: `來賓 {display_name} 請準備demo`
- static audio mode: absolute or mounted `.mp3` path such as `/app/audio/called-guest.mp3`

When you provide an `.mp3` path, the called-guest dashboard announcement will reuse that file as the playback audio instead of generating TTS audio for that event.

`NEW_ORDER_ANNOUNCEMENT_TEXT` also supports two modes:

- text mode: `您有新訂單`
- static audio mode: absolute or mounted `.mp3` path such as `/app/audio/new-order.mp3`

When `NEW_ORDER_ANNOUNCEMENT_TEXT` is an `.mp3` path, the dashboard new-order announcement will reuse that file as the playback audio instead of generating TTS audio.

### Put these in `queue_config.yaml`

Use `queue_config.yaml` for non-secret app behavior, for example:

```yaml
server:
  host: 0.0.0.0
  port: 8000

queue:
  max_capacity: 50
  timeout_minutes: 30
  timeout_action: remove

vip:
  enabled: true
  coffee_price: 60
  coffee_url: https://buymeacoffee.com/yourname

registration:
  location_options:
    '1': ['1', '2', '3']
    '2': ['1', '2', '3', '4']

web_ui:
  protect_read_routes: false
  allow_query_token: false
  session_cookie_name: queue_admin_session
```

### Important YAML note

If you want to override only one nested key, keep the indentation under the parent section:

```yaml
line_bot:
  admin_ids:
    - YOUR_ADMIN_USER_ID
```

This is correct and keeps other `line_bot` values from `.env` intact.

Do **not** write it like this:

```yaml
line_bot:
admin_ids:
  - YOUR_ADMIN_USER_ID
```

That second example makes `line_bot` a null section and puts `admin_ids` at the wrong level.


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
- `LINE_ADMIN_IDS` (comma-separated if multiple admins)

### Required for Telegram bot

- `TELEGRAM_BOT_TOKEN`

### Recommended for Telegram webhook protection

- `TELEGRAM_WEBHOOK_SECRET`

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
- or `DASHBOARD_ANNOUNCEMENT_TEMPLATE=/absolute/or/mounted/path/to/custom-audio.mp3`
- `NEW_ORDER_ANNOUNCEMENT_TEXT=您有新訂單`
- or `NEW_ORDER_ANNOUNCEMENT_TEXT=/absolute/or/mounted/path/to/new-order.mp3`
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
4. either generates audio through Google Cloud TTS when enabled, or reuses a configured static `.mp3` file path for called-guest/new-order announcements,
5. exposes the audio through `/dashboard/audio/{filename}`,
6. lets the dashboard page poll and play the latest announcement after audio is enabled in the browser.

If Google Cloud credentials or SDK are missing, the queue serve flow still works and only the audio generation is skipped.

Health endpoints:

- `GET /`
- `GET /health`

## Telegram webhook setup

The app now exposes:

- `POST /api/telegram/webhook`

Expected configuration:

- `TELEGRAM_BOT_TOKEN`: the BotFather token
- `TELEGRAM_WEBHOOK_SECRET`: optional but recommended; if set, Telegram should send the same value in `X-Telegram-Bot-Api-Secret-Token`

Example webhook registration:

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://YOUR_DOMAIN/api/telegram/webhook",
    "secret_token": "YOUR_TELEGRAM_WEBHOOK_SECRET"
  }'
```

After webhook registration, users can talk to the bot directly in Telegram or add it to a group where it can receive normal text commands.

### First-time Telegram admin onboarding

1. Add your bot in Telegram.
2. Send `/register 學號 座位` to create/update your profile.
3. Ask an existing admin to grant your account admin role if not already set in the database.
4. As an admin, turn on the notifications you want:
   - `/admin/notify status`
   - `/admin/notify all on`
   - or per category, e.g. `/admin/notify join on`
5. Start operating queue commands normally from Telegram.

### Common Telegram commands

User commands:

- `/register [學號] [座位]`
- `/join`
- `/cancel`

Admin commands:

- `/admin/status`
- `/admin/stats`
- `/admin/history [ID]`
- `/admin/export`
- `/admin/clear`
- `/admin/serve`
- `/admin/serve [ID]`
- `/admin/skip`
- `/admin/vip status`
- `/admin/vip toggle on|off`
- `/admin/vip clear`


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
