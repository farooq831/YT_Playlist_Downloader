"""Persistent user settings stored as JSON in the app-data directory."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from config.constants import (
    DEFAULT_QUALITY,
    FILENAME_PRESETS,
    MAX_CONCURRENT_LIMIT,
    MAX_RETRY_LIMIT,
    QUALITY_OPTIONS,
    THEMES,
)
from utils.logger import get_logger
from utils.paths import config_file, default_download_dir

log = get_logger("config")


@dataclass(slots=True)
class AppSettings:
    """All user-configurable options. Defaults are used for missing keys."""

    download_path: str = field(default_factory=lambda: str(default_download_dir()))
    max_concurrent_downloads: int = 2
    theme: str = "dark"
    retry_count: int = 3
    filename_format: str = FILENAME_PRESETS[0]
    quality: str = DEFAULT_QUALITY
    create_playlist_folder: bool = False
    prefer_h264: bool = True
    auto_estimate_size: bool = True
    ffmpeg_path: str = ""
    window_geometry: str = ""
    splitter_state: str = ""

    def validated(self) -> AppSettings:
        """Return a copy with every value clamped to a legal range."""
        quality_labels = {label for label, _ in QUALITY_OPTIONS}
        return replace(
            self,
            max_concurrent_downloads=min(max(1, self.max_concurrent_downloads), MAX_CONCURRENT_LIMIT),
            retry_count=min(max(0, self.retry_count), MAX_RETRY_LIMIT),
            theme=self.theme if self.theme in THEMES else "dark",
            quality=self.quality if self.quality in quality_labels else DEFAULT_QUALITY,
            filename_format=self.filename_format.strip() or FILENAME_PRESETS[0],
            download_path=self.download_path or str(default_download_dir()),
        )


def _coerce(value: Any, default: Any) -> Any:
    """Return *value* if it has the same type as *default*, else ``default``."""
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, int):
        return value if isinstance(value, int) and not isinstance(value, bool) else default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    return default


class ConfigManager:
    """Loads, validates and atomically saves :class:`AppSettings`."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or config_file()
        self._lock = threading.Lock()
        self._settings = AppSettings()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def settings(self) -> AppSettings:
        return self._settings

    def load(self) -> AppSettings:
        """Read the config file; fall back to defaults on any problem."""
        defaults = AppSettings()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("configuration root must be an object")
        except FileNotFoundError:
            log.debug("No configuration file yet, using defaults")
            raw = {}
        except (OSError, ValueError) as exc:
            log.warning("Configuration file is unreadable (%s); using defaults", exc)
            self._backup_corrupt_file()
            raw = {}

        values = {
            f.name: _coerce(raw.get(f.name, getattr(defaults, f.name)), getattr(defaults, f.name))
            for f in fields(AppSettings)
        }
        self._settings = AppSettings(**values).validated()
        return self._settings

    def save(self) -> None:
        """Write the settings atomically (temp file + rename)."""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(asdict(self._settings), indent=2), encoding="utf-8")
                os.replace(tmp, self._path)
            except OSError as exc:
                log.error("Could not save settings: %s", exc)

    def update(self, **changes: Any) -> None:
        """Change one or more settings and persist them."""
        self._settings = replace(self._settings, **changes).validated()
        self.save()

    def replace_all(self, settings: AppSettings) -> None:
        """Replace the whole settings object and persist it."""
        self._settings = settings.validated()
        self.save()

    def _backup_corrupt_file(self) -> None:
        try:
            if self._path.exists():
                os.replace(self._path, self._path.with_suffix(".json.bak"))
        except OSError:
            pass
