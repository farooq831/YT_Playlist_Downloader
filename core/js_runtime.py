"""JavaScript runtime detection for yt-dlp.

YouTube protects its video URLs with JavaScript challenges. yt-dlp solves
them with an external JS runtime; without one, most formats are missing or
YouTube refuses the request. The ``deno`` package from PyPI (installed via
``requirements.txt``) ships a ready-to-use Deno binary, so end users do not
have to install anything themselves.

Search order: bundled Deno (pip package) → Deno on PATH → Node.js on PATH.
"""

from __future__ import annotations

import shutil
import sys
from functools import lru_cache
from pathlib import Path

from utils.logger import get_logger
from utils.paths import project_root

log = get_logger("js-runtime")


@lru_cache(maxsize=1)
def js_runtimes() -> dict[str, dict[str, str]]:
    """Value for yt-dlp's ``js_runtimes`` option (empty if none was found)."""
    bundled = project_root() / "bin" / f"deno{'.exe' if sys.platform == 'win32' else ''}"
    if bundled.is_file():  # shipped inside the packaged .exe build
        log.debug("Using packaged Deno at %s", bundled)
        return {"deno": {"path": str(bundled)}}

    try:
        import deno  # type: ignore[import-not-found]

        path = Path(deno.find_deno_bin())
        if path.is_file():
            log.debug("Using bundled Deno at %s", path)
            return {"deno": {"path": str(path)}}
    except Exception:  # noqa: BLE001 - optional package, any failure means "absent"
        pass

    for name in ("deno", "node"):
        found = shutil.which(name)
        if found:
            log.debug("Using %s at %s", name, found)
            return {name: {"path": found}}

    log.warning("No JavaScript runtime found — YouTube downloads may fail. Run: pip install deno")
    return {}


def runtime_description() -> str:
    """Short human-readable description for the UI."""
    runtimes = js_runtimes()
    if not runtimes:
        return "not found"
    name, cfg = next(iter(runtimes.items()))
    return f"{name.capitalize()} ({cfg.get('path', '')})"
