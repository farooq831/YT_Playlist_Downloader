"""Download queue orchestration.

The :class:`DownloadManager` owns the job queue and a ``QThreadPool``. It
starts at most *N* :class:`DownloadWorker` instances at a time, re-queues
paused jobs at the front so they resume first, and reports a summary once
the queue drains. All public methods must be called from the GUI thread;
worker signals arrive here through queued connections.
"""

from __future__ import annotations

from collections import Counter, deque
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QObject, QThreadPool, Signal, Slot

from models.video import DownloadStatus
from utils.logger import get_logger
from workers.download_worker import DownloadJob, DownloadWorker, WorkerConfig, WorkerOutcome

log = get_logger("manager")


class ManagerState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"


class DownloadManager(QObject):
    """Queue + thread pool for video downloads."""

    progress = Signal(int, object)          # row, ProgressSnapshot
    statusChanged = Signal(int, str, str)   # row, DownloadStatus value, message
    itemFinished = Signal(int, str, object)  # row, WorkerOutcome value, payload
    stateChanged = Signal(str)              # ManagerState value
    queueFinished = Signal(dict)            # {"completed": n, "failed": n, "cancelled": n}

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool(self)
        self._max_concurrent = 2
        self._pool.setMaxThreadCount(self._max_concurrent)
        self._queue: deque[DownloadJob] = deque()
        self._active: dict[int, DownloadWorker] = {}
        self._paused_partials: dict[int, list[Path]] = {}
        self._config: WorkerConfig | None = None
        self._state = ManagerState.IDLE
        self._summary: Counter[str] = Counter()

    # ------------------------------------------------------------- properties
    @property
    def state(self) -> ManagerState:
        return self._state

    @property
    def is_busy(self) -> bool:
        return self._state is not ManagerState.IDLE

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def queued_count(self) -> int:
        return len(self._queue)

    # ---------------------------------------------------------------- control
    def set_max_concurrent(self, value: int) -> None:
        self._max_concurrent = max(1, value)
        self._pool.setMaxThreadCount(self._max_concurrent)
        if self._state is ManagerState.RUNNING:
            self._dispatch()

    def start(self, jobs: list[DownloadJob], config: WorkerConfig) -> None:
        if self.is_busy:
            raise RuntimeError("A download session is already running")
        self._config = config
        self._queue = deque(jobs)
        self._summary.clear()
        self._paused_partials.clear()
        for job in jobs:
            self.statusChanged.emit(job.row, DownloadStatus.QUEUED.value, "Waiting in queue")
        log.info("Starting download of %d video(s) — %d at a time", len(jobs), self._max_concurrent)
        self._set_state(ManagerState.RUNNING)
        self._dispatch()

    def pause(self) -> None:
        if self._state is not ManagerState.RUNNING:
            return
        log.info("Pausing downloads…")
        self._set_state(ManagerState.PAUSED)
        for worker in self._active.values():
            worker.control.request_pause()

    def resume(self, config: WorkerConfig | None = None, retry_jobs: list[DownloadJob] | None = None) -> None:
        """Continue a paused session.

        *config* replaces the session settings (e.g. a newly detected FFmpeg);
        *retry_jobs* are failed jobs to run again first.
        """
        if self._state is not ManagerState.PAUSED:
            return
        if config is not None:
            self._config = config
        for job in reversed(retry_jobs or []):
            self._queue.appendleft(job)
            if self._summary[WorkerOutcome.FAILED.value] > 0:
                self._summary[WorkerOutcome.FAILED.value] -= 1
        log.info("Resuming downloads%s", f" — retrying {len(retry_jobs)} failed video(s)" if retry_jobs else "")
        self._set_state(ManagerState.RUNNING)
        for job in self._queue:
            self.statusChanged.emit(job.row, DownloadStatus.QUEUED.value, "Waiting in queue")
        self._dispatch()

    def cancel(self) -> None:
        if self._state in (ManagerState.IDLE, ManagerState.STOPPING):
            return
        log.info("Cancelling downloads…")
        self._set_state(ManagerState.STOPPING)
        for job in self._queue:
            self._discard_partials(job.row)
            self._summary[WorkerOutcome.CANCELLED.value] += 1
            self.itemFinished.emit(job.row, WorkerOutcome.CANCELLED.value, None)
        self._queue.clear()
        for worker in self._active.values():
            worker.control.request_cancel()
        if not self._active:
            self._finish_session()

    def shutdown(self, timeout_ms: int = 5000) -> None:
        """Stop everything for application exit, keeping partial files."""
        self._queue.clear()
        for worker in self._active.values():
            worker.control.request_pause()
        self._pool.waitForDone(timeout_ms)

    # --------------------------------------------------------------- internal
    def _dispatch(self) -> None:
        assert self._config is not None
        while self._state is ManagerState.RUNNING and self._queue and len(self._active) < self._max_concurrent:
            job = self._queue.popleft()
            self._paused_partials.pop(job.row, None)
            worker = DownloadWorker(job, self._config)
            worker.signals.progress.connect(self.progress)
            worker.signals.status.connect(self.statusChanged)
            worker.signals.finished.connect(self._on_worker_finished)
            self._active[job.row] = worker
            self._pool.start(worker)
        if self._state is ManagerState.RUNNING and not self._queue and not self._active:
            self._finish_session()

    @Slot(int, str, object)
    def _on_worker_finished(self, row: int, outcome: str, payload: object) -> None:
        worker = self._active.pop(row, None)
        if worker is None:
            return

        if outcome == WorkerOutcome.PAUSED.value:
            if self._state is ManagerState.STOPPING:
                # Pause raced with cancel: treat as cancelled.
                self._paused_partials[row] = list(payload or [])  # type: ignore[arg-type]
                self._discard_partials(row)
                outcome, payload = WorkerOutcome.CANCELLED.value, None
            else:
                self._paused_partials[row] = list(payload or [])  # type: ignore[arg-type]
                self._queue.appendleft(worker.job)
                self.itemFinished.emit(row, outcome, payload)
                self._after_worker()
                return

        self._summary[outcome] += 1
        self.itemFinished.emit(row, outcome, payload)
        self._after_worker()

    def _after_worker(self) -> None:
        if self._state is ManagerState.STOPPING and not self._active:
            self._finish_session()
        elif self._state is ManagerState.RUNNING:
            self._dispatch()

    def _finish_session(self) -> None:
        summary = {key.value: self._summary.get(key.value, 0)
                   for key in (WorkerOutcome.COMPLETED, WorkerOutcome.FAILED, WorkerOutcome.CANCELLED)}
        self._queue.clear()
        self._paused_partials.clear()
        self._set_state(ManagerState.IDLE)
        log.info("Download session finished — %d completed, %d failed, %d cancelled",
                 summary["completed"], summary["failed"], summary["cancelled"])
        self.queueFinished.emit(summary)

    def _discard_partials(self, row: int) -> None:
        for path in self._paused_partials.pop(row, []):
            for candidate in (path, Path(f"{path}.ytdl")):
                try:
                    if candidate.is_file():
                        candidate.unlink()
                except OSError:
                    pass

    def _set_state(self, state: ManagerState) -> None:
        if state is not self._state:
            self._state = state
            self.stateChanged.emit(state.value)
