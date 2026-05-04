"""pending flow state 的抽象與儲存實作。"""

from __future__ import annotations

import json
from typing import Protocol


class PendingStateStore(Protocol):
    """描述 register/cancel 等多步驟流程所需的狀態儲存介面。"""

    def get(self, *, user_id: str, flow: str) -> dict: ...
    def set(self, *, user_id: str, flow: str, state: dict) -> None: ...
    def clear(self, *, user_id: str, flow: str) -> None: ...


class MemoryPendingStateStore:
    """用於單進程情境或測試的 in-memory pending state store。"""

    def __init__(self) -> None:
        """以 `(user_id, flow)` 為 key 初始化暫存狀態表。"""
        self._states: dict[tuple[str, str], dict] = {}

    def get(self, *, user_id: str, flow: str) -> dict:
        """讀取指定使用者/流程的狀態；若不存在則回傳空 dict。"""
        state = self._states.get((user_id, flow), {})
        return state if isinstance(state, dict) else {}

    def set(self, *, user_id: str, flow: str, state: dict) -> None:
        """寫入指定使用者/流程的狀態副本。"""
        self._states[(user_id, flow)] = dict(state)

    def clear(self, *, user_id: str, flow: str) -> None:
        """清除指定使用者/流程的狀態。"""
        self._states.pop((user_id, flow), None)


class ConfigPendingStateStore:
    """以 database config 欄位持久化 pending state。"""

    def __init__(self, db, *, namespace: str) -> None:
        """保存資料庫介面與 config key namespace。"""
        self.db = db
        self.namespace = namespace

    def _key(self, *, user_id: str, flow: str) -> str:
        """組出此 store 使用的 config key。"""
        return f"{self.namespace}_pending_{flow}:{user_id}"

    def get(self, *, user_id: str, flow: str) -> dict:
        """從 config 讀取 JSON 狀態；資料損壞時安全回退為空 dict。"""
        raw = self.db.get_config(self._key(user_id=user_id, flow=flow))
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def set(self, *, user_id: str, flow: str, state: dict) -> None:
        """將 pending state 序列化後寫入 config。"""
        self.db.set_config(self._key(user_id=user_id, flow=flow), json.dumps(state, ensure_ascii=False))

    def clear(self, *, user_id: str, flow: str) -> None:
        """以空字串覆蓋 config，表示流程狀態已清除。"""
        self.db.set_config(self._key(user_id=user_id, flow=flow), "")
