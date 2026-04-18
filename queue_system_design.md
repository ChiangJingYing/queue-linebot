# 📋 Queue System — 多人排隊系統設計文件

> **平台：** Windows 桌面端
> **日期：** 2026-04-18
> **版本：** v2.0 (LINE Bot 統一期)

---

## 1. 系統概覽

這是一個**純 LINE Bot 介面**的排隊系統。所有使用者互動（加入隊列、查看狀態、取消排隊、被叫號通知）都透過 LINE Bot 完成，**不需要任何獨立的前端網頁或 WebSocket 連線**。管理員（Server）同樣透過 LINE Bot 的專用指令來叫號、跳過、管理隊列。

> **核心變化（v2.0 vs v1.0）：**
> - 移除了 WebSocket、Streamlit/Vue.js Web UI、REST API 前端
> - 所有操作都透過 LINE Bot 指令完成
> - 通知機制改為 LINE Push API / Reply API
> - 依賴套件更簡化，專注於 `line-bot-sdk-python`

---

## 2. 技術棧評估

| 元件 | 選擇 | 理由 |
|------|------|------|
| **語言** | Python 3.12+ | 跨平台、協程支援好、生態豐富 |
| **Framework** | **FastAPI + uvicorn** (async) | 提供 Webhook 端點、非同步原生 |
| **LINE Bot** | `line-bot-sdk-python` | LINE 官方 SDK，接收 Webhook + 發送推播 |
| **資料庫** | **SQLite** (內建) | Windows 無需額外安裝，小規模够用 |
| **排程** | **APScheduler** (內嵌) | 用於告警、複盤、VIP 時效管理等 |

> **推薦方案：** FastAPI + SQLite + LINE Bot SDK
> 全部用 Python，維護成本低，Windows 上跑得很好。

---

## 3. 系統架構

```
┌───────────────────────────────────────────┐
│              Queue Server                 │
│  ┌───────────────────┐  ┌─────────────┐ │
│  │ LINE Bot Webhook  │  │ Admin Bot   │ │
│  │ Handler           │  │ Handler     │ │
│  │ (一般使用者)       │  │ (管理員)     │ │
│  └────────┬──────────┘  └──────┬──────┘ │
│           │                     │         │
│  ┌────────┴─────────────────────┴───────┐ │
│  │           Queue Manager Core         │ │
│  │  - Regular Queue (標準隊列)         │ │
│  │  - VIP Queue (購買 coffee 排隊)     │ │
│  │  - 排隊檢查 / 加入 / 移除 / 查看    │ │
│  └─────────────────┬───────────────────┘ │
│                    │                       │
│  ┌───────────────┬─┴───────────────────┐ │
│  │   SQLite DB   │ │   LINE Push API   │ │
│  └───────────────┘ └───────────────────┘ │
└───────────────────────────────────────────┘
         ▲                    ▲
         │                    │
   ┌─────┴─────┐     ┌──────┴──────┐
   │ 一般使用者 │     │  管理員      │
   │ (LINE Bot) │     │ (LINE Bot)  │
   └───────────┘     └─────────────┘
```

---

## 4. 詳細功能規格

### 4.1 使用者功能（LINE Bot）

#### 4.1.1 加入排隊 (`/join`)
- 使用者在 LINE 聊天中輸入 `/join [ID]`
- LINE Bot 檢查：
  - ID 是否有效（不為空、格式正確）
  - ID 是否**已在隊列中**（重複檢查）
  - 隊列是否**已满**（可設定最大人數）
- 加入成功後，Bot 回覆訊息告知排隊號碼與大概等待時間

**LINE Bot 使用者輸入：**
```
/join user_12345
```

**Bot 回覆：**
```
✅ 已加入隊列！
   排隊號碼：#5
   前方還有 4 人
   預計等待：約 10 分鐘
   總人數：8
```

#### 4.1.2 查看隊列狀態 (`/status`)
- 使用者在 LINE 聊天中輸入 `/status`
- Bot 查詢 SQLite 資料庫並回傳目前隊列狀態

