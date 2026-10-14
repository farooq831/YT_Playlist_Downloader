"""Filesystem locations used by the application (config, logs, assets)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from config.constants import APP_ID


def project_root() -> Path:
    """Return the directory that contains the application sources.

    Works both when running from source and from a PyInstaller bundle.
    """
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    """Directory holding icons and other static resources."""
    return project_root() / "assets"


def app_data_dir() -> Path:
    """Per-user, writable directory for configuration and logs."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    path = base / APP_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    """Directory for rotating log files."""
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    """Location of the JSON configuration file."""
    return app_data_dir() / "config.json"


def default_download_dir() -> Path:
    """The user's Downloads folder, or the home directory as a fallback."""
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()
