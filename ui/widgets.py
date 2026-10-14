"""Reusable building blocks for the main window."""

from __future__ import annotations

import html
import logging

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from models.video import PlaylistInfo
from ui.icons import svg_pixmap
from ui.theme import ThemeManager
from utils.formatting import format_bytes, format_duration


def make_button(text: str, variant: str | None = None, tooltip: str = "") -> QPushButton:
    """Create a styled push button (variants: primary, danger, ghost, link)."""
    button = QPushButton(text)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        button.setProperty("variant", variant)
    if tooltip:
        button.setToolTip(tooltip)
    return button


def section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("SectionTitle")
    return label


class Card(QFrame):
    """Rounded surface used to group related controls."""

    def __init__(self, parent: QWidget | None = None, margins: int = 18, spacing: int = 12) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(margins, margins, margins, margins)
        self.body.setSpacing(spacing)


class RoundedImage(QLabel):
    """Shows a pixmap cropped to a rounded rectangle with a placeholder."""

    def __init__(self, size: QSize, radius: int = 10, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._radius = radius
        self._aspect = size.height() / size.width()
        self.setMinimumSize(QSize(size.width() // 2, size.height() // 2))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(size.height())

    def set_image(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        self.setFixedHeight(int(self.width() * self._aspect))
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802, ANN001
        pal = ThemeManager.palette()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.setClipPath(path)
        if self._pixmap and not self._pixmap.isNull():
            painter.drawPixmap(self.rect(), self._pixmap)
        else:
            painter.fillRect(rect, QColor(pal.surface_alt))
            icon = svg_pixmap("film", pal.text_faint, 40, 1.6)
            painter.drawPixmap(int(rect.center().x() - 20), int(rect.center().y() - 20), icon)
        painter.end()


class PlaylistHeader(Card):
    """Playlist thumbnail, title and summary chips."""

    estimateRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, margins=14, spacing=10)
        self.thumbnail = RoundedImage(QSize(320, 180))
        self.title = QLabel("No playlist loaded")
        self.title.setObjectName("PlaylistTitle")
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.uploader = QLabel("Paste a playlist link above to get started.")
        self.uploader.setObjectName("Muted")
        self.uploader.setWordWrap(True)

        self.count_chip = self._chip()
        self.duration_chip = self._chip()
        self.size_chip = self._chip()
        chips = QHBoxLayout()
        chips.setSpacing(6)
        for chip in (self.count_chip, self.duration_chip, self.size_chip):
            chips.addWidget(chip)
        chips.addStretch(1)

        self.estimate_button = make_button("Estimate size", "link", "Calculate the total download size "
                                           "for the selected quality")
        self.estimate_button.clicked.connect(self.estimateRequested)
        self.estimate_status = QLabel("")
        self.estimate_status.setObjectName("Faint")
        estimate_row = QHBoxLayout()
        estimate_row.setContentsMargins(0, 0, 0, 0)
        estimate_row.addWidget(self.estimate_button)
        estimate_row.addWidget(self.estimate_status, 1)

        self.body.addWidget(self.thumbnail)
        self.body.addWidget(self.title)
        self.body.addWidget(self.uploader)
        self.body.addLayout(chips)
        self.body.addLayout(estimate_row)
        self.set_playlist(None)

    @staticmethod
    def _chip() -> QLabel:
        chip = QLabel()
        chip.setObjectName("Chip")
        chip.hide()
        return chip

    def set_playlist(self, playlist: PlaylistInfo | None) -> None:
        self.thumbnail.set_image(None)
        self.thumbnail.setVisible(playlist is not None)
        if playlist is None:
            self.title.setText("No playlist loaded")
            self.uploader.setText("Paste a playlist link above to get started.")
            for chip in (self.count_chip, self.duration_chip, self.size_chip):
                chip.hide()
            self.estimate_button.hide()
            self.estimate_status.clear()
            return
        self.title.setText(playlist.title)
        self.uploader.setText(playlist.uploader or ("Single video" if playlist.is_single_video else "YouTube playlist"))
        count = playlist.video_count
        text = f"{count} video{'s' if count != 1 else ''}"
        if playlist.unavailable_count:
            text += f" · {playlist.unavailable_count} unavailable"
        self.count_chip.setText(text)
        self.count_chip.show()
        self.duration_chip.setText(f"{format_duration(playlist.total_duration)} total")
        self.duration_chip.setVisible(playlist.total_duration > 0)
        self.set_size(None)
        self.estimate_button.show()
        self.estimate_status.clear()

    def set_size(self, size: int | None, partial: bool = False) -> None:
        if size:
            self.size_chip.setText(f"≈ {format_bytes(size)}{'+' if partial else ''}")
            self.size_chip.show()
        else:
            self.size_chip.hide()


class EmptyState(QWidget):
    """Centered icon + text shown when the list is empty or loading."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title = QLabel()
        self.title.setObjectName("EmptyTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text = QLabel()
        self.text.setObjectName("Muted")
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text.setWordWrap(True)
        self.busy = QProgressBar()
        self.busy.setObjectName("BusyBar")
        self.busy.setRange(0, 0)
        self.busy.setFixedWidth(220)
        busy_row = QHBoxLayout()
        busy_row.addStretch(1)
        busy_row.addWidget(self.busy)
        busy_row.addStretch(1)
        for widget in (self.icon, self.title, self.text):
            layout.addWidget(widget)
        layout.addSpacing(6)
        layout.addLayout(busy_row)
        layout.addStretch(1)
        self._icon_name = "inbox"
        self.show_idle()

    def show_idle(self) -> None:
        self._set("inbox", "Your playlist will appear here",
                  "Paste a YouTube playlist URL and press Load Playlist. "
                  "Every video is saved as an MP4 file with audio.", busy=False)

    def show_loading(self) -> None:
        self._set("list", "Loading playlist…", "Fetching the list of videos from YouTube.", busy=True)

    def show_error(self, message: str) -> None:
        self._set("alert", "Couldn't load the playlist", message, busy=False)

    def _set(self, icon: str, title: str, text: str, busy: bool) -> None:
        self._icon_name = icon
        self.refresh_icon()
        self.title.setText(title)
        self.text.setText(text)
        self.busy.setVisible(busy)

    def refresh_icon(self) -> None:
        self.icon.setPixmap(svg_pixmap(self._icon_name, ThemeManager.palette().text_faint, 48, 1.5))


class LogPanel(Card):
    """Read-only, color-coded log view fed by the logging bridge."""

    MAX_LINES = 5000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, margins=14, spacing=8)
        header = QHBoxLayout()
        header.setSpacing(6)
        self.icon = QLabel()
        header.addWidget(self.icon)
        header.addWidget(section_title("Download log"))
        header.addStretch(1)
        self.open_button = make_button("Open log file", "ghost")
        self.clear_button = make_button("Clear", "ghost")
        header.addWidget(self.open_button)
        header.addWidget(self.clear_button)
        self.view = QPlainTextEdit()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(self.MAX_LINES)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.view.setMinimumHeight(70)
        self.clear_button.clicked.connect(self.view.clear)
        self.body.addLayout(header)
        self.body.addWidget(self.view, 1)

    def append_message(self, level: int, text: str) -> None:
        p = ThemeManager.palette()
        color = (
            p.danger if level >= logging.ERROR
            else p.warning if level >= logging.WARNING
            else p.success if text.split("  ", 1)[-1].startswith(("Completed", "Already downloaded"))
            else p.text_muted
        )
        bar = self.view.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        safe = html.escape(text).replace("  ", " &nbsp;")
        self.view.appendHtml(f'<span style="color:{color}">{safe}</span>')
        if at_bottom:
            self.view.moveCursor(QTextCursor.MoveOperation.End)
            bar.setValue(bar.maximum())