**Bot 回覆範例：**
```
📊 隊列狀態

標準隊列：
   總人數：8 人
   下一位：user_***

VIP 隊列：
   總人數：2 人
   狀態：已開啟

💡 輸入 /help 查看更多指令
```

#### 4.1.3 取消排隊 (`/cancel`)
- 使用者在 LINE 聊天中輸入 `/cancel`
- Bot 從隊列中移除該使用者
- Bot 回覆確認訊息

**Bot 回覆：**
```
✅ 已取消排隊。
   原本位置：#5
   當前總人數：7
```

#### 4.1.4 LINE Bot 其他功能

| 功能 | LINE Bot 指令 |
|------|------|
| **排隊提醒設定** | `/remind N` — 前方剩 N 人時推播通知 |
| **排隊歷史** | `/history` — 查看自己過去的排隊紀錄 |
| **VIP 購買** | `/coffee` — 引導至 Buy a Coffee 頁面 |
| **說明頁** | `/help` — 顯示所有可用指令 |
| **叫號確認** | 被叫號後回覆 "done" 標記完成 |

---

### 4.2 管理端功能（LINE Bot 指令）

> **權限機制：** 管理員透過 LINE 帳號 ID 驗證，只有白名單內的 ID 可使用 `/admin/` 指令。

#### 4.2.1 查看所有隊列 (`/admin/status`)
- 管理員在 LINE Bot 輸入此指令
- 回傳完整隊列狀態（**完整 ID**，不分頁）

**Bot 回覆範例：**
```
📋 完整隊列狀態

標準隊列 (8人):
   #1 alice   — 10:00
   #2 bob     — 10:05
   #3 charlie — 10:10
   ...

VIP 隊列 (2人):
   #1 vip_dave   — 10:02 (已購買)
   #2 vip_eve    — 10:15 (已購買)

資訊:
   伺服器運行：2h 30m
   今日總排隊：42 人次
```

#### 4.2.2 叫號 / 接受下一位 (`/admin/serve`)
- 管理員輸入 `/admin/serve` → 叫號隊列頭的一位
- 或 `/admin/serve <ID>` → 指定叫號
- Bot 通知被叫號者（LINE push notification）

**Bot 回覆：**
```
✅ 已叫號 #1 alice
   alice 將收到通知訊息
   更新後隊列：#1 bob
```

#### 4.2.3 跳過下一位 (`/admin/skip`)
- 管理員輸入 `/admin/skip` → 跳過隊列頭的一位

**Bot 回覆：**
```
⏭ 已跳過 #1 alice
   alice 將被通知跳號
   更新後隊列：#1 bob
```

#### 4.2.4 VIP 隊列管理 (`/admin/vip/*`)

| 指令 | 說明 |
|------|------|
| `/admin/vip/status` | 查看 VIP 隊列狀態 |
| `/admin/vip/toggle [on/off]` | 開/關 VIP 隊列 |
| `/admin/vip/clear` | 清空 VIP 隊列 |

#### 4.2.5 其他管理功能

| 功能 | LINE Bot 指令 |
|------|------|
| **人數上限** | `/admin/config max 100` — 設定最大人數 |
| **統計面板** | `/admin/stats` — 今日/本月排隊統計 |
| **排出報表** | `/admin/export` — 匯出 CSV/Excel |
| **排隊歷史** | `/admin/history <ID>` — 查詢指定使用者歷史 |

---

## 5. LINE Bot 核心架構

> **全新架構：LINE Bot 是唯一的互動介面，不再有 Web UI、WebSocket 或獨立的客端程式。**

### 5.1 雙 Bot 模式

系統採用 **兩個 LINE Bot** 運行：

| Bot 類型 | 用途 | 權限 |
|----------|------|------|
| **一般 Bot** | 使用者排隊、查詢、取消 | 無管理權限 |
| **管理 Bot** | 叫號、跳過、統計、設定 | 管理員權限 |

> *兩個 Bot 可以共用同一個 Channel Access Token，透過指令前綴 `/admin/` 區分權限。

### 5.2 LINE Bot 指令總覽

#### 使用者指令

