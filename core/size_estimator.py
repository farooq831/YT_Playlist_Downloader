"""Estimate the download size of a video for a given quality.

This runs yt-dlp's format selection without downloading, using exactly the
same selector as the real download, so the estimate matches what will be
fetched.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.downloader import describe_resolution, expected_sizes
from core.format_selector import build_format_selector, build_format_sort
from core.ytdlp_common import base_options, extract_with_fallback
from utils.logger import get_logger

log = get_logger("estimator")


@dataclass(frozen=True, slots=True)
class SizeEstimate:
    size: int | None
    resolution: str | None


def estimate_video(
    url: str,
    max_height: int | None,
    prefer_h264: bool = True,
) -> SizeEstimate:
    """Return the expected size and resolution of *url* (``None`` if unknown)."""
    extra = {
        "format": build_format_selector(max_height),
        "format_sort": build_format_sort(max_height, prefer_h264),
        "skip_download": True,
        "noplaylist": True,
        "no_warnings": True,
    }
    info = extract_with_fallback(lambda clients: base_options(log, player_clients=clients) | extra,
                                 url, download=False, logger=log)
    if not info:
        return SizeEstimate(None, None)
    sizes = expected_sizes(info)
    total = sum(sizes) if sizes and all(sizes) else None
    return SizeEstimate(total, describe_resolution(info))
