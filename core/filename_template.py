"""User-friendly filename templates.

Users write templates such as ``{index} - {title}``; this module validates
them and converts them into yt-dlp output templates (``%(title)s.%(ext)s``).
The extension is always appended by the application and is always ``mp4``
after post-processing.
"""

from __future__ import annotations

import re

from utils.formatting import sanitize_filename

#: Supported placeholders and their yt-dlp equivalents (``None`` = filled in locally).
PLACEHOLDERS: dict[str, str | None] = {
    "index": None,
    "playlist": None,
    "title": "%(title)s",
    "id": "%(id)s",
    "uploader": "%(uploader|Unknown)s",
    "date": "%(upload_date>%Y-%m-%d|unknown-date)s",
}

PLACEHOLDER_HELP = "  ".join(f"{{{name}}}" for name in PLACEHOLDERS)

_TOKEN = re.compile(r"\{(\w+)\}")
_SAMPLE = {
    "index": "01",
    "playlist": "My Playlist",
    "title": "Amazing Video Title",
    "id": "dQw4w9WgXcQ",
    "uploader": "Channel Name",
    "date": "2025-01-31",
}


class TemplateError(ValueError):
    """Raised when a filename template is invalid."""


def validate_template(template: str) -> None:
    """Raise :class:`TemplateError` if *template* cannot be used."""
    text = template.strip()
    if not text:
        raise TemplateError("The filename format cannot be empty.")
    if any(sep in text for sep in ("/", "\\")):
        raise TemplateError("The filename format cannot contain folder separators.")
    tokens = _TOKEN.findall(text)
    unknown = sorted({t for t in tokens if t not in PLACEHOLDERS})
    if unknown:
        raise TemplateError(f"Unknown placeholder(s): {', '.join('{' + t + '}' for t in unknown)}")
    if not {"title", "id", "index"} & set(tokens):
        raise TemplateError("Include {title}, {id} or {index} so filenames are unique.")


def build_outtmpl(template: str, *, index: int, total: int, playlist_title: str) -> str:
    """Convert a user template into a yt-dlp output template."""
    validate_template(template)
    width = max(2, len(str(max(total, 1))))
    escaped = template.strip().replace("%", "%%")

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key == "index":
            return f"{index:0{width}d}"
        if key == "playlist":
            return sanitize_filename(playlist_title).replace("%", "%%")
        return PLACEHOLDERS[key] or ""

    return _TOKEN.sub(substitute, escaped) + ".%(ext)s"


def preview(template: str) -> str:
    """Render a template with sample values for the Settings dialog."""
    validate_template(template)
    return _TOKEN.sub(lambda m: _SAMPLE[m.group(1)], template.strip()) + ".mp4"