| 指令 | 說明 |
|------|------|
| `/join [ID]` | 加入標準隊列 |
| `/join vip [ID]` | 加入 VIP 隊列（需先購買咖啡） |
| `/status` | 查看隊列狀態 |
| `/cancel` | 取消排隊 |
| `/remind N` | 前方剩 N 人時推播通知 |
| `/history` | 查看排隊歷史 |
| `/coffee` | 前往 Buy a Coffee 頁面 |
| `/help` | 顯示說明 |

#### 管理員指令

| 指令 | 說明 |
|------|------|
| `/admin/serve` | 叫號下一位 |
| `/admin/serve [ID]` | 指定叫號 |
| `/admin/skip` | 跳過下一位 |
| `/admin/skip [ID]` | 跳過指定者 |
| `/admin/status` | 查看完整隊列 |
| `/admin/stats` | 查看統計資料 |
| `/admin/config max [N]` | 設定最大人數 |
| `/admin/vip toggle [on/off]` | 開/關 VIP |
| `/admin/vip clear` | 清空 VIP |
| `/admin/history [ID]` | 查詢使用者歷史 |
| `/admin/export` | 匯出報表 |

### 5.3 被叫號通知

- 當管理員叫號時，Bot **主動推播 LINE 訊息**通知被叫號者
- 訊息內容：
```
🎉 嘿！輪到你了！
   排隊號碼：#3
   請前往服務區
   超過 5 分鐘未回應將視為跳號
```
- **5 分鐘逾時**未回應 → 自動跳號並通知

### 5.4 VIP 隊列與 Buy a Coffee

- 使用者輸入 `/coffee` 或 `/vip`
- Bot 回覆：
```
☕ 請購買一杯咖啡獲得 VIP 排隊權

[Buy a Coffee 連結](https://buycoffee.example.com/yourname)

購買完成後輸入 `/join vip` 加入 VIP 隊列
```
- 購買驗證透過 **Buy a Coffee Webhook** 完成
- 設有設定旗標：**是否開啟 VIP 隊列**

**Buy a Coffee 設定：**
```json
{
  "buy_coffee": {
    "enabled": true,
    "price": 60,
    "currency": "TWD",
    "purchase_url": "https://buycoffee.example.com/yourname",
    "verifier": "api_user_id"
  }
}
```

---

## 6. 資料庫設計 (SQLite)

### 6.1 表格

#### `queues` — 排隊紀錄
```sql
CREATE TABLE queues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT UNIQUE NOT NULL,          -- 使用者 ID
    queue_type TEXT NOT NULL DEFAULT 'regular', -- regular / vip
    queue_number INTEGER NOT NULL,          -- 排隊號碼
    join_time TEXT NOT NULL,               -- 加入時間
    cancel_time TEXT,                      -- 取消時間 (NULL = 仍在排隊)
    served_time TEXT,                      -- 被叫號時間 (NULL = 尚未叫號)
    served BOOLEAN NOT NULL DEFAULT 0,     -- 是否已被叫號
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### `vip_purchases` — VIP 購買記錄
```sql
CREATE TABLE vip_purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT UNIQUE NOT NULL,
    platform TEXT NOT NULL,              -- line / web / app
    coffee_id TEXT,                      -- Buy a Coffee 訂單 ID
    purchased_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    verified BOOLEAN DEFAULT 0
);
```

#### `queue_events` — 事件日誌
```sql
CREATE TABLE queue_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,           -- join / cancel / served / skip
    user_id TEXT,
    queue_type TEXT,
    details TEXT,                       -- 附加資訊 (JSON)
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

#### `server_config` — 伺服器設定
```sql
CREATE TABLE server_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

**初始化設定範例：**
```sql
INSERT INTO server_config (key, value) VALUES
    ('queue_max_capacity', '50'),
    ('queue_timeout_minutes', '30'),
    ('vip_enabled', 'true'),
    ('coffee_price', '60');
```

---

## 7. LINE Bot Webhook 規格

> **因為整個系統只透過 LINE Bot 互動，不再需要獨立的 REST API。所有操作都透過 LINE 訊息觸發。**

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/line/webhook` | LINE 事件的 webhook 端點 |

### 7.1 Webhook 事件結構

