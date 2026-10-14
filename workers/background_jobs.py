"""Factories for the application's background tasks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from core.ffmpeg import FFmpegInfo, FFmpegLocator
from core.playlist_parser import PlaylistParser
from core.size_estimator import SizeEstimate, estimate_video
from models.video import PlaylistInfo
from utils.logger import get_logger
from workers.task import BackgroundTask

log = get_logger("jobs")


def playlist_load_task(url: str) -> BackgroundTask:
    """Load a playlist. ``succeeded`` delivers a :class:`PlaylistInfo`."""

    def run(_: BackgroundTask) -> PlaylistInfo:
        return PlaylistParser().parse(url)

    return BackgroundTask(run, name="playlist-loader")


def ffmpeg_detect_task(custom_path: str | None) -> BackgroundTask:
    """Detect FFmpeg. ``succeeded`` delivers ``FFmpegInfo | None``."""

    def run(_: BackgroundTask) -> FFmpegInfo | None:
        return FFmpegLocator(custom_path or None).locate()

    return BackgroundTask(run, name="ffmpeg-detect")


def size_estimate_task(
    jobs: list[tuple[int, str]],
    max_height: int | None,
    prefer_h264: bool,
    parallelism: int = 4,
) -> BackgroundTask:
    """Estimate sizes for ``(row, url)`` pairs.

    ``progress`` delivers ``(row, SizeEstimate)`` for each video as it
    completes; ``succeeded`` delivers the number of videos estimated.
    """

    def run(task: BackgroundTask) -> int:
        done = 0
        with ThreadPoolExecutor(max_workers=parallelism, thread_name_prefix="estimate") as pool:
            futures = {
                pool.submit(estimate_video, url, max_height, prefer_h264): row
                for row, url in jobs
            }
            for future in as_completed(futures):
                if task.cancelled:
                    pool.shutdown(wait=False, cancel_futures=True)
                    break
                row = futures[future]
                try:
                    estimate = future.result()
                except Exception as exc:  # noqa: BLE001 - an estimate is best effort
                    log.debug("Size estimate failed for row %d: %s", row, exc)
                    estimate = SizeEstimate(None, None)
                done += 1
                task.report((row, estimate))
        return done

    return BackgroundTask(run, name="size-estimator")
