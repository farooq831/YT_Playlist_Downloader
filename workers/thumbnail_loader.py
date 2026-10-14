"""Asynchronous thumbnail downloader based on ``QNetworkAccessManager``.

Requests are fully asynchronous (no threads needed), de-duplicated, limited
in parallelism, and images are scaled/cropped to 16:9 before being handed
to the UI so that only small pixmaps are kept in memory.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QObject, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from config.constants import USER_AGENT
from utils.logger import get_logger

log = get_logger("thumbnails")


class ThumbnailLoader(QObject):
    """Loads images by URL and emits ``loaded(key, pixmap)``."""

    loaded = Signal(str, QPixmap)

    def __init__(self, parent: QObject | None = None, max_parallel: int = 6) -> None:
        super().__init__(parent)
        self._nam = QNetworkAccessManager(self)
        self._pending: deque[tuple[str, str, QSize]] = deque()
        self._in_flight = 0
        self._max_parallel = max_parallel

    def request(self, key: str, url: str, size: QSize) -> None:
        """Queue a download; the image is center-cropped to *size*."""
        self._pending.append((key, url, size))
        self._pump()

    def clear_pending(self) -> None:
        self._pending.clear()

    def _pump(self) -> None:
        while self._in_flight < self._max_parallel and self._pending:
            key, url, size = self._pending.popleft()
            request = QNetworkRequest(QUrl(url))
            request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, USER_AGENT)
            request.setAttribute(
                QNetworkRequest.Attribute.RedirectPolicyAttribute,
                QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
            )
            request.setTransferTimeout(15000)
            reply = self._nam.get(request)
            self._in_flight += 1
            reply.finished.connect(lambda r=reply, k=key, s=size: self._on_finished(r, k, s))

    def _on_finished(self, reply: QNetworkReply, key: str, size: QSize) -> None:
        self._in_flight -= 1
        try:
            if reply.error() == QNetworkReply.NetworkError.NoError:
                image = QImage()
                if image.loadFromData(reply.readAll()) and not image.isNull():
                    self.loaded.emit(key, QPixmap.fromImage(self._crop(image, size)))
            else:
                log.debug("Thumbnail failed (%s): %s", reply.url().toString(), reply.errorString())
        finally:
            reply.deleteLater()
            self._pump()

    @staticmethod
    def _crop(image: QImage, size: QSize) -> QImage:
        scaled = image.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                              Qt.TransformationMode.SmoothTransformation)
        x = max(0, (scaled.width() - size.width()) // 2)
        y = max(0, (scaled.height() - size.height()) // 2)
        return scaled.copy(QRect(x, y, size.width(), size.height()))