**一般使用者訊息範例：**
```json
{
  "type": "message",
  "replyToken": "xxxxxx",
  "source": {
    "userId": "U1234567890abcdef"
  },
  "message": {
    "type": "text",
    "text": "/join user_12345"
  }
}
```

**管理員指令範例：**
```json
{
  "type": "message",
  "replyToken": "xxxxxx",
  "source": {
    "userId": "Uadmin_xxxxx"
  },
  "message": {
    "type": "text",
    "text": "/admin/serve"
  }
}
```

**Buy a Coffee Webhook 範例：**
```json
{
  "coffeeId": "order_xxxxx",
  "userId": "user_12345",
  "amount": 60,
  "timestamp": 1713400000
}
```

### 7.2 推播通知 (Push API)

當需要主動通知使用者時（被叫號、跳號、提醒等）：

**推播訊息結構：**
```json
{
  "to": ["U1234567890abcdef"],
  "messages": [
    {
      "type": "text",
      "text": "🎉 嘿！輪到你了！排隊號碼 #3\n請前往服務區\n超過 5 分鐘未回應將視為跳號"
    }
  ]
}
```

---

## 8. 隊列事件通知機制

> **取代 WebSocket：所有通知透過 LINE Push API 或 reply API 完成。**

### 8.1 主動通知事件

| 事件 | 觸發條件 | 通知方式 |
|------|----------|----------|
| **被叫號** | 管理員叫號 | LINE Push API |
| **跳號** | 管理員跳過 / 逾時未回應 | LINE Push API |
| **排隊提醒** | 使用者設定的前方剩 N 人 | LINE Push API |
| **前面有人取消** | 前方隊員取消排隊 | LINE Reply Message |
| **VIP 狀態變更** | 管理員開/關 VIP 隊列 | LINE Push API |

### 8.2 隊列狀態查詢

- 使用者主動輸入 `/status` 查詢時，Bot 透過 **Reply Message** 即時回傳
- 資料直接從 SQLite 讀取，無需即時推送（輕量查詢）

### 8.3 前端互動流程

```
使用者 ──(LINE 訊息)──→ Queue Server ──(LINE Reply)──→ 使用者
管理者 ──(LINE 訊息)──→ Queue Server ──(LINE Reply)──→ 管理者
Queue Server ──(LINE Push)──→ 被叫號使用者 (主動通知)
```

### 8.4 被叫號狀態追蹤

```
管理員叫號 #1 alice
    │
    ▼
Bot 推送通知給 alice
    │
    ├── alice 回覆 "done" → 標記已服務
    ├── alice 逾時 5 分鐘 → 自動跳號並通知
    └── alice 主動取消 → 標記取消
```

---

## 9. 專案結構

```
queue_system/
├── main.py                  # FastAPI 入口 + APScheduler 註冊
├── config.py                # 設定檔 (YAML / JSON)
├── database.py              # SQLite 連線管理
├── models.py                # 資料模型 (Pydantic)
├── bot/
│   ├── handler.py           # LINE Bot Webhook 處理
│   ├── commands.py          # 指令路由 (一般/管理員)
│   ├── pusher.py            # LINE Push API 通知
│   └── admin_auth.py        # 管理員權限驗證
├── services/
│   ├── queue_manager.py     # 隊列核心邏輯
│   ├── vip_service.py       # VIP / Buy a Coffee
│   └── notifier.py          # 通知服務 (LINE Push/Reply)
├── scheduler/
│   ├── timeout_task.py      # 逾時自動移除
│   └── reminder_task.py     # 排隊提醒
├── utils/
│   ├── validators.py        # ID 驗證
│   └── helpers.py           # 工具函式
├── tests/
│   ├── test_queue_core.py
│   ├── test_vip_service.py
│   ├── test_bot_commands.py
│   └── test_e2e.py
├── logs/
│   └── queue_events.log
├── queue.db                  # SQLite 資料庫 (自動建立)
├── queue_config.yaml        # 設定檔
└── requirements.txt
```

---

## 10. 核心流程圖

### 10.1 加入隊列

