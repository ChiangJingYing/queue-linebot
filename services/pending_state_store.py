from __future__ import annotations

import json
from typing import Protocol


class PendingStateStore(Protocol):
    def get(self, *, user_id: str, flow: str) -> dict: ...
    def set(self, *, user_id: str, flow: str, state: dict) -> None: ...
    def clear(self, *, user_id: str, flow: str) -> None: ...


class MemoryPendingStateStore:
    def __init__(self) -> None:
        self._states: dict[tuple[str, str], dict] = {}

    def get(self, *, user_id: str, flow: str) -> dict:
        state = self._states.get((user_id, flow), {})
        return state if isinstance(state, dict) else {}

    def set(self, *, user_id: str, flow: str, state: dict) -> None:
        self._states[(user_id, flow)] = dict(state)

    def clear(self, *, user_id: str, flow: str) -> None:
        self._states.pop((user_id, flow), None)


class ConfigPendingStateStore:
    def __init__(self, db, *, namespace: str) -> None:
        self.db = db
        self.namespace = namespace

    def _key(self, *, user_id: str, flow: str) -> str:
        return f"{self.namespace}_pending_{flow}:{user_id}"

    def get(self, *, user_id: str, flow: str) -> dict:
        raw = self.db.get_config(self._key(user_id=user_id, flow=flow))
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def set(self, *, user_id: str, flow: str, state: dict) -> None:
        self.db.set_config(self._key(user_id=user_id, flow=flow), json.dumps(state, ensure_ascii=False))

    def clear(self, *, user_id: str, flow: str) -> None:
        self.db.set_config(self._key(user_id=user_id, flow=flow), "")
