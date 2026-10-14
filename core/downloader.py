"""Single-video download engine built on the yt-dlp Python API.

:class:`VideoDownloader` downloads exactly one video to an MP4 file. It is
GUI-agnostic and thread-safe per instance; the Qt worker in
``workers.download_worker`` wraps it with retries and signals.

Pause / cancel
    yt-dlp has no native pause. A :class:`DownloadControl` flag is checked
    from inside the progress hook; when set, the hook raises
    :class:`DownloadInterrupted`, which aborts yt-dlp immediately while
    leaving the ``.part`` file on disk. Because ``continuedl`` is enabled,
    the next attempt continues from where it stopped (HTTP range requests),
    which also makes interrupted downloads resumable across app restarts.

MP4 guarantee
    * the format selector only produces video+audio combinations,
    * ``merge_output_format="mp4"`` makes FFmpeg merge into MP4 (never MKV),
    * ``FFmpegVideoConvertor`` converts any non-MP4 single-file fallback,
    * the final path is verified to end in ``.mp4``.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from core.format_selector import build_format_selector, build_format_sort
from core.ytdlp_common import PLAYER_CLIENTS, base_options, extract_with_fallback
from utils.logger import get_logger

log = get_logger("downloader")


class InterruptReason(StrEnum):
    PAUSED = "paused"
    CANCELLED = "cancelled"


class DownloadInterrupted(Exception):
    """Raised from the progress hook to stop yt-dlp on pause/cancel.

    Deliberately not an ``OSError``/``DownloadError`` subclass so that yt-dlp
    does not swallow or re-wrap it.
    """

    def __init__(self, reason: InterruptReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class DownloadControl:
    """Thread-safe pause/cancel flags shared between GUI and worker."""

    def __init__(self) -> None:
        self._paused = threading.Event()
        self._cancelled = threading.Event()

    def request_pause(self) -> None:
        self._paused.set()

    def request_cancel(self) -> None:
        self._cancelled.set()

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def check(self) -> None:
        """Raise :class:`DownloadInterrupted` if pause or cancel was requested."""
        if self._cancelled.is_set():
            raise DownloadInterrupted(InterruptReason.CANCELLED)
        if self._paused.is_set():
            raise DownloadInterrupted(InterruptReason.PAUSED)

    def sleep(self, seconds: float) -> None:
        """Interruptible sleep used for retry back-off."""
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            self.check()
            self._cancelled.wait(min(0.2, remaining))
        self.check()


class Phase(StrEnum):
    STARTING = "starting"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"


@dataclass(slots=True)
class DownloadRequest:
    url: str
    output_dir: Path
    outtmpl: str
    ffmpeg_location: str
    max_height: int | None = None
    prefer_h264: bool = True
    network_retries: int = 10


@dataclass(slots=True)
class ProgressSnapshot:
    phase: Phase
    downloaded: int = 0
    total: int | None = None
    speed: float | None = None
    eta: float | None = None
    percent: float = 0.0
    resolution: str | None = None
    message: str = ""


@dataclass(slots=True)
class DownloadResult:
    filepath: Path
    resolution: str | None
    filesize: int | None
    already_existed: bool


def describe_resolution(info: dict[str, Any]) -> str | None:
    """Return e.g. ``"1080p"`` for the video stream described by *info*."""
    for fmt in info.get("requested_formats") or [info]:
        if fmt.get("vcodec") not in (None, "none") and fmt.get("height"):
            fps = fmt.get("fps")
            suffix = f"{int(fps)}" if fps and fps > 30 else ""
            return f"{fmt['height']}p{suffix}"
    height = info.get("height")
    return f"{height}p" if height else None


def expected_sizes(info: dict[str, Any]) -> list[int]:
    """Sizes of the streams yt-dlp will download for *info* (0 = unknown)."""
    formats = info.get("requested_formats") or [info]
    return [int(f.get("filesize") or f.get("filesize_approx") or 0) for f in formats]


class _ProgressAggregator:
    """Combines the progress of the separate video and audio downloads."""

    def __init__(self) -> None:
        self.streams: dict[str, tuple[int, int]] = {}
        self.sizes: list[int] | None = None
        self.resolution: str | None = None

    def prime(self, info: dict[str, Any]) -> None:
        if self.sizes is None:
            self.sizes = expected_sizes(info)
            self.resolution = describe_resolution(info)

    def update(self, key: str, downloaded: int, total: int) -> None:
        self.streams[key] = (downloaded, max(total, downloaded))

    def totals(self) -> tuple[int, int | None]:
        done = sum(d for d, _ in self.streams.values())
        known = sum(t for _, t in self.streams.values())
        sizes = self.sizes or []
        # Streams are downloaded in order; add sizes of those not started yet.
        pending = sum(sizes[len(self.streams):]) if len(self.streams) < len(sizes) else 0
        if pending == 0 and len(self.streams) < len(sizes):
            return done, None
        total = known + pending
        return done, total or None


class VideoDownloader:
    """Downloads one video as a merged MP4 file."""

    PROGRESS_INTERVAL = 0.25  # seconds between progress callbacks

    def __init__(
        self,
        request: DownloadRequest,
        control: DownloadControl,
        on_progress: Callable[[ProgressSnapshot], None],
    ) -> None:
        self._request = request
        self._control = control
        self._on_progress = on_progress
        self._aggregator = _ProgressAggregator()
        self._last_emit = 0.0
        self._saw_download = False
        self._partial_files: set[Path] = set()

    # ---------------------------------------------------------------- options
    def build_options(self, player_clients: tuple[str, ...] = PLAYER_CLIENTS) -> dict[str, Any]:
        req = self._request
        self._aggregator = _ProgressAggregator()  # fresh totals for every attempt
        options = base_options(log, player_clients=player_clients) | {
            "format": build_format_selector(req.max_height),
            "format_sort": build_format_sort(req.max_height, req.prefer_h264),
            "merge_output_format": "mp4",
            "final_ext": "mp4",
            "postprocessors": [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}],
            "ffmpeg_location": req.ffmpeg_location,
            "paths": {"home": str(req.output_dir)},
            "outtmpl": {"default": req.outtmpl},
            "noplaylist": True,
            "continuedl": True,
            "nopart": False,
            "overwrites": False,
            "keepvideo": False,
            "updatetime": False,
            "windowsfilenames": True,
            "trim_file_name": 150,
            "retries": req.network_retries,
            "fragment_retries": req.network_retries,
            "file_access_retries": 5,
            "retry_sleep_functions": {"http": lambda n: min(2 ** n, 30), "fragment": lambda n: min(2 ** n, 30)},
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._postprocessor_hook],
        }
        return options

    # -------------------------------------------------------------- execution
    def download(self) -> DownloadResult:
        """Download the video. Raises on failure or interruption."""
        self._control.check()
        self._emit(ProgressSnapshot(Phase.STARTING, message="Fetching video information…"), force=True)
        info = extract_with_fallback(self.build_options, self._request.url, download=True, logger=log)
        if not info:
            raise RuntimeError("yt-dlp returned no information for this video")

        path = self._final_path(info)
        if path is None or not path.is_file():
            raise RuntimeError("The download finished but the output file could not be found")
        if path.suffix.lower() != ".mp4":
            raise RuntimeError(f"Unexpected output format '{path.suffix}' — expected MP4")

        size = path.stat().st_size
        return DownloadResult(
            filepath=path,
            resolution=describe_resolution(info),
            filesize=size,
            already_existed=not self._saw_download,
        )

    def cleanup_partials(self) -> None:
        """Delete partial files left behind by a cancelled download."""
        for path in list(self._partial_files):
            for candidate in (path, Path(f"{path}.ytdl"), Path(str(path).removesuffix(".part") + ".ytdl")):
                try:
                    if candidate.suffix in {".part", ".ytdl"} and candidate.is_file():
                        candidate.unlink()
                        log.debug("Removed partial file %s", candidate)
                except OSError as exc:
                    log.debug("Could not remove %s: %s", candidate, exc)

    @property
    def partial_files(self) -> list[Path]:
        return sorted(self._partial_files)

    # ------------------------------------------------------------------ hooks
    def _progress_hook(self, data: dict[str, Any]) -> None:
        self._control.check()  # raises to abort on pause/cancel

        info = data.get("info_dict") or {}
        self._aggregator.prime(info)
        status = data.get("status")
        key = str(data.get("filename") or "")
        tmp = data.get("tmpfilename")
        if tmp:
            self._partial_files.add(Path(tmp))

        if status == "downloading":
            self._saw_download = True
            downloaded = int(data.get("downloaded_bytes") or 0)
            total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
            self._aggregator.update(key, downloaded, total)
            self._emit_progress(data.get("speed"))
        elif status == "finished":
            total = int(data.get("total_bytes") or data.get("downloaded_bytes") or 0)
            self._aggregator.update(key, total, total)
            self._emit_progress(None, force=True)

    def _postprocessor_hook(self, data: dict[str, Any]) -> None:
        if data.get("status") != "started":
            return
        name = data.get("postprocessor") or ""
        messages = {
            "Merger": "Merging video and audio into MP4…",
            "VideoConvertor": "Converting to MP4…",
            "MoveFiles": "Finalizing…",
        }
        message = messages.get(name)
        if message:
            done, total = self._aggregator.totals()
            self._emit(
                ProgressSnapshot(
                    Phase.PROCESSING, downloaded=done, total=total, percent=100.0,
                    resolution=self._aggregator.resolution, message=message,
                ),
                force=True,
            )

    # ---------------------------------------------------------------- helpers
    def _emit_progress(self, speed: float | None, force: bool = False) -> None:
        done, total = self._aggregator.totals()
        percent = min(100.0, done * 100.0 / total) if total else 0.0
        eta = (total - done) / speed if speed and total else None
        self._emit(
            ProgressSnapshot(
                Phase.DOWNLOADING, downloaded=done, total=total, speed=speed, eta=eta,
                percent=percent, resolution=self._aggregator.resolution,
            ),
            force=force,
        )

    def _emit(self, snapshot: ProgressSnapshot, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_emit >= self.PROGRESS_INTERVAL:
            self._last_emit = now
            self._on_progress(snapshot)

    @staticmethod
    def _final_path(info: dict[str, Any]) -> Path | None:
        candidates: list[str] = []
        for entry in info.get("requested_downloads") or []:
            candidates += [entry.get("filepath"), entry.get("_filename")]
        candidates += [info.get("filepath"), info.get("_filename")]
        paths = [Path(c) for c in candidates if c]
        for path in paths:
            if path.suffix.lower() == ".mp4" and path.is_file():
                return path
        for path in paths:
            mp4 = path.with_suffix(".mp4")
            if mp4.is_file():
                return mp4
        return paths[0] if paths else None
