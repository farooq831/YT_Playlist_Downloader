"""Error classification.

yt-dlp reports almost every problem as a ``DownloadError`` whose message is
free text. This module turns those messages (and plain Python exceptions)
into a small set of :class:`ErrorKind` values with user-friendly messages and
a flag telling the retry logic whether trying again could possibly help.
"""

from __future__ import annotations

import errno
import re
from dataclasses import dataclass
from enum import StrEnum

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_PREFIX = re.compile(r"^(?:ERROR:\s*)?(?:\[[\w:]+\]\s*)?(?:[\w-]{6,}:\s*)?", re.IGNORECASE)


class ErrorKind(StrEnum):
    INVALID_URL = "invalid_url"
    PRIVATE = "private"
    AGE_RESTRICTED = "age_restricted"
    SIGN_IN_REQUIRED = "sign_in_required"
    MEMBERS_ONLY = "members_only"
    REMOVED = "removed"
    REGION_BLOCKED = "region_blocked"
    LIVE_STREAM = "live_stream"
    NETWORK = "network"
    RATE_LIMITED = "rate_limited"
    DISK_FULL = "disk_full"
    PERMISSION = "permission"
    FFMPEG_MISSING = "ffmpeg_missing"
    FORMAT_UNAVAILABLE = "format_unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    """A classified error ready to be shown to the user."""

    kind: ErrorKind
    message: str
    detail: str = ""
    retryable: bool = False

    def __str__(self) -> str:
        return self.message


class AppError(Exception):
    """Exception carrying an :class:`ErrorInfo`."""

    def __init__(self, info: ErrorInfo) -> None:
        super().__init__(info.message)
        self.info = info


# (kind, substrings to look for in the lower-cased message, friendly text, retryable)
_RULES: tuple[tuple[ErrorKind, tuple[str, ...], str, bool], ...] = (
    (
        ErrorKind.DISK_FULL,
        ("no space left", "disk full", "not enough space on the disk", "[errno 28]", "errno 28"),
        "The disk is full. Free some space or choose another download folder.",
        False,
    ),
    (
        ErrorKind.FFMPEG_MISSING,
        ("ffmpeg is not installed", "ffprobe and ffmpeg not found", "ffmpeg not found",
         "you have requested merging of multiple formats but ffmpeg"),
        "FFmpeg is required to merge video and audio into MP4 but was not found.",
        False,
    ),
    (
        ErrorKind.PERMISSION,
        ("permission denied", "access is denied", "[errno 13]", "winerror 5"),
        "Permission denied while writing the file. Choose a different download folder.",
        False,
    ),
    (
        ErrorKind.AGE_RESTRICTED,
        ("confirm your age", "age-restricted", "age restricted", "inappropriate for some users"),
        "Age-restricted video. YouTube only shows it to signed-in adults, so it can't be downloaded.",
        False,
    ),
    (
        ErrorKind.MEMBERS_ONLY,
        ("members-only", "members only", "join this channel"),
        "Members-only video. It requires a channel membership.",
        False,
    ),
    (
        ErrorKind.PRIVATE,
        ("private video", "playlist is private", "this playlist does not exist",
         "the playlist does not exist", "private playlist"),
        "This content is private and can't be downloaded.",
        False,
    ),
    (
        ErrorKind.REGION_BLOCKED,
        ("not available in your country", "blocked it in your country", "geo restrict",
         "geo-restrict", "not made this video available in your country", "from your location"),
        "This video is not available in your region.",
        False,
    ),
    (
        ErrorKind.REMOVED,
        ("video unavailable", "has been removed", "no longer available", "account associated with this video has been terminated",
         "this video does not exist", "deleted video", "copyright claim", "incomplete youtube id",
         "is not a valid url", "video is unavailable"),
        "This video is unavailable or has been removed.",
        False,
    ),
    (
        ErrorKind.LIVE_STREAM,
        ("live event will begin", "premieres in", "this live event", "is_live", "is live now"),
        "This is an upcoming or ongoing live stream and cannot be downloaded yet.",
        False,
    ),
    (
        ErrorKind.SIGN_IN_REQUIRED,
        ("sign in to confirm you", "not a bot", "sign in to view", "login required", "use --cookies"),
        "YouTube is temporarily limiting downloads from your network. It will be retried automatically; "
        "if it keeps failing, wait a while or try another network.",
        True,
    ),
    (
        ErrorKind.RATE_LIMITED,
        ("http error 429", "too many requests"),
        "YouTube is rate-limiting requests. Waiting before retrying…",
        True,
    ),
    (
        ErrorKind.FORMAT_UNAVAILABLE,
        ("requested format is not available", "no video formats found"),
        "No downloadable MP4 video format was found for this video.",
        False,
    ),
    (
        ErrorKind.NETWORK,
        ("urlopen error", "timed out", "timeout", "connection reset", "connection aborted",
         "connection refused", "getaddrinfo", "name resolution", "network is unreachable",
         "remote end closed", "unable to download webpage", "unable to download video data",
         "incompleteread", "ssl", "http error 5", "http error 403", "broken pipe",
         "connectionerror", "max retries exceeded", "did not get any data blocks",
         "content too short", "transporterror", "errno 10054", "errno 10060", "errno 11001"),
        "Network error. The download will be retried.",
        True,
    ),
)


def _clean(text: str) -> str:
    text = _ANSI.sub("", text).strip()
    first_line = text.splitlines()[0] if text else ""
    return _PREFIX.sub("", first_line, count=1).strip() or first_line


def _collect_messages(exc: BaseException) -> str:
    """Concatenate the messages of *exc* and everything it wraps."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        exc_info = getattr(current, "exc_info", None)
        wrapped = exc_info[1] if isinstance(exc_info, tuple) and len(exc_info) > 1 else None
        current = wrapped or current.__cause__ or current.__context__
    return " | ".join(parts)


def classify_error(error: BaseException | str) -> ErrorInfo:
    """Map an exception or message to an :class:`ErrorInfo`."""
    if isinstance(error, AppError):
        return error.info

    if isinstance(error, BaseException):
        if isinstance(error, OSError) and error.errno == errno.ENOSPC:
            return ErrorInfo(ErrorKind.DISK_FULL, _RULES[0][2], str(error), False)
        haystack = _collect_messages(error)
        detail = _clean(str(error)) or type(error).__name__
    else:
        haystack = error
        detail = _clean(error)

    lowered = _ANSI.sub("", haystack).lower()
    for kind, needles, message, retryable in _RULES:
        if any(needle in lowered for needle in needles):
            return ErrorInfo(kind, message, detail, retryable)

    # Unknown errors get one more chance; they are often transient.
    return ErrorInfo(ErrorKind.UNKNOWN, detail or "An unknown error occurred.", detail, True)
