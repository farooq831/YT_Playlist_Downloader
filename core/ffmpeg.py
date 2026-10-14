"""FFmpeg detection.

FFmpeg is mandatory: YouTube serves HD video and audio as separate streams,
and FFmpeg is what merges them into a single MP4 file.

The locator checks, in order:

1. a path configured by the user in Settings,
2. the ``FFMPEG_PATH`` / ``FFMPEG_BINARY`` environment variables,
3. a ``bin/`` or ``ffmpeg/bin/`` folder shipped next to the application,
4. the system ``PATH``,
5. well-known install locations (winget, scoop, chocolatey, Homebrew, ...),
6. the binary bundled with the optional ``imageio-ffmpeg`` package.

Every candidate is verified by actually running ``ffmpeg -version``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from utils.logger import get_logger
from utils.paths import project_root

log = get_logger("ffmpeg")

_EXE_SUFFIX = ".exe" if sys.platform == "win32" else ""
_VERSION_RE = re.compile(r"ffmpeg version\s+(\S+)", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class FFmpegInfo:
    """A verified FFmpeg installation."""

    ffmpeg_path: Path
    version: str
    source: str
    ffprobe_path: Path | None = None

    @property
    def location(self) -> str:
        """Value for yt-dlp's ``ffmpeg_location`` option.

        A directory is passed when it contains a normally named ``ffmpeg``
        binary (so ffprobe is picked up as well); otherwise the binary itself.
        """
        if self.ffmpeg_path.stem.lower() == "ffmpeg":
            return str(self.ffmpeg_path.parent)
        return str(self.ffmpeg_path)

    @property
    def short_version(self) -> str:
        match = re.match(r"n?(\d+(?:\.\d+)*)", self.version)
        return match.group(1) if match else self.version[:16]


class FFmpegLocator:
    """Finds and verifies an FFmpeg binary."""

    def __init__(self, custom_path: str | Path | None = None, timeout: float = 10.0) -> None:
        self._custom_path = Path(custom_path).expanduser() if custom_path else None
        self._timeout = timeout

    # ------------------------------------------------------------------ public
    def locate(self) -> FFmpegInfo | None:
        """Return the first working FFmpeg, or ``None`` if none was found."""
        seen: set[str] = set()
        for candidate, source in self._candidates():
            key = os.path.normcase(str(candidate))
            if key in seen or not candidate.is_file():
                continue
            seen.add(key)
            version = self.verify(candidate)
            if version:
                ffprobe = self._sibling_ffprobe(candidate)
                log.debug("Using FFmpeg %s from %s (%s)", version, candidate, source)
                return FFmpegInfo(candidate, version, source, ffprobe)
            log.debug("Rejected FFmpeg candidate %s", candidate)
        return None

    def verify(self, binary: Path) -> str | None:
        """Run ``ffmpeg -version`` and return the version string if it works."""
        try:
            result = subprocess.run(
                [str(binary), "-hide_banner", "-version"],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("Could not execute %s: %s", binary, exc)
            return None
        if result.returncode != 0:
            return None
        match = _VERSION_RE.search(result.stdout or "")
        return match.group(1) if match else "unknown"

    # ----------------------------------------------------------------- helpers
    def _candidates(self) -> Iterator[tuple[Path, str]]:
        exe = f"ffmpeg{_EXE_SUFFIX}"

        if self._custom_path:
            path = self._custom_path
            yield (path / exe if path.is_dir() else path), "settings"
            yield path / "bin" / exe, "settings"

        for var in ("FFMPEG_PATH", "FFMPEG_BINARY", "IMAGEIO_FFMPEG_EXE"):
            value = os.environ.get(var)
            if value:
                path = Path(value)
                yield (path / exe if path.is_dir() else path), f"${var}"

        root = project_root()
        for folder in (root / "bin", root / "ffmpeg" / "bin", root / "ffmpeg", root / "assets" / "ffmpeg"):
            yield folder / exe, "bundled"

        found = shutil.which("ffmpeg")
        if found:
            yield Path(found), "PATH"

        for folder in self._well_known_dirs():
            yield folder / exe, "system"

        bundled = self._imageio_ffmpeg()
        if bundled:
            yield bundled, "imageio-ffmpeg"

    @staticmethod
    def _well_known_dirs() -> Iterator[Path]:
        home = Path.home()
        if sys.platform == "win32":
            env = os.environ
            program_files = [env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), env.get("ProgramW6432")]
            local = Path(env.get("LOCALAPPDATA", home / "AppData" / "Local"))
            yield Path("C:/ffmpeg/bin")
            for base in filter(None, program_files):
                yield Path(base) / "ffmpeg" / "bin"
                yield Path(base) / "FFmpeg" / "bin"
            yield local / "Microsoft" / "WinGet" / "Links"
            packages = local / "Microsoft" / "WinGet" / "Packages"
            if packages.is_dir():
                for match in sorted(packages.glob("*FFmpeg*/*/bin"), reverse=True):
                    yield match
            yield home / "scoop" / "shims"
            yield home / "scoop" / "apps" / "ffmpeg" / "current" / "bin"
            yield Path(env.get("ChocolateyInstall", "C:/ProgramData/chocolatey")) / "bin"
        elif sys.platform == "darwin":
            yield from (Path("/opt/homebrew/bin"), Path("/usr/local/bin"), Path("/opt/local/bin"))
        else:
            yield from (Path("/usr/bin"), Path("/usr/local/bin"), Path("/snap/bin"),
                        home / ".local" / "bin", Path("/var/lib/flatpak/exports/bin"))

    @staticmethod
    def _imageio_ffmpeg() -> Path | None:
        try:
            import imageio_ffmpeg  # type: ignore[import-not-found]

            return Path(imageio_ffmpeg.get_ffmpeg_exe())
        except Exception:  # noqa: BLE001 - optional dependency, any failure means "absent"
            return None

    @staticmethod
    def _sibling_ffprobe(ffmpeg: Path) -> Path | None:
        probe = ffmpeg.with_name(f"ffprobe{_EXE_SUFFIX}")
        return probe if probe.is_file() else None


def install_hint() -> str:
    """Platform-specific instructions for installing FFmpeg."""
    if sys.platform == "win32":
        return (
            "Install FFmpeg with one of:\n"
            "  • winget install Gyan.FFmpeg\n"
            "  • choco install ffmpeg   /   scoop install ffmpeg\n"
            "  • pip install imageio-ffmpeg\n"
            "or download it from https://www.gyan.dev/ffmpeg/builds/ and select "
            "ffmpeg.exe in Settings › Advanced."
        )
    if sys.platform == "darwin":
        return "Install FFmpeg with:  brew install ffmpeg   (or: pip install imageio-ffmpeg)"
    return (
        "Install FFmpeg with your package manager, e.g.\n"
        "  sudo apt install ffmpeg   /   sudo dnf install ffmpeg   /   sudo pacman -S ffmpeg\n"
        "(or: pip install imageio-ffmpeg)"
    )
