"""Download worker: runs one video download on a ``QThreadPool`` thread.

The worker owns the retry policy: transient errors (network, rate limits,
unknown) are retried with exponential back-off up to the configured count;
permanent errors (private, removed, age-restricted, region-blocked, disk
full …) fail immediately with a friendly message.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from config.constants import MIN_FREE_SPACE_BYTES
from core.downloader import (
    DownloadControl,
    DownloadInterrupted,
    DownloadRequest,
    InterruptReason,
    ProgressSnapshot,
    VideoDownloader,
)
from core.errors import ErrorInfo, ErrorKind, classify_error
from models.video import DownloadStatus
from utils.disk import free_space
from utils.logger import get_logger

log = get_logger("worker")


class WorkerOutcome(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class DownloadJob:
    """Everything needed to download one playlist entry."""

    row: int
    url: str
    title: str
    outtmpl: str


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    """Settings shared by all jobs of one download session."""

    output_dir: Path
    ffmpeg_location: str
    max_height: int | None
    prefer_h264: bool
    retry_count: int


class DownloadWorkerSignals(QObject):
    progress = Signal(int, object)        # row, ProgressSnapshot
    status = Signal(int, str, str)        # row, DownloadStatus value, message
    finished = Signal(int, str, object)   # row, WorkerOutcome value, payload


class DownloadWorker(QRunnable):
    """Downloads one video with retries; communicates only through signals.

    Payload of ``finished`` by outcome:

    * ``completed`` → :class:`core.downloader.DownloadResult`
    * ``failed``    → :class:`core.errors.ErrorInfo`
    * ``paused``    → ``list[Path]`` of partial files kept for resuming
    * ``cancelled`` → ``None``
    """

    def __init__(self, job: DownloadJob, config: WorkerConfig) -> None:
        super().__init__()
        self.setAutoDelete(False)  # lifetime is managed by DownloadManager
        self.job = job
        self.config = config
        self.control = DownloadControl()
        self.signals = DownloadWorkerSignals()

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        try:
            self._run()
        except Exception as exc:  # noqa: BLE001 - last line of defence
            log.exception("Unexpected error while downloading “%s”", self.job.title)
            self._finish(WorkerOutcome.FAILED, classify_error(exc))

    def _run(self) -> None:
        job, cfg = self.job, self.config
        attempts = cfg.retry_count + 1

        for attempt in range(1, attempts + 1):
            if self._handle_interrupt_before_start():
                return

            space = free_space(cfg.output_dir)
            if space is not None and space < MIN_FREE_SPACE_BYTES:
                self._finish(
                    WorkerOutcome.FAILED,
                    ErrorInfo(ErrorKind.DISK_FULL, "Not enough free disk space to continue downloading."),
                )
                return

            self._status(DownloadStatus.FETCHING, "Fetching video information…")
            downloader = VideoDownloader(
                DownloadRequest(
                    url=job.url,
                    output_dir=cfg.output_dir,
                    outtmpl=job.outtmpl,
                    ffmpeg_location=cfg.ffmpeg_location,
                    max_height=cfg.max_height,
                    prefer_h264=cfg.prefer_h264,
                ),
                self.control,
                self._on_progress,
            )
            try:
                result = downloader.download()
            except DownloadInterrupted as interrupt:
                self._handle_interrupt(interrupt.reason, downloader)
                return
            except Exception as exc:  # noqa: BLE001 - classified below
                error = classify_error(exc)
                log.debug("Attempt %d for “%s” failed: %s", attempt, job.title, exc, exc_info=True)
                if error.retryable and attempt < attempts:
                    delay = min(60, 3 * 2 ** (attempt - 1))
                    if error.kind is ErrorKind.RATE_LIMITED:
                        delay = max(delay, 30)
                    log.warning("“%s”: %s Retrying in %ds (%d/%d)",
                                job.title, error.message, delay, attempt, cfg.retry_count)
                    self._status(DownloadStatus.RETRYING,
                                 f"{error.message} Retry {attempt}/{cfg.retry_count} in {delay}s")
                    try:
                        self.control.sleep(delay)
                    except DownloadInterrupted as interrupt:
                        self._handle_interrupt(interrupt.reason, downloader)
                        return
                    continue
                log.error("Failed: “%s” — %s%s", job.title, error.message,
                          f" ({error.detail})" if error.detail and error.detail != error.message else "")
                self._finish(WorkerOutcome.FAILED, error)
                return
            else:
                if result.already_existed:
                    log.info("Already downloaded: %s", result.filepath.name)
                else:
                    log.info("Completed: %s", result.filepath.name)
                self._finish(WorkerOutcome.COMPLETED, result)
                return

    # -------------------------------------------------------------- helpers
    def _handle_interrupt_before_start(self) -> bool:
        if self.control.cancelled:
            self._finish(WorkerOutcome.CANCELLED, None)
            return True
        if self.control.paused:
            self._finish(WorkerOutcome.PAUSED, [])
            return True
        return False

    def _handle_interrupt(self, reason: InterruptReason, downloader: VideoDownloader) -> None:
        if reason is InterruptReason.CANCELLED:
            downloader.cleanup_partials()
            log.info("Cancelled: %s", self.job.title)
            self._finish(WorkerOutcome.CANCELLED, None)
        else:
            log.info("Paused: %s", self.job.title)
            self._finish(WorkerOutcome.PAUSED, downloader.partial_files)

    def _on_progress(self, snapshot: ProgressSnapshot) -> None:
        self._emit(self.signals.progress, self.job.row, snapshot)

    def _status(self, status: DownloadStatus, message: str = "") -> None:
        self._emit(self.signals.status, self.job.row, status.value, message)

    def _finish(self, outcome: WorkerOutcome, payload: object) -> None:
        self._emit(self.signals.finished, self.job.row, outcome.value, payload)

    @staticmethod
    def _emit(signal: Signal, *args: object) -> None:  # type: ignore[valid-type]
        try:
            signal.emit(*args)  # type: ignore[attr-defined]
        except RuntimeError:
            pass  # GUI already gone
