"""Generic background task that reports back to the GUI through Qt signals.

Short-lived jobs (playlist loading, FFmpeg detection, size estimation) run on
daemon threads, so a slow network call can never block application exit.
Results are delivered to the GUI thread via queued signal connections.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from utils.logger import get_logger

log = get_logger("task")


class TaskSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)  # the exception instance
    progress = Signal(object)
    finished = Signal()


class BackgroundTask:
    """Run ``fn(task)`` on a daemon thread.

    ``fn`` receives the task itself so it can call :meth:`report` and check
    :attr:`cancelled`. Results of a cancelled task are discarded.
    """

    def __init__(self, fn: Callable[[BackgroundTask], Any], name: str = "task") -> None:
        self.signals = TaskSignals()
        self._fn = fn
        self._name = name
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> BackgroundTask:
        self._thread.start()
        return self

    def cancel(self) -> None:
        self._cancel.set()

    def report(self, payload: Any) -> None:
        """Send intermediate results to the GUI (ignored once cancelled)."""
        if not self.cancelled:
            self._safe_emit(self.signals.progress, payload)

    def _run(self) -> None:
        try:
            result = self._fn(self)
        except Exception as exc:  # noqa: BLE001 - forwarded to the GUI
            log.debug("Task %s failed", self._name, exc_info=True)
            if not self.cancelled:
                self._safe_emit(self.signals.failed, exc)
        else:
            if not self.cancelled:
                self._safe_emit(self.signals.succeeded, result)
        finally:
            self._safe_emit(self.signals.finished)

    @staticmethod
    def _safe_emit(signal: Any, *args: Any) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:
            pass  # receiver already destroyed (application shutting down)
