"""Application-wide constants.

Everything that is "fixed" about the application (names, quality presets,
filename presets, limits) lives here so that the rest of the code base never
hard-codes magic values.
"""

from __future__ import annotations

from typing import Final

APP_NAME: Final[str] = "YT Playlist Downloader"
APP_ID: Final[str] = "YTPlaylistDownloader"
APP_VERSION: Final[str] = "1.0.0"
ORG_NAME: Final[str] = "YTPD"
AUTHOR: Final[str] = "Muhammad Farooq"
COPYRIGHT_YEAR: Final[str] = "2026"
COPYRIGHT: Final[str] = f"© {COPYRIGHT_YEAR} {AUTHOR}. All rights reserved."

#: (label shown in the UI, maximum height in pixels or ``None`` for "best")
QUALITY_OPTIONS: Final[tuple[tuple[str, int | None], ...]] = (
    ("Best Available", None),
    ("2160p (4K)", 2160),
    ("1440p", 1440),
    ("1080p", 1080),
    ("720p", 720),
    ("480p", 480),
    ("360p", 360),
)
DEFAULT_QUALITY: Final[str] = QUALITY_OPTIONS[0][0]

#: Filename presets. Placeholders are documented in ``core.filename_template``.
FILENAME_PRESETS: Final[tuple[str, ...]] = (
    "{index} - {title}",
    "{title}",
    "{title} [{id}]",
    "{index} - {uploader} - {title}",
    "{playlist} - {index} - {title}",
)

THEMES: Final[tuple[str, ...]] = ("dark", "light")

MAX_CONCURRENT_LIMIT: Final[int] = 8
MAX_RETRY_LIMIT: Final[int] = 10

#: Refuse to start a download when less than this is free on the target drive.
MIN_FREE_SPACE_BYTES: Final[int] = 200 * 1024 * 1024

#: Playlists up to this size get their download size estimated automatically.
AUTO_ESTIMATE_LIMIT: Final[int] = 50

YOUTUBE_WATCH_URL: Final[str] = "https://www.youtube.com/watch?v={id}"
THUMBNAIL_URL: Final[str] = "https://i.ytimg.com/vi/{id}/mqdefault.jpg"
THUMBNAIL_URL_HQ: Final[str] = "https://i.ytimg.com/vi/{id}/hqdefault.jpg"

USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
