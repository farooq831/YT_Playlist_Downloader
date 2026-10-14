"""Human-friendly formatting helpers (sizes, speeds, durations, filenames)."""

from __future__ import annotations

import re

_UNITS: tuple[str, ...] = ("B", "KB", "MB", "GB", "TB")
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def format_bytes(value: float | int | None, precision: int = 1) -> str:
    """Format a byte count, e.g. ``1536`` -> ``"1.5 KB"``."""
    if value is None or value < 0:
        return "—"
    size = float(value)
    unit = 0
    while size >= 1024 and unit < len(_UNITS) - 1:
        size /= 1024
        unit += 1
    if unit == 0:
        return f"{size:.0f} {_UNITS[unit]}"
    return f"{size:.{precision}f} {_UNITS[unit]}"


def format_speed(bytes_per_second: float | None) -> str:
    """Format a transfer rate, e.g. ``"3.2 MB/s"``."""
    if not bytes_per_second or bytes_per_second <= 0:
        return "—"
    return f"{format_bytes(bytes_per_second)}/s"


def format_duration(seconds: float | int | None) -> str:
    """Format seconds as ``h:mm:ss`` or ``m:ss``."""
    if seconds is None or seconds < 0:
        return "--:--"
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_eta(seconds: float | int | None) -> str:
    """Format a remaining-time estimate."""
    if seconds is None or seconds < 0 or seconds > 7 * 24 * 3600:
        return "—"
    return format_duration(seconds)


def sanitize_filename(name: str, max_length: int = 120) -> str:
    """Make *name* safe to use as a file or folder name on every platform."""
    cleaned = _INVALID_FILENAME_CHARS.sub("_", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    if cleaned.upper() in _WINDOWS_RESERVED:
        cleaned = f"_{cleaned}"
    cleaned = cleaned[:max_length].rstrip(" .")
    return cleaned or "untitled"