```
使用者 LINE 輸入 /join user_12345
    │
    ▼
Bot 驗證 ID (不為空、格式正確)
    │
    ▼
Bot 檢查是否已在隊列中
    │
    ├── 已在 → 回覆錯誤 "已在排隊中"
    │
    └── 不在 → 檢查隊列容量
         │
         ├── 已滿 → 回覆錯誤 "隊列已滿"
         │
         └── 可加入 → 插入隊列 → 回覆排隊號碼
```

### 10.2 管理員叫號

```
管理員 LINE 輸入 /admin/serve
    │
    ▼
Bot 叫號隊列頭 (head)
    │
    ├── 叫號 → 標記為 served → 從隊列移除
    │          → LINE Push 通知被叫者
    │
    └── 跳過 → 標記 skip → LINE Push 通知
```

---

## 11. VIP / Buy a Coffee 流程

```
使用者 LINE 輸入 "/coffee"
    │
    ▼
Bot 回覆：「請購買一杯咖啡獲得 VIP 排隊權 👇
   [Buy a Coffee 連結]"
    │
    ▼
使用者完成購買 → Callback Webhook
    │
    ▼
驗證訂單 (Coffee ID / 金額 / 時間)
    │
    ├── 驗證失敗 → 通知 LINE "驗證失敗，請重買"
    │
    └── 驗證成功 → 存入 vip_purchases → 標記 verified
                 → 可加入 VIP 隊列
```

---

## 12. 額外功能 (我設想的)

| 功能 | LINE Bot 指令 |
|------|------|
| **🔔 排隊提醒** | `/remind N` — 前方剩 N 人時推播通知 |
| **⏰ 逾時自動移除** | 30 分鐘未服務自動移除並通知 |
| **📊 統計面板** | `/admin/stats` — 今日排隊人數、平均等待時間 |
| **🔄 跳過/替換** | `/admin/skip` / `/admin/move <ID> <pos>` |
| **📋 排隊歷史** | `/history` / `/admin/history [ID]` |
| **🏷️ 稱號系統** | VIP 顯示「咖啡騎士」稱號 |
| **📤 匯出報表** | `/admin/export` — 匯出 CSV/Excel |
| **🔒 權限控制** | 只有 admin 可使用 `/admin/*` 指令 |
| **📈 即時圖表** | `/admin/chart` — 排隊人數變化趨勢 |
| **🔖 批次叫號** | `/admin/serve-batch N` — 一次叫 N 位 |
| **📮 跳號補叫** | `/admin/revive <ID>` — 被跳號者重新加入 |
| **🔔 叫號確認** | 被叫號者回覆 "done" 標記完成 |

---

## 13. 設定檔範例 (queue_config.yaml)

```yaml
server:
  host: "0.0.0.0"
  port: 8000
  debug: false

queue:
  max_capacity: 50
  timeout_minutes: 30
  timeout_action: "remove"    # "remove" 或 "warn"

vip:
  enabled: true
  coffee_price: 60
  coffee_url: "https://buymeacoffee.com/yourname"
  verification_endpoint: "https://api.buymeacoffee.com/v1/orders"

line_bot:
  channel_secret: "your_channel_secret"
  channel_access_token: "your_token"

logging:
  level: "INFO"
  log_file: "logs/queue_events.log"
  max_size_mb: 10
  backup_count: 5
```

---

## 14. 安裝與執行

```bash
# 1. 安裝依賴
pip install -r requirements.txt

# 2. 執行
python main.py

# 3. 自動化 (Windows 工作排程器)
# 加入 「每啟動時」執行 python main.py
```

### requirements.txt
```
fastapi==0.115.0
uvicorn==0.32.0
sqlite3
pydantic==2.9.0
line-bot-sdk==3.14.0
apscheduler==3.10.4
pyyaml==6.0.2
```

> **備註：** `websockets` 套件已移除，因為不再使用 WebSocket。

---

## 15. TDD (Test-Driven Development) 開發規劃

> **核心理念：** 先寫測試、再寫程式，測試通過才算完成
> **測試框架：** `pytest` + `pytest-asyncio` (Async) + `factory-boy` (工廠模式)
> **Coverage 目標：** 核心邏輯 > 80%，Bot 指令 > 70%，整體 > 75%

### 15.1 TDD 核心開發工作流 (The Workflow)

