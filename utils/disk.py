"""Disk-space and writability helpers."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def existing_parent(path: Path) -> Path:
    """Return *path* or its closest ancestor that exists on disk."""
    current = path.expanduser().resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def free_space(path: Path | str) -> int | None:
    """Free bytes on the drive that holds *path* (``None`` if unknown)."""
    try:
        return shutil.disk_usage(existing_parent(Path(path))).free
    except OSError:
        return None


def is_writable(directory: Path) -> bool:
    """Check that files can actually be created inside *directory*."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".ytpd_", delete=True):
            pass
        return True
    except OSError:
        return False
