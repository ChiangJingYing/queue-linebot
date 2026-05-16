"""Shared admin serve concurrency and cooldown guard."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable


class AdminServeGuard:
    """Share one serve lock/cooldown state across platform handlers."""

    def __init__(
        self,
        *,
        cooldown_seconds: int = 3,
        clock: Callable[[], float] | None = None,
        lock: threading.Lock | None = None,
    ) -> None:
        self.lock = lock or threading.Lock()
        self.clock = clock or time.monotonic
        self.cooldown_seconds = max(int(cooldown_seconds), 0)
        self.last_served_at = 0.0
        self.last_served_label = ""

    def try_acquire(self) -> bool:
        return self.lock.acquire(blocking=False)

    def release(self) -> None:
        self.lock.release()

    def cooldown_message(self) -> str | None:
        if self.cooldown_seconds <= 0 or not self.last_served_at:
            return None
        if self.clock() - self.last_served_at >= self.cooldown_seconds:
            return None
        label = self.last_served_label or "上一位使用者"
        return f"⚠️ 剛剛已叫號：{label}，請稍候再試，避免重複叫號。"

    def record_success(self, display_name: str) -> None:
        self.last_served_at = self.clock()
        self.last_served_label = display_name

    def set_cooldown_seconds(self, cooldown_seconds: int) -> None:
        self.cooldown_seconds = max(int(cooldown_seconds), 0)