在進行任何功能開發前，必須遵循 **Red-Green-Refactor (RGR)** 循環。這不是為了寫測試而寫測試，而是透過測試來「設計」系統。

#### 🔄 RGR 循環標準作業程序

1.  **🔴 RED (Write a failing test)**
    *   根據規劃文件中的「功能規格」或「測試案例」，寫出一個針對新功能的測試。
    *   **必須是必然失敗的**。如果測試已經通過了，說明你寫的不是新功能測試。
    *   執行 `pytest`，確認測試結果為 `FAILED`。

2.  **🟢 GREEN (Make it pass)**
    *   撰寫「剛好能讓測試通過」的最低限度程式碼。
    *   **不要過度工程 (Over-engineering)**。如果測試只需要一個 `return True` 就能過，那就先寫一個，確保測試路徑是通的。
    *   執行 `pytest`，直到測試顯示 `PASSED`。

3.  **🔵 REFACTOR (Clean up)**
    *   在測試保護的情況下，優化程式碼結構、命名、邏輯。
    *   檢查是否符合 `PEP 8` 規範。
    *   再次執行 `pytest`，確保重構沒有破壞原有的功能。

---

#### 🛠️ 實作範例：以「加入隊列 (Join Queue)」為例

**Step 1: RED**
在 `tests/test_queue_core.py` 寫下：
```python
def test_join_regular_queue():
    manager = QueueManager()
    result = manager.join(user_id="user_1", queue_type="regular")
    assert result["status"] == "success"
    assert result["queue_number"] == 1
```
執行 `pytest` → **Error: `NameError: name 'QueueManager' is not defined`** (這是正確的失敗)。

**Step 2: GREEN**
在 `services/queue_manager.py` 寫下最低限度的實作：
```python
class QueueManager:
    def join(self, user_id, queue_type):
        return {"status": "success", "queue_number": 1}
```
執行 `pytest` → **PASSED**.

**Step 3: REFACTOR**
考慮到 ID 是否重複、容量是否已滿，將邏輯移入 `database.py`，並優化 `QueueManager` 的內部架構。
再次執行 `pytest` → **PASSED**.

---

#### 📋 開發檢查清單 (Definition of Done)

在進入下一個 Feature 之前，必須確認：
* [ ] **測試覆蓋率**：當前模組的測試覆蓋率是否達到目標 (例如 Core > 85%)？
* [ ] **邊界測試**：是否測試了 Empty ID、Duplicate ID、Full Capacity、Invalid Type 等極端情況？
* [ ] **無 Regression**：之前的測試案例是否全部維持在 `PASSED` 狀態？
* [ ] **代碼質量**：是否已進行 Linting 檢查 (如 `ruff` 或 `flake8`)？

### 15.2 TDD 開發階段與順序

```
Phase 1 ── 基礎設施 (Day 1-2)
   ├── 資料庫模型驗證測試
   ├── ID 驗證測試
   └── 基本隊列數據結構測試

Phase 2 ── 核心邏輯 (Day 3-5)
   ├── 加入隊列 (重複檢查、容量檢查)
   ├── 查看隊列狀態
   ├── 取消排隊
   └── 叫號/跳過

Phase 3 ── VIP 系統 (Day 6-7)
   ├── Buy a Coffee 驗證流程
   ├── VIP 隊列 toggle 測試
   ├── VIP 加入條件檢查
   └── 擁擠時段隔離測試

Phase 4 ── LINE Bot 指令 (Day 8-12)
   ├── 使用者指令 (/join, /status, /cancel, /remind, /help)
   ├── 管理員指令 (/admin/serve, /admin/skip, /admin/vip/*, /admin/stats)
   ├── 管理員權限驗證
   └── LINE Push API 通知測試

Phase 5 ── 排程任務 (Day 13-14)
   ├── 逾時自動移除測試
   ├── 排隊提醒測試
   └── Buy a Coffee Webhook 測試

Phase 6 ── 整合與優化 (Day 15-17)
   ├── E2E 完整流程測試
   ├── Performance Test
   └── Bug fix + Coverage 補齊
```

### 15.3 測試程式碼結構

