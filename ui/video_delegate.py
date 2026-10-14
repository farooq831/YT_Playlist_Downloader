"""Custom painter for rows of the video list.

Painting rows directly (instead of creating a widget per row) keeps the list
smooth and memory-light even for playlists with thousands of videos.

Row layout::

    ┌──────────────────────────────────────────────────────────────┐
    │ ┌──────────┐  12. Video title …                  [ STATUS ] │
    │ │thumbnail │  1080p · 245.3 MB · Channel                     │
    │ │    3:21  │  120.4 MB of 245.3 MB      49% · 3.2 MB/s · 0:42│
    │ └──────────┘  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
    └──────────────────────────────────────────────────────────────┘
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from models.video import DownloadStatus, VideoItem
from models.video_list_model import VideoRoles
from ui.icons import svg_pixmap
from ui.theme import Palette, ThemeManager, status_color
from utils.formatting import format_bytes, format_duration, format_eta, format_speed

ModelIndex = QModelIndex | QPersistentModelIndex


class VideoItemDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 98
    THUMB_SIZE = QSize(128, 72)
    THUMB_LOAD_SIZE = QSize(256, 144)  # 2× for high-DPI screens

    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        item: VideoItem | None = index.data(VideoRoles.ITEM)
        if item is None:
            return
        pal = ThemeManager.palette()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        state = option.state
        selected = bool(state & QStyle.StateFlag.State_Selected)
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        rect = QRectF(option.rect).adjusted(4, 4, -4, -4)

        # Card background
        painter.setPen(QPen(QColor(pal.accent if selected else pal.border), 1))
        painter.setBrush(QColor(pal.surface_hover if (hovered or selected) else pal.surface_alt))
        painter.drawRoundedRect(rect, 10, 10)

        # Thumbnail
        thumb = QRectF(rect.left() + 10, rect.top() + (rect.height() - self.THUMB_SIZE.height()) / 2,
                       self.THUMB_SIZE.width(), self.THUMB_SIZE.height())
        self._paint_thumbnail(painter, thumb, index.data(VideoRoles.THUMBNAIL), item, pal)

        # Status chip
        color = status_color(item.status, pal)
        chip_font = QFont(option.font)
        chip_font.setPointSizeF(8.0)
        chip_font.setBold(True)
        chip_fm = QFontMetrics(chip_font)
        chip_text = item.status.label.upper()
        chip_w = chip_fm.horizontalAdvance(chip_text) + 20
        chip = QRectF(rect.right() - 12 - chip_w, rect.top() + 10, chip_w, 22)
        chip_bg = QColor(color)
        chip_bg.setAlphaF(0.14)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(chip_bg)
        painter.drawRoundedRect(chip, 11, 11)
        painter.setFont(chip_font)
        painter.setPen(QColor(color))
        painter.drawText(chip, Qt.AlignmentFlag.AlignCenter, chip_text)

        left = thumb.right() + 14
        right = rect.right() - 12

        # Title
        title_font = QFont(option.font)
        title_font.setPointSizeF(10.0)
        title_font.setBold(True)
        title_rect = QRectF(left, rect.top() + 9, chip.left() - 12 - left, 22)
        painter.setFont(title_font)
        painter.setPen(QColor(pal.text_faint if item.status is DownloadStatus.UNAVAILABLE else pal.text))
        title = f"{item.index}. {item.title}"
        painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         QFontMetrics(title_font).elidedText(title, Qt.TextElideMode.ElideRight,
                                                             int(title_rect.width())))

        # Meta line
        small = QFont(option.font)
        small.setPointSizeF(8.6)
        small_fm = QFontMetrics(small)
        painter.setFont(small)
        meta_parts = [item.resolution or "Auto quality"]
        if item.display_size:
            prefix = "" if item.total_bytes else "~"
            meta_parts.append(f"{prefix}{format_bytes(item.display_size)}")
        if item.uploader:
            meta_parts.append(item.uploader)
        meta_rect = QRectF(left, rect.top() + 31, right - left, 18)
        painter.setPen(QColor(pal.text_muted))
        painter.drawText(meta_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         small_fm.elidedText("  ·  ".join(meta_parts), Qt.TextElideMode.ElideRight,
                                             int(meta_rect.width())))

        # Detail line (left: state description, right: numbers)
        detail_rect = QRectF(left, rect.top() + 51, right - left, 18)
        left_text, left_color, right_text = self._detail_texts(item, pal)
        right_w = small_fm.horizontalAdvance(right_text) + 4 if right_text else 0
        if right_text:
            painter.setPen(QColor(pal.text_muted))
            painter.drawText(detail_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right_text)
        if left_text:
            painter.setPen(QColor(left_color))
            avail = int(detail_rect.width() - right_w - 12)
            painter.drawText(detail_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             small_fm.elidedText(left_text, Qt.TextElideMode.ElideRight, avail))

        # Progress bar
        bar = QRectF(left, rect.bottom() - 16, right - left, 6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(pal.track))
        painter.drawRoundedRect(bar, 3, 3)
        fraction = self._fraction(item)
        if fraction > 0:
            filled = QRectF(bar.left(), bar.top(), max(6.0, bar.width() * fraction), bar.height())
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(filled, 3, 3)

        painter.restore()

    # ---------------------------------------------------------------- helpers
    def _paint_thumbnail(self, painter: QPainter, rect: QRectF, pixmap: object, item: VideoItem, pal: Palette) -> None:
        clip = QPainterPath()
        clip.addRoundedRect(rect, 8, 8)
        painter.save()
        painter.setClipPath(clip)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            painter.drawPixmap(rect.toRect(), pixmap)
            if item.status is DownloadStatus.UNAVAILABLE:
                painter.fillRect(rect, QColor(0, 0, 0, 150))
        else:
            painter.fillRect(rect, QColor(pal.track))
            icon = svg_pixmap("film", pal.text_faint, 26)
            painter.drawPixmap(int(rect.center().x() - 13), int(rect.center().y() - 13), icon)
        painter.restore()

        if item.duration:
            font = QFont(painter.font())
            font.setPointSizeF(7.6)
            font.setBold(True)
            fm = QFontMetrics(font)
            text = format_duration(item.duration)
            w = fm.horizontalAdvance(text) + 10
            badge = QRectF(rect.right() - w - 4, rect.bottom() - 20, w, 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 200))
            painter.drawRoundedRect(badge, 4, 4)
            painter.setFont(font)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _fraction(item: VideoItem) -> float:
        if item.status is DownloadStatus.COMPLETED:
            return 1.0
        if item.status in {DownloadStatus.PENDING, DownloadStatus.QUEUED, DownloadStatus.UNAVAILABLE,
                           DownloadStatus.CANCELLED} and item.progress <= 0:
            return 0.0
        return max(0.0, min(1.0, item.progress / 100.0))

    @staticmethod
    def _detail_texts(item: VideoItem, p: Palette) -> tuple[str, str, str]:
        status = item.status
        muted = p.text_muted
        if status is DownloadStatus.DOWNLOADING:
            left = f"{format_bytes(item.downloaded_bytes)} of {format_bytes(item.total_bytes)}" \
                if item.total_bytes else format_bytes(item.downloaded_bytes)
            right = f"{item.progress:.1f}%  ·  {format_speed(item.speed)}  ·  ETA {format_eta(item.eta)}"
            return left, muted, right
        if status is DownloadStatus.COMPLETED:
            return item.message or "Saved as MP4", p.success, "100%"
        if status in {DownloadStatus.FAILED, DownloadStatus.UNAVAILABLE}:
            return item.message or status.label, p.danger if status is DownloadStatus.FAILED else muted, ""
        if status is DownloadStatus.RETRYING:
            return item.message, p.warning, ""
        if status is DownloadStatus.PAUSED:
            return f"Paused at {item.progress:.1f}% — partial data is kept", p.warning, ""
        if status in {DownloadStatus.FETCHING, DownloadStatus.PROCESSING}:
            return item.message, p.info, f"{item.progress:.0f}%" if item.progress else ""
        if status is DownloadStatus.QUEUED:
            return "Waiting in queue", muted, ""
        if status is DownloadStatus.CANCELLED:
            return "Cancelled", muted, ""
        return "", muted, ""
