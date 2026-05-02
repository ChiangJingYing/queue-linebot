# queue-linebot

一個以 Python 與 SQLite 為核心的排隊系統，支援 LINE、Telegram、Discord 三個平台的互動入口，並整合 VIP 隊列、管理員操作、Dashboard，以及完整測試。

本專案目前的重點不是只做單一平台機器人，而是讓**排隊核心邏輯共用**，再由各平台各自處理輸入解析與回應格式。

---

## 目錄

- [功能概覽](#功能概覽)
- [系統架構總覽](#系統架構總覽)
- [統一命令處理與平台差異設計](#統一命令處理與平台差異設計)
- [未來要修改功能時，應該怎麼做](#未來要修改功能時應該怎麼做)
- [環境需求](#環境需求)
- [安裝方式](#安裝方式)
- [啟動方式](#啟動方式)
- [Docker 部署](#docker-部署)
- [設定載入順序](#設定載入順序)
- [環境變數說明](#環境變數說明)
- [queue_config.yaml 設定說明](#queue_configyaml-設定說明)
- [Discord 設定](#discord-設定)
- [Telegram 設定](#telegram-設定)
- [Dashboard 與語音播報](#dashboard-與語音播報)
- [LINE Rich Menu](#line-rich-menu)
- [三平台功能對照表](#三平台功能對照表)
- [測試](#測試)
- [重要實作注意事項](#重要實作注意事項)

---

## 功能概覽

### 一般使用者功能

- 註冊學號與座位
- 加入一般隊列
- 取消排隊
- 查看目前排隊狀態
- 查看個人排隊歷史
- 顯示常用功能選單

### VIP 相關功能

- VIP 隊列支援
- VIP 購買／驗證資料紀錄
- 管理員查看 VIP 狀態
- 清空 VIP 隊列

### 管理員功能

- 叫號
- 跳過指定使用者
- 手動提醒
- 切換排隊開關
- 匯出資料預覽
- 查看統計資訊
- 查看完整歷史
- 推播設定

### Web / Dashboard 功能

- Dashboard 狀態頁
- Dashboard 設定頁
- 圖片配置與座位版面儲存
- 語音播報下一位與新訂單提示
- Web UI token / session 驗證

### 平台支援

- Telegram webhook
- Discord interactions
- LINE Messaging API 指令與 quick reply 流程

---

## 系統架構總覽

專案大致可分成幾層：

### 1. 核心資料與排隊邏輯

- `core/database.py`
- `core/queue_manager.py`
- `core/models.py`
- `core/validators.py`
- `core/time_utils.py`

這一層負責：
- 資料持久化
- 排隊順位
- 設定狀態
- 基本驗證
- 時間格式處理

這層應盡量**不依賴任何特定聊天平台**。

### 2. 共用業務流程層

- `services/user_flow.py`
- `services/register_flow.py`
- `services/register_service.py`
- `services/cancel_flow.py`
- `services/serve_flow.py`
- `services/admin_flow.py`
- `services/vip_service.py`
- `services/pending_state_store.py`

這一層負責：
- 一般使用者共用流程
- 註冊多步驟流程
- 取消／二次確認流程
- 叫號流程
- 管理員共用流程
- VIP 業務邏輯

這層應盡量回傳**平台無關的 outcome / state / message**，避免直接綁死 Telegram 或 Discord 的 payload 格式。

### 3. 平台輸入／輸出轉接層

#### Telegram
- `services/telegram_commands.py`

#### Discord
- `services/discord_commands.py`
- `services/interaction_presenters.py`

#### Webhook / HTTP 入口
- `main.py`

這一層負責：
- 將平台收到的事件轉成內部命令
- 呼叫共用 flow
- 再把結果轉回平台需要的回應格式

---

## 統一命令處理與平台差異設計

這部分是最近重構的核心，後續維護務必遵守。

### 設計目標

同一個功能，例如：
- `/join`
- `/cancel`
- `/status`
- `/history`
- `/help`
- `/register`

應優先讓**業務邏輯共用**，不要在 Telegram、Discord 各寫一套。

換句話說：

- **命令意圖要共用**
- **平台輸入格式可以不同**
- **平台輸出格式也可以不同**

---

### 目前的分工方式

#### 1. 平台把輸入正規化成統一命令或動作

例如：

##### Telegram
在 `services/telegram_commands.py`：
- 使用者輸入文字 `/join`
- 或按下按鈕 `設定資料`
- 或 inline callback
- 最後都會被轉成內部一致的 command / action

##### Discord
在 `main.py`：
- `_extract_discord_input(payload)` 會把 Discord interaction 轉成統一輸入
- slash command `type == 2`
- button `type == 3`
- modal submit `type == 5`
- 最後轉成例如：
  - `/menu`
  - `/join`
  - `register:start`
  - `register:submit:B12345678`
  - `register:group:A`
  - `register:item:1`

這一步的重點是：

> **平台原生 payload 很亂，但進入 service 前要盡量整理成簡單、可測試、可共享的內部文字／動作。**

---

#### 2. 共用 flow 處理業務邏輯

例如：

- `services/user_flow.py`
  - `join_user()`
  - `cancel_user()`
  - `get_user_status()`
  - `build_history_message()`
  - `build_help_message()`

- `services/register_flow.py`
  - `begin_register_location_flow()`
  - `advance_register_flow()`

這些函式不應直接知道：
- Discord button 長怎樣
- Telegram reply markup 長怎樣
- LINE Rich Menu 長怎樣

它們只應處理：
- 是否需要註冊
- 狀態是否成功
- 下一步有哪些選項
- 要顯示什麼訊息

---

#### 3. 平台層負責把共用結果包成各平台回應

##### Telegram
在 `services/telegram_commands.py`：
- 回 `reply_markup`
- 決定是 reply keyboard 還是 inline keyboard

##### Discord
在 `services/discord_commands.py` + `services/interaction_presenters.py`：
- 回 `components`
- 決定是 button、modal、ephemeral response
- 處理 Discord 規格限制

例如最近修掉的就是 Discord 特有問題：
- button `style` 必須是數字，不可用字串
- 每列 button 最多 5 顆

這些就屬於**平台差異層**，不應污染共用 flow。

---

## 未來要修改功能時，應該怎麼做

這一節很重要。之後若要改功能，建議依照下面順序進行。

### 原則一：先判斷這是「共用邏輯」還是「平台差異」

先問自己：

#### 如果你要改的是這些，通常應改共用 flow
- 排隊成功／失敗條件
- 註冊必填規則
- 歷史訊息內容
- help 指令顯示內容
- 取消排隊邏輯
- VIP／一般隊列規則
- 管理員操作規則

通常應優先看：
- `services/user_flow.py`
- `services/register_flow.py`
- `services/register_service.py`
- `services/cancel_flow.py`
- `services/admin_flow.py`
- `services/serve_flow.py`
- `services/vip_service.py`

#### 如果你要改的是這些，通常應改平台差異層
- Telegram 按鈕長相
- Discord slash command / modal / button payload
- Discord component 限制
- Telegram callback_data / keyboard 結構
- 哪個平台要用文字輸入、哪個平台要用 modal

通常應優先看：
- `services/telegram_commands.py`
- `services/discord_commands.py`
- `services/interaction_presenters.py`
- `main.py`
- `scripts/register_discord_commands.py`

---

### 原則二：先補測試，再改實作

這個專案目前已經有相當完整的 pytest 覆蓋，未來修改請延續這個習慣。

建議流程：

1. 先找到最貼近的測試檔
2. 先新增 regression test
3. 確認測試紅燈
4. 再改實作
5. 跑相關測試群

---

### 原則三：優先改共用 flow，不要複製邏輯到各平台

#### 好的做法
- `join_user()` 改一次
- Telegram / Discord 都吃到同一套規則

#### 不好的做法
- 在 `telegram_commands.py` 寫一套 join 判斷
- 在 `discord_commands.py` 再寫另一套 join 判斷

這會讓平台間行為慢慢漂移，最後很難維護。

---

### 原則四：平台 payload 的限制一定要測

最近已經踩到的 Discord 規格坑：

- button `style` 必須是 int
- 每個 action row 最多 5 顆 button

所以之後只要改到 Discord response 結構，請至少檢查：

- `type`
- `custom_id`
- `style`
- `components` 巢狀結構
- 每列按鈕數量
- modal text input 格式

對應測試檔通常是：
- `tests/test_interaction_presenters.py`
- `tests/test_discord_commands.py`
- `tests/test_main_and_config.py`

---

### 原則五：新增指令時的建議流程

假設未來要新增一個 `/foo` 功能，建議順序如下：

#### 情境 A：Telegram 與 Discord 都要支援

1. 先在共用 flow 加入業務邏輯
2. 在 `telegram_commands.py` 加入命令路由
3. 在 `discord_commands.py` 加入命令路由
4. 若 Discord 需要 slash command，更新 `scripts/register_discord_commands.py`
5. 若需要平台按鈕／UI，更新 presenter
6. 補：
   - flow 測試
   - Telegram 測試
   - Discord 測試
   - parity 測試

#### 情境 B：只有某平台需要特有互動

例如 Discord modal、Telegram inline keyboard。

則做法應是：
- 互動表現留在平台層
- 但最終業務處理仍盡量導回共用 flow

例如：
- Discord 用 modal 收學號
- 收到後轉成 `register:submit:<學號>`
- 再交給既有 register flow

這樣 UI 可以不同，但邏輯仍一致。

---

### 原則六：不要把「平台上的 convenience」誤做成核心規則

例如：
- Discord slash command 是否顯示 option
- Telegram 是否提供快捷按鈕
- 某平台是否用 modal

這些通常只是互動介面差異，不是業務規則本身。

例如這次 `/join`：
- backend 保留對 Discord `data.options` 的兼容
- 但 slash command UI 不一定要暴露 option

這就是很典型的：
- **相容性是平台層需求**
- **是否顯示給使用者是 UI 層需求**
- **join 的商業邏輯仍應留在共用 flow**

---

## 環境需求

- Python 3.11+
- pip
- SQLite
- 若使用 Docker：Docker / Docker Compose

---

## 安裝方式

```bash
git clone <your-repo-url>
cd queue-linebot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

若使用 `uv`，則依 `pyproject.toml` / `uv.lock` 安裝。

---

## 啟動方式

### 直接執行

```bash
python main.py
```

### 使用 uvicorn

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Docker 部署

本專案目前 Docker 相關檔案：

- `Dockerfile`
- `docker-compose.yml`

目前 `docker-compose.yml` 重點：

- service name: `queue-linebot`
- container name: `queue-linebot`
- `restart: unless-stopped`
- `TZ=Asia/Taipei`
- `env_file: .env`
- 對外 port：`8000:8000`

掛載內容包含：
- `./queue.db:/app/queue.db`
- `./config/queue_config.yaml:/app/config/queue_config.yaml`
- `./logs:/app/logs`
- `./rich_menus:/app/rich_menus`
- `./dashboard_layout:/app/dashboard_layout`

### 建置與啟動

```bash
docker compose up -d --build
```

### 查看日誌

```bash
docker compose logs -f queue-linebot
```

如果改到 Discord / Telegram webhook 流程，建議一定要搭配 log 一起看。

---

## 設定載入順序

系統設定載入順序如下：

1. 內建預設值
2. `.env` / Docker `env_file`
3. `config/queue_config.yaml`

也就是說：

- **敏感資訊、token、金鑰**：放 `.env`
- **非敏感的功能設定**：放 `config/queue_config.yaml`

---

## 環境變數說明

建議放在 `.env`：

```env
LINE_CHANNEL_SECRET=xxx
LINE_CHANNEL_TOKEN=xxx
LINE_ADMIN_RICH_MENU_ID=xxx
LINE_ADMIN_RICH_MENU_PAGE2_ID=xxx
LINE_USER_RICH_MENU_ID=xxx

TELEGRAM_BOT_TOKEN=1234567890:your_bot_token
TELEGRAM_WEBHOOK_SECRET=your-telegram-webhook-secret

DISCORD_BOT_TOKEN=your-discord-bot-token
DISCORD_APPLICATION_ID=your-discord-application-id
DISCORD_PUBLIC_KEY=your-discord-public-key

WEB_UI_ADMIN_TOKEN=xxx
WEB_UI_SESSION_SECRET=xxx

GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/google-service-account.json
```

也可參考：
- `config/.env.example`
- `.env.example`

### 其他可放在 `.env` 的選項

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
# 或 NEW_ORDER_ANNOUNCEMENT_TEXT=/app/audio/new-order.mp3
```

---

## queue_config.yaml 設定說明

建議將非敏感設定放在：
- `config/queue_config.yaml`

例如：

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

### YAML 注意事項

若只想覆蓋某個巢狀欄位，縮排一定要正確，例如：

```yaml
line_bot:
  admin_ids:
    - YOUR_ADMIN_USER_ID
```

不要寫成：

```yaml
line_bot:
admin_ids:
  - YOUR_ADMIN_USER_ID
```

否則會把 section 結構弄壞。

---

## Discord 設定

### Webhook / Interactions 入口

Discord interaction endpoint：

- `POST /api/discord/interactions`

在 `main.py` 中，這個入口會先做：

- `discord_command_service is None` 檢查
- `DISCORD_PUBLIC_KEY` 檢查
- `x-signature-ed25519` / `x-signature-timestamp` 驗證
- JSON parse
- interaction type 分流

### Discord 目前的互動流程

- slash commands 為主要入口
- `/register` 會開 modal 輸入學號
- modal submit 後，使用 button 繼續多步驟選排／選座位
- slash command、button、modal submit 最終都會轉成統一內部 input

### 註冊 Discord slash commands

設定好以下環境變數後：

- `DISCORD_APPLICATION_ID`
- `DISCORD_BOT_TOKEN`

執行：

```bash
python scripts/register_discord_commands.py
```

目前會註冊以下 DM 用指令：

- `/menu`
- `/register`
- `/join`
- `/cancel`
- `/status`
- `/history`
- `/help`

### Discord 回應格式的重要限制

這些是目前已知、而且踩過坑的地方：

- button `style` 必須是數字，不可用字串
- 每個 action row 最多 5 顆 button
- modal text input 要符合 Discord 結構

對應封裝位置：
- `services/interaction_presenters.py`

若未來要改 Discord buttons / modal，**請優先改這裡，不要四散在各 service 自己手刻 payload**。

---

## Telegram 設定

Telegram webhook endpoint：

- `POST /api/telegram/webhook`

### 需要的設定

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_WEBHOOK_SECRET`（建議設定）

如果設定了 `TELEGRAM_WEBHOOK_SECRET`，Telegram 應以：
- `X-Telegram-Bot-Api-Secret-Token`

送出相同值。

### 註冊 webhook 範例

```bash
curl -X POST "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-domain.example/api/telegram/webhook",
    "secret_token": "your-telegram-webhook-secret"
  }'
```

---

## Dashboard 與語音播報

當管理員執行：

- `/admin/serve`
- `/admin/serve [user_id]`

系統會：

1. 正常叫號
2. 組出播報文字
3. 儲存最新 Dashboard announcement payload
4. 若啟用 Google Cloud TTS，則產生音訊；否則可重用靜態 `.mp3`
5. 透過 `/dashboard/audio/{filename}` 提供音檔
6. 由 Dashboard 輪詢並播放

### TTS 推薦中文語音預設

- language code: `cmn-TW`
- voice name: `cmn-TW-Standard-A`
- audio encoding: `MP3`
- speaking rate: `1.0`
- pitch: `0.0`

---

## LINE Rich Menu

目前提供：

- `rich_menus/user_rich_menu.json`
- `rich_menus/admin_rich_menu.json`
- `rich_menus/admin_page2_rich_menu.json`

可使用腳本上傳：

```bash
python scripts/upload_rich_menus.py \
  --admin-image assets/admin-rich-menu.png \
  --user-image assets/user-rich-menu.png \
  --write-config
```

若加上 `--write-config`，會回寫 `config/queue_config.yaml` 中的 rich menu id。

---

## 三平台功能對照表

以下對照表以目前程式碼與測試中已確認的功能為準，目的是讓後續維護時，可以快速看出哪些功能是三平台共用、哪些仍是平台特有。

### 一般使用者功能對照

| 功能 | LINE | Telegram | Discord |
| --- | --- | --- | --- |
| `/register` 註冊學號與座位 | ✅ | ✅ | ✅ |
| `/join` 加入一般隊列 | ✅ | ✅ | ✅ |
| `/join vip` 加入 VIP 隊列 | ✅ | ✅ | ❌ |
| `/cancel` 取消排隊 | ✅ | ✅ | ✅ |
| `/status` 查看目前狀態 | ✅ | ✅ | ✅ |
| `/history` 查看個人排隊歷史 | ✅ | ✅ | ✅ |
| `/help` 查看說明 | ✅ | ✅ | ✅ |
| `/menu` 顯示常用功能選單 | ❌ | ✅ | ✅ |
| 可收到「輪到你了」叫號推播 | ✅ | ✅ | ✅ |
| 註冊流程互動方式 | 文字輸入 + quick reply | 文字輸入 + inline keyboard / reply keyboard | modal + buttons |
| 取消排隊二次確認 | quick reply | inline keyboard | buttons |

### 管理員功能對照

| 功能 | LINE | Telegram | Discord |
| --- | --- | --- | --- |
| `/admin/serve` 叫下一位 | ✅ | ✅ | ❌ |
| `/admin/serve [id]` 叫指定使用者 | ✅ | ✅ | ❌ |
| `/admin/ping` 手動提醒下一位 | ✅ | ✅ | ❌ |
| `/admin/ping [id]` 手動提醒指定使用者 | ✅ | ✅ | ❌ |
| `/admin/status` 完整狀態 | ✅ | ✅ | ❌ |
| `/admin/stats` 統計面板 | ✅ | ✅ | ❌ |
| `/admin/history [id]` 查詢使用者歷史 | ✅ | ✅ | ❌ |
| `/admin/export` 匯出 CSV 預覽 | ✅ | ✅ | ❌ |
| `/admin/clear` 清空全部隊列 | ✅ | ✅ | ❌ |
| `/admin/skip` 跳過指定使用者 | ❌ | ✅ | ❌ |
| `/admin/vip status` 查看 VIP 隊列狀態 | ✅ | ✅ | ❌ |
| `/admin/vip toggle [on/off]` 開關 VIP 隊列 | ✅ | ✅ | ❌ |
| `/admin/vip clear` 清空 VIP 隊列 | ✅ | ✅ | ❌ |
| `/admin/join [on/off]` 切換總隊列狀態 | ✅ | ✅ | ❌ |
| `/admin/join status` 查看總隊列狀態 | ✅ | ✅ | ❌ |
| `/admin/notify ...` 推播設定 | ❌ | ✅ | ❌ |
| `/admin/apply` 申請 / 審核 admin 權限 | ✅ | ✅ | ❌ |
| 可收到其他 admin 的操作通知 | ❌ | ✅ | ❌ |
| 管理員快捷選單 | quick reply / rich menu | reply keyboard | ❌ |

### 對照表補充說明

- Discord 目前只實作一般使用者 DM 流程，入口集中在 `POST /api/discord/interactions` 與 `services/discord_commands.py`。
- Telegram 目前同時支援一般使用者與管理員自助操作，命令與互動集中在 `services/telegram_commands.py`。
- LINE 目前仍保有最完整的管理員命令覆蓋，主要分布在 `bot/handler_commands.py`、`bot/handler_registration.py`、`bot/handler_admin.py`。
- `/join vip` 目前在 LINE 與 Telegram 可用；Discord 目前 README 應視為未支援，而不是推定未來一定會支援。
- `/admin/skip` 目前只在 TelegramCommandService 中有實作與測試，LINE 與 Discord 不應在 README 誤寫成已支援。
- 「可收到『輪到你了』叫號推播」指的是該平台身分的使用者在被叫號時，系統目前有實作通知出口。LINE 走 `services/notifier.py` 的 LINE push，Discord 使用者會透過 `discord_sender` 收到 DM，Telegram 使用者也可透過 Telegram sender 收到通知。
- 「可收到其他 admin 的操作通知」指的是管理員自己所在的平台帳號，是否能收到其他管理員操作所觸發的通知；這不是跨平台廣播。以目前實作來說，Telegram admin 可透過 `/admin/notify ...` 收到 Telegram 管理通知；LINE admin 與 Discord admin 目前沒有對應的管理通知機制。
- 也就是說，像 LINE 的 admin 動作不會自動讓 Telegram 的一般使用者收到管理通知；通知是否送出、送到誰，仍以各平台現有 sender 與通知偏好設定為準。

---

## 測試

專案目前有相當完整的 pytest 測試。

### 建議常用測試群

#### Discord 相關

```bash
pytest -q --no-cov \
  tests/test_discord_setup.py \
  tests/test_discord_commands.py \
  tests/test_interaction_presenters.py \
  tests/test_main_and_config.py
```

#### 共用流程與跨平台一致性

```bash
pytest -q --no-cov \
  tests/test_user_flow.py \
  tests/test_register_flow.py \
  tests/test_cancel_flow.py \
  tests/test_cross_platform_parity.py
```

#### 全面測試

```bash
pytest
```

### 測試檔分工建議

- `tests/test_user_flow.py`
  - 共用使用者邏輯
- `tests/test_register_flow.py`
  - 註冊流程狀態機
- `tests/test_cancel_flow.py`
  - 取消流程
- `tests/test_telegram_commands.py`
  - Telegram 平台層
- `tests/test_discord_commands.py`
  - Discord 平台層
- `tests/test_interaction_presenters.py`
  - Discord / Telegram UI payload builder
- `tests/test_main_and_config.py`
  - webhook / interaction endpoint / config integration
- `tests/test_cross_platform_parity.py`
  - 平台間行為一致性

---

## 重要實作注意事項

### 1. Discord 的平台限制要特別小心

近期已確認的真實問題：

- button `style` 若用字串，Discord 前端會視為 invalid
- 一列超過 5 顆按鈕，Discord 前端會視為 invalid

這類錯誤有時候後端 log 看起來仍是 `200 OK`，但 Discord 前端仍會顯示失敗。

所以只看後端 HTTP status 不夠，還要看 response payload 是否真的符合 Discord 規格。

### 2. `main.py` 的 `_extract_discord_input()` 很關鍵

這裡負責把：
- slash command
- component button
- modal submit

轉成內部統一輸入。

若 Discord 某類互動失效，這裡通常是第一個要檢查的地方。

### 3. `services/interaction_presenters.py` 是 Discord / Telegram UI 封裝出口

若要改：
- Discord buttons
- Telegram inline keyboard
- Telegram reply keyboard

請優先改這裡，不要分散在不同 service 內各自手刻。

### 4. `tests/test_cross_platform_parity.py` 很重要

如果你改的是共用流程，請確認 Telegram / Discord 的使用者體驗是否仍一致。

### 5. 若是 Docker 部署，改完一定要重建

```bash
docker compose up -d --build
```

並觀察：

```bash
docker compose logs -f queue-linebot
```

---

如果後續再做更大規模重構，建議持續維持下面這條原則：

> **共用邏輯集中在 flow / service，平台差異集中在 command adapter 與 presenter。**

這樣功能才不會越改越散，平台之間也比較不容易出現行為漂移。