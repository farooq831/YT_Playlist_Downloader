"""Shared yt-dlp plumbing: logging bridge, base options and client fallback.

No sign-in or cookies are needed. YouTube's default "web" client is often
blocked with "Sign in to confirm you're not a bot", but the *embedded
player* client is not, and it still offers every quality (up to 4K). The
app therefore asks yt-dlp to use these YouTube clients:

1. ``web_embedded`` (full quality), with ``mweb`` and ``android`` merged in
   for videos that can't be embedded;
2. if YouTube still blocks the video, ``android`` alone, which works
   almost everywhere but is limited to 360p.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from core.errors import ErrorKind, classify_error
from core.js_runtime import js_runtimes

PLAYER_CLIENTS: tuple[str, ...] = ("web_embedded", "mweb", "android")
FALLBACK_CLIENTS: tuple[str, ...] = ("android",)

# yt-dlp messages worth showing in the in-app log at INFO level.
_INFO_TAGS = ("[Merger]", "[VideoConvertor]", "[VideoRemuxer]", "has already been downloaded")


class YtDlpLogger:
    """Routes yt-dlp output into the application's ``logging`` tree.

    yt-dlp sends regular progress chatter through ``debug``. Errors are also
    raised as exceptions and reported by the caller, and yt-dlp's technical
    warnings mean nothing to end users, so both only go to the log file.
    """

    def __init__(self, logger: logging.Logger, prefix: str = "") -> None:
        self._log = logger
        self._prefix = f"{prefix}: " if prefix else ""

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] "):
            self._log.debug(msg[8:])
        elif any(tag in msg for tag in _INFO_TAGS):
            self._log.info("%s%s", self._prefix, msg)
        else:
            self._log.debug(msg)

    def info(self, msg: str) -> None:
        self._log.debug(msg)

    def warning(self, msg: str) -> None:
        self._log.debug("%s%s", self._prefix, msg.removeprefix("WARNING: "))

    def error(self, msg: str) -> None:
        self._log.debug(msg)


def base_options(
    logger: logging.Logger,
    prefix: str = "",
    player_clients: tuple[str, ...] = PLAYER_CLIENTS,
) -> dict[str, Any]:
    """Options common to every yt-dlp instance created by the application."""
    options: dict[str, Any] = {
        "logger": YtDlpLogger(logger, prefix),
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "no_color": True,
        "socket_timeout": 30,
        "extractor_retries": 3,
        "extractor_args": {"youtube": {"player_client": list(player_clients)}},
    }
    runtimes = js_runtimes()
    if runtimes:
        options["js_runtimes"] = runtimes
    return options


def is_blocked(error: BaseException) -> bool:
    """True when YouTube refused the request or offered no usable format."""
    return classify_error(error).kind in {ErrorKind.SIGN_IN_REQUIRED, ErrorKind.FORMAT_UNAVAILABLE}


def extract_with_fallback(
    options_for: Callable[[tuple[str, ...]], dict[str, Any]],
    url: str,
    *,
    download: bool,
    logger: logging.Logger,
) -> dict[str, Any] | None:
    """Run ``extract_info`` with the main clients, then the fallback client.

    *options_for* builds the yt-dlp options for a given client list. Errors
    other than "blocked" (and pause/cancel interruptions) are re-raised
    immediately.
    """
    attempts = (PLAYER_CLIENTS, FALLBACK_CLIENTS)
    for number, clients in enumerate(attempts, start=1):
        try:
            with YoutubeDL(options_for(clients)) as ydl:
                return ydl.extract_info(url, download=download)
        except DownloadError as exc:
            if number == len(attempts) or not is_blocked(exc):
                raise
            logger.debug("Clients %s blocked for %s: %s", clients, url, exc)
            if download:
                logger.info("YouTube limited this video; retrying with a compatibility mode "
                            "(quality may be lower)…")
    return None
