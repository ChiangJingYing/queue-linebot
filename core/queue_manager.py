"""Queue manager 核心商業邏輯。

這個模組負責與資料庫層協作，實作隊列的主要規則：
- 加入 / 取消 / 叫號 / 跳過
- 一般與 VIP 隊列檢查
- 管理統計、匯出與清空
- 使用者基本資料與驗證狀態
- 通知器觸發時機

平台層（LINE / Telegram / Discord）應盡量透過這個 class 操作隊列，
把 UI 與訊息格式留在 service / handler 層處理。
"""

from __future__ import annotations

from datetime import datetime

from .database import DatabaseManager
from .validators import validate_user_id


class QueueManager:
    """封裝隊列核心規則與資料庫/通知器協作。

    ``QueueManager`` 本身不建立平台推播物件；``self.notifier`` 採注入式設計：
    - 可在建構時透過 ``QueueManager(db, notifier=...)`` 傳入
    - 也可在外部初始化完成後再補掛 ``queue_manager.notifier = Notifier(...)``

    這樣 queue 核心就能維持與 LINE / Telegram / Discord 平台實作解耦，
    只在需要通知使用者時呼叫 notifier 的共用介面。
    """

    def __init__(
        self,
        db: DatabaseManager | None = None,
        notifier: object | None = None,
    ) -> None:
        """初始化資料庫介面與可選 notifier。

        ``notifier`` 預期提供像 ``notify_served()``、``notify_skip()``、
        ``notify_user()`` 這類方法。若未注入，queue 操作仍可正常進行，
        只是 serve / skip / ping 等流程不會額外對使用者送出私訊通知。
        """
        #: 資料存取層，負責 queue row、config、profile、event log 等持久化操作。
        self.db = db or DatabaseManager()
        #: 可選通知出口；由外部 runtime / service 注入，不由 QueueManager 自行建立。
        self.notifier = notifier

    # -- join --

    def join(self, user_id: str, queue_type: str = "regular") -> dict:
        """將使用者加入一般或 VIP 隊列。

        主要檢查項目：
        - user id 是否有效
        - 是否重複排隊
        - 總隊列是否開放
        - VIP 是否啟用且使用者是否已購買
        - 一般隊列是否超過容量上限

        成功時回傳目前號碼、位置與總人數；失敗時回傳統一錯誤 dict。
        """
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        existing = self.db.get_active_queue_entry(valid_id)
        if existing is not None:
            if existing.served:
                return {
                    "status": "error",
                    "message": f"你已被叫號（號碼 #{existing.queue_number}），請等待叫號者解除後再加入。",
                }
            return {
                "status": "error",
                "message": f"你已在排隊中（號碼 #{existing.queue_number}），請勿重複加入。",
            }

        if not self.db.is_queue_enabled():
            return {"status": "error", "message": "目前隊列已關閉，請稍後再試。"}

        if queue_type == "vip":
            if not self.db.is_vip_enabled():
                return {"status": "error", "message": "VIP 隊列目前已停用。"}
            if not self.db.is_vip_purchased(valid_id):
                return {"status": "error", "message": "尚未找到 VIP 購買紀錄，請先購買咖啡。"}

        entry = self.db.join_queue(valid_id, queue_type)

        if queue_type == "regular":
            max_cap = self.db.get_queue_max_capacity()
            if len(self.db.get_regular_queue()) > max_cap:
                self.db.cancel_queue(valid_id)
                return {"status": "error", "message": "隊列已滿，請稍後再試。"}

        self.db.log_event("join", valid_id, queue_type)

        all_queue = self.db.get_all_queue()
        return {
            "status": "success",
            "queue_number": entry.queue_number,
            "position": len(all_queue) - len([e for e in all_queue if e.queue_number > entry.queue_number]),
            "total_in_queue": len(all_queue),
        }

    # -- cancel --

    def cancel(self, user_id: str) -> dict:
        """取消使用者目前的有效排隊紀錄。"""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        entry = self.db.cancel_queue(valid_id)
        if entry is None:
            return {"status": "error", "message": "你目前不在隊列中。"}

        self.db.log_event("cancel", valid_id, entry.queue_type)

        return {
            "status": "cancelled",
            "id": valid_id,
            "removed_position": entry.queue_number,
            "new_total": len(self.db.get_all_queue()),
        }

    # -- serve --

    def serve_next(self) -> dict:
        """叫號目前隊列最前面的使用者，必要時觸發 notifier。

        成功 serve 後會：
        1. 更新隊列資料狀態
        2. 寫入 ``serve`` event log
        3. 若 ``self.notifier`` 存在，呼叫 ``notify_served(user_id, queue_number)``（私訊通知被叫號者）
        """
        all_q = self.db.get_all_queue()
        if not all_q:
            return {"status": "error", "message": "目前隊列是空的。"}

        head = all_q[0]
        served = self.db.serve_queue(head.user_id)
        if served is None:
            return {"status": "error", "message": "叫號失敗，請稍後再試。"}

        self.db.log_event("serve", head.user_id, head.queue_type)

        if self.notifier:
            self.notifier.notify_served(head.user_id, served.queue_number)

        return {"status": "served", "id": head.user_id, "queue_number": served.queue_number}

    def serve_specific(self, user_id: str) -> dict:
        """叫指定使用者的號，前提是該使用者目前仍在有效隊列中。

        與 ``serve_next()`` 相同，成功後若有 ``self.notifier``，
        會對該使用者送出 ``notify_served()`` 私訊通知。
        """
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        served = self.db.serve_queue(valid_id)
        if served is None:
            return {"status": "error", "message": "該使用者目前不在隊列中。"}

        self.db.log_event("serve", valid_id, served.queue_type)

        if self.notifier:
            self.notifier.notify_served(valid_id, served.queue_number)

        return {"status": "served", "id": valid_id, "queue_number": served.queue_number}

    # -- skip --

    def skip_next(self) -> dict:
        """跳過目前隊列最前面的使用者，必要時觸發 notifier。

        若 ``self.notifier`` 存在，會呼叫 ``notify_skip(user_id)`` 通知被跳過者。
        """
        all_q = self.db.get_all_queue()
        if not all_q:
            return {"status": "error", "message": "目前隊列是空的。"}

        head = all_q[0]
        skipped = self.db.skip_queue(head.user_id)
        if skipped is None:
            return {"status": "error", "message": "跳過失敗，請稍後再試。"}

        self.db.log_event("skip", head.user_id, head.queue_type)

        # Push notification to skipped user
        if self.notifier:
            self.notifier.notify_skip(head.user_id)

        return {"status": "skipped", "id": head.user_id, "queue_number": head.queue_number}

    def skip_specific(self, user_id: str) -> dict:
        """跳過指定使用者。

        成功後若有 ``self.notifier``，會對被跳過的使用者送出 ``notify_skip()``。
        """
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        skipped = self.db.skip_queue(valid_id)
        if skipped is None:
            return {"status": "error", "message": "該使用者目前不在隊列中。"}

        self.db.log_event("skip", valid_id, skipped.queue_type)

        # Push notification to skipped user
        if self.notifier:
            self.notifier.notify_skip(valid_id)

        return {"status": "skipped", "id": valid_id, "queue_number": skipped.queue_number}

    # -- release (解除叫號鎖定) --

    def release_served(self, user_id: str) -> dict:
        """解除指定使用者的叫號鎖定，使其可再次加入隊列。

        當管理員完成服務後，呼叫此方法解除使用者的「已叫號待解除」狀態，
        讓使用者可以重新加入隊列。
        """
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        released = self.db.release_queue(valid_id)
        if released is None:
            return {"status": "error", "message": "該使用者目前沒有待解除的叫號記錄。"}

        self.db.log_event("release", valid_id, released.queue_type, "管理員解除叫號鎖定")
        return {"status": "released", "id": valid_id, "queue_number": released.queue_number}

    def get_called_entry(self, user_id: str):
        """回傳使用者目前「已叫號待解除」的記錄；若不存在則為 ``None``。"""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return None
        return self.db.get_called_entry(valid_id)

    def get_called_queue(self) -> list:
        """回傳所有目前「已叫號待解除」的使用者列表。"""
        return self.db.get_called_queue()

    # -- status --

    def get_status(self) -> dict:
        """回傳 admin/status 類介面需要的聚合隊列狀態。"""
        regular = self.db.get_regular_queue()
        vip = self.db.get_vip_queue()

        reg_head = regular[0].user_id if regular else ""
        vip_head = vip[0].user_id if vip else ""

        return {
            "regular_count": len(regular),
            "regular_next": reg_head,
            "regular_head": reg_head,
            "vip_count": len(vip),
            "vip_next": vip_head,
            "vip_enabled": self.db.is_vip_enabled(),
        }

    def get_queue(self) -> list:
        """取得完整有效隊列，供 admin 視圖或 presenter 使用。"""
        return self.db.get_all_queue()

    def get_history(self, user_id: str) -> list:
        """取得特定使用者的原始歷史資料；無效 id 時回空列表。"""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return []
        return self.db.get_user_history(valid_id)

    def get_stats(self) -> dict:
        """計算今日 admin 統計資料。

        目前統計包含：
        - 今日加入人數
        - 今日叫號數
        - 今日取消/跳過數
        - 平均等待分鐘數
        - VIP 啟用/活躍/今日加入/今日叫號
        """
        today = datetime.now().date()
        all_rows = self.db.get_queue_rows_for_export(limit=1000)

        joined_today = 0
        served_count = 0
        skipped_count = 0
        served_waits = []
        vip_joined_today = 0
        vip_served_count = 0
        vip_active_count = len(self.db.get_vip_queue())

        for row in all_rows:
            join_time = row.get("join_time")
            served_time = row.get("served_time")
            cancel_time = row.get("cancel_time")
            queue_type = row.get("queue_type")

            join_dt = datetime.fromisoformat(join_time) if join_time else None
            served_dt = datetime.fromisoformat(served_time) if served_time else None
            cancel_dt = datetime.fromisoformat(cancel_time) if cancel_time else None

            if join_dt and join_dt.date() == today:
                joined_today += 1
                if queue_type == "vip":
                    vip_joined_today += 1

            if served_dt and served_dt.date() == today:
                served_count += 1
                if join_dt:
                    served_waits.append((served_dt - join_dt).total_seconds() / 60)
                if queue_type == "vip":
                    vip_served_count += 1

            if cancel_dt and cancel_dt.date() == today:
                skipped_count += 1

        average_wait = sum(served_waits) / len(served_waits) if served_waits else 0.0

        return {
            "joined_today": joined_today,
            "served_count": served_count,
            "skipped_count": skipped_count,
            "average_wait_minutes": average_wait,
            "vip": {
                "enabled": self.db.is_vip_enabled(),
                "active_count": vip_active_count,
                "joined_today": vip_joined_today,
                "served_count": vip_served_count,
            },
        }

    def clear_vip_queue(self) -> dict:
        """清空所有有效 VIP 排隊紀錄，並逐筆記錄 admin event log。"""
        removed_users = []
        for entry in list(self.db.get_vip_queue()):
            cancelled = self.db.cancel_queue(entry.user_id)
            if cancelled is not None:
                removed_users.append(entry.user_id)
                self.db.log_event("vip_clear", entry.user_id, entry.queue_type, "管理員清空 VIP 隊列")

        return {
            "status": "cleared",
            "removed_count": len(removed_users),
            "removed_users": removed_users,
        }

    def get_user_position(self, user_id: str) -> int | None:
        """回傳使用者目前的 1-based 排位；若不在隊列中則為 ``None``。"""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return None

        for index, entry in enumerate(self.db.get_all_queue(), start=1):
            if entry.user_id == valid_id:
                return index
        return None

    def get_queue_stats(self) -> dict:
        """回傳整體系統摘要統計。

        與 ``get_stats()`` 不同，這裡偏向總覽：
        - 已完成基本註冊的人數
        - 目前排隊中人數
        - 累計已叫號人數
        """
        profiles = self.db.get_all_user_profiles()
        registered = sum(1 for p in profiles if p.location and p.location.strip())
        active_queue = self.db.get_all_queue()
        served = self.db.get_queue_rows_for_export(limit=10000)
        served_count = sum(
            1
            for r in served
            if r.get("served_time") is not None and not r.get("cancel_time")
        )

        return {
            "registered": registered,
            "queue": len(active_queue),
            "served": served_count,
        }

    def clear_all_queue(self, keep_admin_user_ids: set[str] | None = None) -> dict:
        """清空全部隊列、已服務紀錄、使用者資料與管理員申請。

        ``keep_admin_user_ids`` 允許在重置時保留部分 admin 個人資料，避免管理後台
        清空隊列時把自己也一併刪掉。
        """
        removed_entries = self.db.clear_all_queue()
        removed_users = [entry.user_id for entry in removed_entries]
        cleared_served = self.db.clear_served_queue()
        cleared_profiles, kept_admin_profiles = self.db.clear_all_user_profiles(
            keep_user_ids=keep_admin_user_ids or set()
        )
        cleared_admin_applications = self.db.clear_all_admin_applications()
        for entry in removed_entries:
            self.db.log_event("clear", entry.user_id, entry.queue_type, "管理員清空全部隊列")
        return {
            "status": "cleared",
            "removed_count": len(removed_users),
            "removed_users": removed_users,
            "cleared_profiles": cleared_profiles,
            "cleared_profiles_user": cleared_profiles,
            "kept_admin_profiles": kept_admin_profiles,
            "cleared_profiles_admin": kept_admin_profiles,
            "cleared_served": cleared_served,
            "cleared_admin_applications": cleared_admin_applications,
        }

    def register_name(self, user_id: str, display_name: str, location: str = "") -> dict:
        """建立或更新使用者基本資料。

        目前至少要求非空白顯示名稱，位置可由上層流程決定是否必填。
        """
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        normalized_name = display_name.strip()
        if not normalized_name:
            return {"status": "error", "message": "名稱不可為空白。"}

        profile = self.db.upsert_user_profile(valid_id, normalized_name, location=location)
        return {
            "status": "success",
            "user_id": profile.user_id,
            "display_name": profile.display_name,
            "location": profile.location,
            "verified": profile.verified,
        }

    def verify_user(self, user_id: str, verified: bool = True) -> dict:
        """設定使用者驗證狀態。"""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        profile = self.db.get_user_profile(valid_id)
        if profile is None:
            return {"status": "error", "message": "尚未找到該使用者的名稱註冊資料。"}

        updated = self.db.verify_user_profile(valid_id, verified)
        return {
            "status": "success",
            "user_id": valid_id,
            "display_name": updated.display_name if updated else profile.display_name,
            "verified": bool(updated.verified) if updated else verified,
        }

    def ping_user(self, user_id: str | None = None) -> dict:
        """手動提醒指定使用者，或預設提醒隊首使用者。

        這個方法不改變 queue 狀態，只在有 ``self.notifier`` 時呼叫
        ``notify_user()`` 送出提醒訊息，並記錄一筆 ``ping`` event。
        """
        target_id = user_id
        if not target_id:
            all_q = self.db.get_all_queue()
            if not all_q:
                return {"status": "error", "message": "目前隊列是空的。"}
            target_id = all_q[0].user_id

        valid_id = validate_user_id(target_id)
        if valid_id is None:
            return {"status": "error", "message": "使用者 ID 格式不正確。"}

        entry = self.db.get_active_queue_entry(valid_id)
        if entry is None:
            return {"status": "error", "message": "該使用者目前不在隊列中。"}

        display_name = self.db.get_display_name(valid_id)
        if self.notifier:
            self.notifier.notify_user(valid_id, f"📣 {display_name}，輪到你注意隊列狀態了。")
        self.db.log_event("ping", valid_id, entry.queue_type, "管理員手動提醒")
        return {"status": "success", "user_id": valid_id, "display_name": display_name}

    def get_user_history(self, user_id: str, limit: int = 20) -> list[dict]:
        """將 event history 轉成平台層較容易消費的 dict 結構。"""
        valid_id = validate_user_id(user_id)
        if valid_id is None:
            return []

        events = self.db.get_event_history(valid_id, limit=limit)
        return [
            {
                "event_type": event.event_type,
                "user_id": event.user_id,
                "queue_type": event.queue_type,
                "details": event.details,
                "created_at": event.created_at,
            }
            for event in events
        ]

    def export_queue_csv(self, limit: int = 20) -> str:
        """匯出隊列資料為 CSV 字串。"""
        return self.db.export_queue_csv(limit=limit)

    # -- config --

    def set_queue_enabled(self, enabled: bool) -> dict:
        """開啟或關閉隊列加入功能。"""
        self.db.set_config("queue_enabled", "true" if enabled else "false")
        return {"status": "ok", "queue_enabled": enabled}

    def get_queue_enabled(self) -> bool:
        """讀取目前是否允許新使用者加入隊列。"""
        return self.db.is_queue_enabled()

    def set_max_capacity(self, n: int) -> dict:
        """設定一般隊列人數上限。"""
        self.db.set_config("queue_max_capacity", str(n))
        return {"status": "ok", "max_capacity": n}

    def get_max_capacity(self) -> int:
        """讀取一般隊列人數上限。"""
        return self.db.get_queue_max_capacity()

