"""Small best-effort background dispatch helpers."""

from __future__ import annotations

from collections.abc import Callable
import logging
from queue import Empty, Queue
import threading
from typing import TypeVar


logger = logging.getLogger(__name__)
T = TypeVar("T")


class InlineDispatcher:
    """Run dispatched work immediately.

    Tests use this default so side effects remain deterministic.
    """

    def dispatch(self, func: Callable[[], T]) -> T:
        return func()


class ThreadedDispatcher:
    """Run dispatched work in a daemon thread pool on a best-effort basis."""

    def __init__(self, *, max_workers: int = 4) -> None:
        self._queue: Queue[Callable[[], object] | None] = Queue()
        self._workers = [
            threading.Thread(target=self._run_worker, name=f"queue-notify_{index}", daemon=True)
            for index in range(max(int(max_workers), 1))
        ]
        for worker in self._workers:
            worker.start()

    def dispatch(self, func: Callable[[], T]) -> None:
        self._queue.put(func)
        return None

    def shutdown(self, *, wait: bool = False) -> None:
        for _ in self._workers:
            self._queue.put(None)
        if wait:
            for worker in self._workers:
                worker.join()

    def _run_worker(self) -> None:
        while True:
            try:
                func = self._queue.get()
            except Empty:
                continue
            try:
                if func is None:
                    return
                func()
            except Exception:
                logger.exception("Background notification task failed")
            finally:
                self._queue.task_done()


DEFAULT_DISPATCHER = InlineDispatcher()
