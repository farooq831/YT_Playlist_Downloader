"""Plain data objects describing playlists, videos and their download state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DownloadStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    FETCHING = "fetching"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    RETRYING = "retrying"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def is_active(self) -> bool:
        """A worker is currently busy with this item."""
        return self in {self.FETCHING, self.DOWNLOADING, self.PROCESSING, self.RETRYING}

    @property
    def is_finished(self) -> bool:
        """The item has reached a final state for the current run."""
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED, self.UNAVAILABLE}


_LABELS: dict[DownloadStatus, str] = {
    DownloadStatus.PENDING: "Ready",
    DownloadStatus.QUEUED: "Queued",
    DownloadStatus.FETCHING: "Preparing",
    DownloadStatus.DOWNLOADING: "Downloading",
    DownloadStatus.PROCESSING: "Merging",
    DownloadStatus.RETRYING: "Retrying",
    DownloadStatus.PAUSED: "Paused",
    DownloadStatus.COMPLETED: "Completed",
    DownloadStatus.FAILED: "Failed",
    DownloadStatus.CANCELLED: "Cancelled",
    DownloadStatus.UNAVAILABLE: "Unavailable",
}


@dataclass(slots=True)
class VideoItem:
    """One entry of a playlist plus its live download state."""

    index: int
    video_id: str
    title: str
    url: str
    duration: int | None = None
    uploader: str | None = None
    thumbnail_url: str | None = None

    status: DownloadStatus = DownloadStatus.PENDING
    progress: float = 0.0  # 0..100
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    speed: float | None = None
    eta: float | None = None
    resolution: str | None = None
    estimated_size: int | None = None
    filepath: str | None = None
    message: str = ""

    @property
    def is_downloadable(self) -> bool:
        return self.status is not DownloadStatus.UNAVAILABLE

    @property
    def display_size(self) -> int | None:
        """Best known size: the real one while downloading, else the estimate."""
        return self.total_bytes or self.estimated_size

    def reset_progress(self) -> None:
        self.progress = 0.0
        self.downloaded_bytes = 0
        self.speed = None
        self.eta = None
        self.message = ""


@dataclass(slots=True)
class PlaylistInfo:
    """A parsed playlist (or a single video wrapped as a one-item playlist)."""

    title: str
    url: str
    playlist_id: str | None = None
    uploader: str | None = None
    thumbnail_url: str | None = None
    videos: list[VideoItem] = field(default_factory=list)
    is_single_video: bool = False

    @property
    def video_count(self) -> int:
        return len(self.videos)

    @property
    def available_count(self) -> int:
        return sum(1 for v in self.videos if v.is_downloadable)

    @property
    def unavailable_count(self) -> int:
        return self.video_count - self.available_count

    @property
    def total_duration(self) -> int:
        return sum(v.duration or 0 for v in self.videos if v.is_downloadable)
