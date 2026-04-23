# Web UI Auth Plan

## Goal
為目前的 Web UI / 管理型 HTTP 端點加入**簡易密鑰防護**，先用低成本方式降低未授權存取風險，不引入完整帳號系統。

## Scope
第一階段先保護這些端點：

- `GET /dashboard`
- `GET /dashboard/data`
- `GET /dashboard/config`
- `GET /dashboard/layout`
- `POST /dashboard/layout`
- `POST /dashboard/layout/reset`
- `POST /dashboard/layout/image`
- `GET /dashboard/assets/{filename}`
- `POST /api/queue/reset`

> 若未來確認公開看板可匿名讀取，可把 `/dashboard`、`/dashboard/data`、`/dashboard/assets/*` 改成只保護寫入端點。

## Proposed Approach
採用單一 shared secret，透過以下任一方式通過驗證：

1. `X-Admin-Token: <token>` header
2. `?token=<token>` query string（只建議過渡期或內網使用）
3. Cookie session（登入成功後寫入短期 cookie，減少手動帶 token）

### 建議分兩階段

#### Phase 1 — Header / Query Token
- 新增 config：`web_ui.admin_token`
- 若 token 未設定：
  - 開發模式可放行並記 warning log
  - production 建議拒絕啟動或至少高亮警告
- 新增共用驗證函式，例如：`require_web_ui_token(request)`
- 對上述路由統一套用

優點：
- 實作快
- 幾乎不需改資料庫
- 適合內網 / 小團隊

缺點：
- query token 可能進入瀏覽器歷史與 proxy log
- 使用者體驗普通

#### Phase 2 — Simple Login Session
- 新增 `/dashboard/login`
- 使用表單輸入 token
- 驗證成功後設定 signed cookie
- 後續 dashboard/config/layout API 讀 cookie 驗證
- logout 時清除 cookie

優點：
- UX 較好
- 不需每次手動附 token

缺點：
- 要補 CSRF / cookie 安全屬性
- 複雜度高於 phase 1

## Recommended Config Shape
```yaml
web_ui:
  admin_token: "change-me"
  protect_read_routes: true
  allow_query_token: false
  session_cookie_name: "queue_admin_session"
```

## Recommended Validation Rules
- token 必須使用常數時間比較（`hmac.compare_digest`）
- 空 token 視為未設定，不可與空請求視為相等
- 寫入型端點一律需要 auth
- 若 `protect_read_routes = true`，讀取型端點也需要 auth
- 驗證失敗回 `401 Unauthorized`
- 不在 log 中印出完整 token

## Suggested Implementation Steps

### Step 1: Config
- 在 `config.py` 的 defaults 中加入 `web_ui`
- 支援從環境變數讀取，例如：`WEB_UI_ADMIN_TOKEN`

### Step 2: Shared Guard
新增類似：

- `_extract_web_ui_token(request)`
- `_is_valid_web_ui_token(request)`
- `require_web_ui_auth(request)`

並集中放在：
- `main.py`
- 或 `utils/auth.py`

### Step 3: Protect Routes
先保護寫入路由：
- `POST /api/queue/reset`
- `POST /dashboard/layout`
- `POST /dashboard/layout/reset`
- `POST /dashboard/layout/image`

再視需要擴大到讀取路由。

### Step 4: Optional Login Page
若要改善 UX：
- 新增 `/dashboard/login`
- 成功後 set cookie
- `/dashboard/config` 與 `/dashboard` 改讀 cookie

## Security Notes

### Query token 風險
若放在 URL：
- 容易出現在瀏覽器歷史
- 容易出現在 server/access logs
- 若有第三方資源請求，可能經由 referrer 洩漏

因此建議：
- query token 只做過渡
- 最終以 header 或 cookie 為主

### Cookie 建議
若進入 phase 2：
- `HttpOnly=true`
- `Secure=true`（HTTPS）
- `SameSite=Lax` 或 `Strict`
- 設有效期限

### Reverse Proxy
若服務會掛在 nginx / caddy 後：
- 避免 access log 記錄完整 query string
- 只允許內網來源更佳

## Non-Goals
這份簡易方案**不處理**：
- 多使用者帳號系統
- 權限分級（viewer/editor/admin）
- OAuth / LINE Login / Telegram Login
- 審計紀錄與異常告警

## Suggested Future Upgrades
若未來需求升級，可往下走：
1. signed cookie session
2. RBAC（viewer/editor/admin）
3. IP allowlist
4. CSRF protection for form posts
5. audit log for reset/layout changes

## Rollout Recommendation
建議 rollout 順序：

1. 先做 phase 1，只保護寫入路由
2. 驗證部署流程沒問題
3. 再決定是否連讀取路由一起保護
4. 若常用 dashboard/config，再做 phase 2 cookie login

## Acceptance Criteria
- 未帶正確 token 時，管理型寫入端點回 401
- 帶正確 token 時可正常操作
- token 不會被完整寫入 log
- config 缺 token 時，系統能明確提示風險
