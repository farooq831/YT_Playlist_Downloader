"""Qt list model exposing :class:`VideoItem` objects to the video list view.

Thumbnails are loaded lazily: the first time the view asks for a row's
thumbnail the model emits :pyattr:`thumbnailRequested`. Loaded pixmaps are
kept in a bounded LRU cache so that very large playlists do not exhaust
memory; evicted thumbnails are simply requested again when scrolled back
into view.
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from enum import IntEnum
from typing import Any

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QPixmap

from models.video import DownloadStatus, VideoItem

ModelIndex = QModelIndex | QPersistentModelIndex


class VideoRoles(IntEnum):
    ITEM = Qt.ItemDataRole.UserRole + 1
    THUMBNAIL = Qt.ItemDataRole.UserRole + 2


class VideoListModel(QAbstractListModel):
    """List model for the playlist videos."""

    #: key, url — the key must be passed back to :meth:`set_thumbnail`.
    thumbnailRequested = Signal(str, str)

    MAX_CACHED_THUMBNAILS = 400

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._items: list[VideoItem] = []
        self._thumbs: OrderedDict[int, QPixmap] = OrderedDict()
        self._requested: set[int] = set()
        self._generation = 0

    # ------------------------------------------------------------ Qt interface
    def rowCount(self, parent: ModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        row = index.row()
        item = self._items[row]
        if role == VideoRoles.ITEM:
            return item
        if role == VideoRoles.THUMBNAIL:
            return self._thumbnail(row, item)
        if role == Qt.ItemDataRole.DisplayRole:
            return item.title
        if role == Qt.ItemDataRole.ToolTipRole:
            lines = [item.title]
            if item.filepath:
                lines.append(item.filepath)
            if item.message:
                lines.append(item.message)
            return "\n".join(lines)
        return None

    # --------------------------------------------------------------- mutation
    def set_items(self, items: list[VideoItem]) -> None:
        self.beginResetModel()
        self._items = items
        self._thumbs.clear()
        self._requested.clear()
        self._generation += 1
        self.endResetModel()

    def clear(self) -> None:
        self.set_items([])

    def items(self) -> list[VideoItem]:
        return self._items

    def item(self, row: int) -> VideoItem | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def update_item(self, row: int, **changes: Any) -> None:
        item = self.item(row)
        if item is None:
            return
        for name, value in changes.items():
            setattr(item, name, value)
        self.refresh_row(row)

    def refresh_row(self, row: int) -> None:
        if 0 <= row < len(self._items):
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [VideoRoles.ITEM])

    def refresh_all(self) -> None:
        if self._items:
            self.dataChanged.emit(self.index(0), self.index(len(self._items) - 1), [VideoRoles.ITEM])

    def status_counts(self) -> Counter[DownloadStatus]:
        return Counter(item.status for item in self._items)

    # -------------------------------------------------------------- thumbnails
    def set_thumbnail(self, key: str, pixmap: QPixmap) -> None:
        """Store a thumbnail delivered for a key produced by this model."""
        try:
            generation, row = (int(part) for part in key.split(":", 1))
        except ValueError:
            return
        if generation != self._generation or not 0 <= row < len(self._items):
            return  # result for a playlist that is no longer shown
        self._thumbs[row] = pixmap
        self._thumbs.move_to_end(row)
        while len(self._thumbs) > self.MAX_CACHED_THUMBNAILS:
            evicted, _ = self._thumbs.popitem(last=False)
            self._requested.discard(evicted)
        idx = self.index(row)
        self.dataChanged.emit(idx, idx, [VideoRoles.THUMBNAIL])

    def _thumbnail(self, row: int, item: VideoItem) -> QPixmap | None:
        pixmap = self._thumbs.get(row)
        if pixmap is not None:
            self._thumbs.move_to_end(row)
            return pixmap
        if item.thumbnail_url and row not in self._requested:
            self._requested.add(row)
            self.thumbnailRequested.emit(f"{self._generation}:{row}", item.thumbnail_url)
        return None