```
queue_system/
├── tests/
│   ├── conftest.py            # 全域 fixtures (DB, Factory, Bot Context)
│   ├── factories.py           # Factory-boy 工廠
│   ├── test_queue_core.py     # 隊列核心邏輯測試
│   ├── test_vip_service.py    # VIP 測試
│   ├── test_validators.py     # ID 驗證測試
│   ├── test_bot_commands.py   # LINE Bot 指令測試
│   ├── test_notifiers.py      # LINE Push/Reply 通知測試
│   ├── test_scheduler.py      # 排程/逾時任務測試
│   ├── test_e2e.py            # E2E 完整流程測試
│   └── test_performance.py    # 壓力測試
├── pytest.ini                 # pytest 設定
└── .coveragerc                # Coverage 設定
```

### 15.4 關鍵測試案例 (代表)

#### 隊列核心邏輯 (test_queue_core.py)

```python
# --- 加入隊列 ---
class TestJoinQueue:
    def test_join_regular_queue(self):        # 正常加入
    def test_join_vip_queue_no_purchase(self):# VIP 未購買咖啡 → 拒絕
    def test_join_duplicate_user(self):       # 已在隊列 → 拒絕
    def test_join_over_capacity(self):        # 隊列滿 → 拒絕
    def test_join_empty_id(self):            # ID 為空 → 拒絕
    def test_join_special_chars_id(self):    # ID 含特殊字元

# --- 查看隊列 ---
class TestQueueStatus:
    def test_empty_queue(self):              # 空隊列
    def test_regular_only(self):            # 只有標準隊列
    def test_both_queues(self):            # 都有人
    def test_masked_ids(self):            # 遮罩 ID (安全性)

# --- 取消排隊 ---
class TestCancelQueue:
    def test_cancel_exists(self):          # 正常取消
    def test_cancel_nonexistent(self):     # 不在隊列 → 拒絕
    def test_cancel_already_served(self):  # 已被叫號 → 拒絕

# --- 叫號 ---
class TestServeQueue:
    def test_serve_next(self):             # 叫下一位
    def test_serve_specific(self):        # 指定叫號
    def test_serve_empty_queue(self):     # 空隊列 → 錯誤
    def test_serve_resets_numbering(self): # 叫號後重新編號
```

#### VIP 服務 (test_vip_service.py)

```python
class TestVipService:
    def test_vip_purchase_success(self):          # 購買成功
    def test_vip_duplicate_purchase(self):        # 重複購買 → 記錄但不重複
    def test_vip_coffee_disabled(self):           # VIP 關閉 → 禁止加入
    def test_vip_verification_failed(self):       # 驗證失敗
    def test_vip_queue_empty(self):              # VIP 空隊列
    def test_vip_toggle_enable(self):            # 開啟 VIP
    def test_vip_toggle_disable(self):           # 關閉 VIP → 清空 VIP 隊列
    def test_vip_cross_queue_service(self):       # VIP 和標準隊列叫號
```

#### LINE Bot 指令測試 (test_bot_commands.py)

```python
class TestBotCommands:
    def test_join_command(self):              # /join user_12345
    def test_join_vip_no_coffee(self):       # /join vip 未購買咖啡 → 拒絕
    def test_status_command(self):           # /status 回傳隊列狀態
    def test_cancel_command(self):           # /cancel 取消排隊
    def test_help_command(self):             # /help 顯示說明
    def test_remind_command(self):           # /remind N 設定提醒
    def test_join_duplicate(self):           # 重複 /join 同一人 → 拒絕
    def test_empty_join(self):              # /join 無 ID → 拒絕
    def test_vip_command(self):             # /coffee 返回連結
    def test_invalid_command(self):         # 無效指令 → 提示

class TestAdminCommands:
    def test_admin_serve(self):              # /admin/serve 叫號
    def test_admin_serve_specific(self):    # /admin/serve ID 指定叫號
    def test_admin_skip(self):              # /admin/skip 跳過
    def test_admin_vip_toggle(self):        # /admin/vip toggle
    def test_admin_vip_clear(self):         # /admin/vip clear
    def test_admin_status(self):            # /admin/status 完整隊列
    def test_admin_stats(self):            # /admin/stats 統計資料
    def test_admin_config(self):           # /admin/config max N
    def test_admin_unauthorized(self):      # 非 admin 用指令 → 拒絕
```

