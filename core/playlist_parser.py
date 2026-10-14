"""Playlist URL validation and parsing.

Parsing uses yt-dlp's *flat* extraction, which only reads the playlist pages
(100 entries per request) instead of every single video page. This keeps
loading fast and memory usage low even for playlists with thousands of
videos.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from config.constants import THUMBNAIL_URL, YOUTUBE_WATCH_URL
from core.errors import AppError, ErrorInfo, ErrorKind, classify_error
from core.ytdlp_common import base_options, extract_with_fallback
from models.video import DownloadStatus, PlaylistInfo, VideoItem
from utils.logger import get_logger

log = get_logger("playlist")

_YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
    "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_LIST_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")
_UNAVAILABLE_TITLES = {"[private video]", "[deleted video]", "[unavailable video]"}


class InvalidUrlError(AppError):
    """The text entered by the user is not a usable YouTube URL."""

    def __init__(self, message: str) -> None:
        super().__init__(ErrorInfo(ErrorKind.INVALID_URL, message))


def normalize_url(raw: str) -> tuple[str, str]:
    """Validate a YouTube URL and return ``(canonical_url, kind)``.

    ``kind`` is ``"playlist"``, ``"video"`` or ``"channel"``. Watch URLs that
    contain a ``list=`` parameter are treated as the whole playlist.
    """
    text = raw.strip()
    if not text:
        raise InvalidUrlError("Please paste a YouTube playlist URL.")
    if "://" not in text:
        text = f"https://{text}"

    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in _YOUTUBE_HOSTS:
        raise InvalidUrlError("That doesn't look like a YouTube link. Paste a URL like "
                              "https://www.youtube.com/playlist?list=…")

    query = parse_qs(parsed.query)
    list_id = (query.get("list") or [""])[0]
    if list_id:
        if not _LIST_RE.match(list_id):
            raise InvalidUrlError("The playlist ID in this URL is malformed.")
        return f"https://www.youtube.com/playlist?list={list_id}", "playlist"

    path = parsed.path.rstrip("/")
    video_id = ""
    if host.endswith("youtu.be"):
        video_id = path.lstrip("/").split("/")[0]
    elif path == "/watch":
        video_id = (query.get("v") or [""])[0]
    elif path.startswith(("/shorts/", "/live/", "/embed/", "/v/")):
        video_id = path.split("/")[2] if path.count("/") >= 2 else ""
    if video_id:
        if not _ID_RE.match(video_id):
            raise InvalidUrlError("The video ID in this URL is malformed.")
        return YOUTUBE_WATCH_URL.format(id=video_id), "video"

    if path.startswith(("/@", "/channel/", "/c/", "/user/")):
        parts = path.split("/")
        base = "/".join(parts[:3] if parts[1] in {"channel", "c", "user"} else parts[:2])
        tab = path[len(base):] or "/videos"
        return f"https://www.youtube.com{base}{tab}", "channel"

    raise InvalidUrlError("This YouTube URL does not point to a playlist or video.")


class PlaylistParser:
    """Loads playlist metadata through the yt-dlp API."""

    def parse(self, url: str) -> PlaylistInfo:
        """Fetch and parse *url*. Raises :class:`AppError` on failure."""
        canonical, kind = normalize_url(url)
        extra = {
            "extract_flat": "in_playlist",
            "skip_download": True,
            "noplaylist": False,
            "lazy_playlist": False,
            "ignoreerrors": False,
        }
        log.info("Fetching playlist information…")
        try:
            info = extract_with_fallback(
                lambda clients: base_options(log, player_clients=clients) | extra,
                canonical, download=False, logger=log,
            )
        except Exception as exc:  # noqa: BLE001 - classified below
            log.debug("Playlist extraction failed", exc_info=True)
            raise AppError(classify_error(exc)) from exc

        if not info:
            raise AppError(ErrorInfo(ErrorKind.UNKNOWN, "YouTube returned no data for this URL."))

        if info.get("_type") in {"playlist", "multi_video"}:
            playlist = self._build_playlist(info, canonical)
        else:
            playlist = self._build_single(info, canonical)

        if not playlist.videos:
            raise AppError(ErrorInfo(ErrorKind.REMOVED, "This playlist is empty or none of its videos are available."))
        if kind == "channel":
            playlist.title = playlist.title or "Channel uploads"
        log.info("Loaded “%s” with %d videos", playlist.title, playlist.video_count)
        return playlist

    # ----------------------------------------------------------------- helpers
    def _build_playlist(self, info: dict[str, Any], url: str) -> PlaylistInfo:
        videos: list[VideoItem] = []
        for entry in info.get("entries") or []:
            if not entry:
                continue
            if entry.get("_type") == "playlist" or entry.get("ie_key") == "YoutubeTab":
                continue  # nested tabs/playlists are not supported
            video = self._entry_to_video(entry, len(videos) + 1)
            if video:
                videos.append(video)

        first_available = next((v for v in videos if v.is_downloadable), None)
        return PlaylistInfo(
            title=info.get("title") or "Untitled playlist",
            url=url,
            playlist_id=info.get("id"),
            uploader=info.get("uploader") or info.get("channel"),
            thumbnail_url=first_available.thumbnail_url if first_available else None,
            videos=videos,
        )

    def _build_single(self, info: dict[str, Any], url: str) -> PlaylistInfo:
        video = self._entry_to_video(info, 1)
        videos = [video] if video else []
        return PlaylistInfo(
            title=info.get("title") or "Video",
            url=url,
            playlist_id=None,
            uploader=info.get("uploader") or info.get("channel"),
            thumbnail_url=video.thumbnail_url if video else None,
            videos=videos,
            is_single_video=True,
        )

    @staticmethod
    def _entry_to_video(entry: dict[str, Any], index: int) -> VideoItem | None:
        video_id = entry.get("id")
        if not video_id:
            return None
        title = (entry.get("title") or "").strip() or "Untitled video"
        duration = entry.get("duration")
        video = VideoItem(
            index=index,
            video_id=video_id,
            title=title,
            url=YOUTUBE_WATCH_URL.format(id=video_id),
            duration=int(duration) if isinstance(duration, (int, float)) else None,
            uploader=entry.get("uploader") or entry.get("channel"),
            thumbnail_url=THUMBNAIL_URL.format(id=video_id),
        )
        availability = entry.get("availability")
        if title.lower() in _UNAVAILABLE_TITLES or availability in {"private", "needs_auth", "subscriber_only"}:
            video.status = DownloadStatus.UNAVAILABLE
            video.message = (
                "Private video" if "private" in title.lower() or availability == "private"
                else "Members-only video" if availability == "subscriber_only"
                else "Requires sign-in" if availability == "needs_auth"
                else "Video was removed"
            )
            video.thumbnail_url = None
        if entry.get("live_status") in {"is_upcoming", "is_live"}:
            video.status = DownloadStatus.UNAVAILABLE
            video.message = "Live stream / premiere — not downloadable yet"
        return video