#### E2E 測試 (test_e2e.py)

```python
class TestEndToEnd:
    def test_full_join_serve_cancel(self):       # 加入→叫號→取消
    def test_full_join_status_cancel(self):     # 加入→查看→取消
    def test_multiple_users_order(self):        # 多使用者排隊順序
    def test_vip_priority_flow(self):          # VIP 優先排隊流程
    def test_over_capacity_rejection(self):    # 超出容量拒絕加入
```

### 15.5 pytest 設定 (pytest.ini)

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --strict-markers
    --tb=short
    --cov=queue_system
    --cov-report=term-missing
    --cov-report=html:htmlcov
    --maxfail=5
    --durations=10

markers =
    slow: 慢速測試
    integration: 整合測試
    e2e: E2E 測試
    performance: 性能測試
    unit: 單元測試
```

### 15.6 Coverage 設定 (.coveragerc)

```ini
[run]
source = queue_system
branch = true
omit =
    tests/*
    setup.py
    */__init__.py

[report]
exclude_lines =
    pragma: no cover
    if TYPE_CHECKING:
    @abc.abstractmethod
show_missing = true
precision = 2
fail_under = 75
```

### 15.7 CI/CD Pipeline

```yaml
# .github/workflows/tests.yml (GitHub Actions 範例)
name: Tests

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - name: Install deps
        run: pip install -r requirements.txt pytest pytest-asyncio pytest-cov pytest-factoryboy
      - name: Run Tests
        run: pytest -v --cov=queue_system --cov-report=xml --maxfail=3
      - name: Upload Coverage
        uses: codecov/codecov-action@v4
        with:
          file: coverage.xml
```

### 15.8 Fixture 與 Factory (conftest.py + factories.py)

```python
# conftest.py
import pytest
import sqlite3
from line_bot_sdk import ...  # LINE Bot SDK

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_queue.db")

@pytest.fixture
def bot_context(db_path):
    # 模擬 LINE Bot 上下文 (user_id, reply_token 等)
    return {
        "user_id": "U1234567890abcdef",
        "reply_token": "xxxxxx",
        "db_path": db_path
    }

# factories.py
import factory
from queue_system.models import QueueEntry

class QueueEntryFactory(factory.Factory):
    class Meta:
        model = QueueEntry
    user_id = factory.Sequence(lambda n: f"user_{n}")
    queue_type = "regular"
    joined_at = factory.Faker("past_datetime")
```

### 15.9 測試順序與優先級

| 優先級 | 測試模組 | 執行順序 | 預估行數 |
|--------|----------|----------|----------|
| P0 (最高) | `test_validators.py` | 第一 | ~150 |
| P0 | `test_queue_core.py` | 第二 | ~300 |
| P1 | `test_vip_service.py` | 第三 | ~200 |
| P1 | `test_bot_commands.py` | 第四 | ~350 |
| P1 | `test_notifiers.py` | 第五 | ~200 |
| P2 | `test_scheduler.py` | 第六 | ~150 |
| P2 | `test_e2e.py` | 第七 | ~200 |
| P3 | `test_performance.py` | 最後 | ~150 |

**Total: ~1,700 行測試程式碼**

---

## 16. 未來擴展方向

| 方向 | 說明 |
|------|------|
| **Redis 替代 SQLite** | 高流量時用 Redis 隊列 |
| **Python 多線程 Worker** | 背景處理大量通知 |
| **Docker 化** | Docker Compose 部署 |
| **其他平台** | Slack Bot / Telegram Bot 擴充 |
| **群組排隊** | 多人同時加入，以群組為單位 |
| **隊伍合併** | 不同 Queue 可以合併 |
| **多語言支援** | 中文 / 英文 / 日文界面 |
| **QR Code 排隊** | 管理員產生 QR，使用者掃描加入 |

---

> **規劃完成日期：** 2026-04-18
> **版本：** v2.0 (LINE Bot 統一期)
> **總計功能點：** 20+
> **預估開發時數：** ~40-60 小時 (从零開始)
