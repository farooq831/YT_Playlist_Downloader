"""Main application window.

The window only coordinates: parsing, downloading, FFmpeg detection and size
estimation all run on background threads and report back through signals,
so the GUI thread never blocks.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from config.constants import (
    APP_NAME,
    APP_VERSION,
    AUTHOR,
    AUTO_ESTIMATE_LIMIT,
    COPYRIGHT,
    MIN_FREE_SPACE_BYTES,
    QUALITY_OPTIONS,
)
from config.settings import ConfigManager
from core.download_manager import DownloadManager, ManagerState
from core.downloader import DownloadResult, Phase, ProgressSnapshot
from core.errors import AppError, ErrorInfo, ErrorKind, classify_error
from core.ffmpeg import FFmpegInfo, install_hint
from core.filename_template import TemplateError, build_outtmpl
from core.format_selector import quality_to_height
from core.playlist_parser import InvalidUrlError, normalize_url
from core.size_estimator import SizeEstimate
from models.video import DownloadStatus, PlaylistInfo
from models.video_list_model import VideoListModel, VideoRoles
from ui.icons import app_icon, svg_icon, svg_pixmap
from ui.settings_dialog import SettingsDialog
from ui.theme import ThemeManager, repolish
from ui.video_delegate import VideoItemDelegate
from ui.widgets import Card, EmptyState, LogPanel, PlaylistHeader, make_button, section_title
from utils.disk import free_space, is_writable
from utils.formatting import format_bytes, format_eta, format_speed, sanitize_filename
from utils.logger import QtLogHandler, get_logger
from utils.paths import logs_dir
from workers.background_jobs import ffmpeg_detect_task, playlist_load_task, size_estimate_task
from workers.download_worker import DownloadJob, WorkerConfig, WorkerOutcome
from workers.task import BackgroundTask
from workers.thumbnail_loader import ThumbnailLoader

log = get_logger("ui")

_HEADER_THUMB_KEY = "header"

#: Errors that affect every remaining video: the queue is paused and the
#: affected videos are retried automatically when the user presses Resume.
_PAUSING_ERRORS = frozenset({
    ErrorKind.DISK_FULL, ErrorKind.FFMPEG_MISSING, ErrorKind.PERMISSION,
})


class MainWindow(QMainWindow):
    """Top-level window of the application."""

    SIDEBAR_WIDTH = 350

    def __init__(self, config: ConfigManager, log_handler: QtLogHandler) -> None:
        super().__init__()
        self._config = config
        self._playlist: PlaylistInfo | None = None
        self._ffmpeg: FFmpegInfo | None = None
        self._ffmpeg_detecting = False
        self._load_task: BackgroundTask | None = None
        self._estimate_task: BackgroundTask | None = None
        self._ffmpeg_task: BackgroundTask | None = None
        self._job_rows: list[int] = []
        self._disk_warning_shown = False
        self._jobs: dict[int, DownloadJob] = {}
        self._worker_config: WorkerConfig | None = None
        self._retry_on_resume: set[int] = set()

        self._model = VideoListModel(self)
        self._thumbs = ThumbnailLoader(self)
        self._manager = DownloadManager(self)
        self._manager.set_max_concurrent(self.settings.max_concurrent_downloads)

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setMinimumSize(QSize(980, 660))
        self.setAcceptDrops(True)

        self._build_ui()
        self._connect_signals()
        log_handler.emitter.message.connect(self.log_panel.append_message)
        self._refresh_icons()
        self._restore_geometry()

        self._overall_timer = QTimer(self)
        self._overall_timer.setInterval(500)
        self._overall_timer.timeout.connect(self._update_overall_progress)
        self._disk_timer = QTimer(self)
        self._disk_timer.setInterval(5000)
        self._disk_timer.timeout.connect(self._update_disk_space)
        self._disk_timer.start()

        self._update_disk_space()
        self._update_controls()
        QTimer.singleShot(0, self._detect_ffmpeg)
        log.info("%s is ready. Paste a playlist URL to begin.", APP_NAME)

    @property
    def settings(self):  # noqa: ANN201 - convenience alias
        return self._config.settings

    # =================================================================== UI
    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("Central")
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 16, 20, 12)
        root.setSpacing(14)
        root.addLayout(self._build_header())
        root.addWidget(self._build_url_card())

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        body = QWidget()
        body.setObjectName("Transparent")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(14)
        body_layout.addWidget(self._build_sidebar())
        body_layout.addWidget(self._build_video_card(), 1)
        self.log_panel = LogPanel()
        self.splitter.addWidget(body)
        self.splitter.addWidget(self.log_panel)
        self.splitter.setStretchFactor(0, 4)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([520, 170])
        root.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

        self.status_label = QLabel("Ready")
        self.statusBar().addWidget(self.status_label, 1)
        self.queue_label = QLabel("")
        self.statusBar().addPermanentWidget(self.queue_label)
        self.credit_label = QLabel(f"Made by {AUTHOR}  ·  {COPYRIGHT}")
        self.statusBar().addPermanentWidget(self.credit_label)

        settings_action = QAction("Settings", self)
        settings_action.setShortcut(QKeySequence("Ctrl+,"))
        settings_action.triggered.connect(self._open_settings)
        self.addAction(settings_action)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(40, 40))
        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel(APP_NAME)
        title.setObjectName("AppTitle")
        subtitle = QLabel(f"Download complete YouTube playlists as MP4  ·  by {AUTHOR}")
        subtitle.setObjectName("AppSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        self.ffmpeg_badge = QLabel("Checking FFmpeg…")
        self.ffmpeg_badge.setObjectName("Badge")
        self.ffmpeg_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ffmpeg_badge.mousePressEvent = lambda _e: self._open_settings(tab=2)  # type: ignore[method-assign]
        self.settings_button = make_button("Settings", "ghost", "Settings (Ctrl+,)")
        self.settings_button.clicked.connect(lambda: self._open_settings())

        header.addWidget(logo)
        header.addLayout(titles)
        header.addStretch(1)
        self.about_button = make_button("About", "ghost", f"About {APP_NAME}")
        self.about_button.clicked.connect(self._show_about)
        header.addWidget(self.ffmpeg_badge)
        header.addWidget(self.about_button)
        header.addWidget(self.settings_button)
        return header

    def _build_url_card(self) -> Card:
        card = Card(margins=14, spacing=6)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.url_edit = QLineEdit()
        self.url_edit.setObjectName("UrlInput")
        self.url_edit.setPlaceholderText("Paste a YouTube playlist URL — e.g. https://www.youtube.com/playlist?list=…")
        self.url_edit.setClearButtonEnabled(True)
        self.url_action = self.url_edit.addAction(svg_icon("link", ThemeManager.palette().text_faint),
                                                  QLineEdit.ActionPosition.LeadingPosition)
        self.paste_button = make_button("Paste", None, "Paste from clipboard")
        self.load_button = make_button("Load Playlist", "primary")
        self.load_button.setMinimumWidth(150)
        row.addWidget(self.url_edit, 1)
        row.addWidget(self.paste_button)
        row.addWidget(self.load_button)
        self.url_error = QLabel()
        self.url_error.setObjectName("ErrorText")
        self.url_error.hide()
        card.body.addLayout(row)
        card.body.addWidget(self.url_error)
        return card

    def _build_sidebar(self) -> QWidget:
        content = QWidget()
        content.setObjectName("Transparent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(14)

        self.header_card = PlaylistHeader()
        layout.addWidget(self.header_card)

        # Options
        options = Card(margins=16, spacing=10)
        options.body.addWidget(section_title("Download options"))
        self.quality_combo = QComboBox()
        for label, _ in QUALITY_OPTIONS:
            self.quality_combo.addItem(label)
        self.quality_combo.setCurrentText(self.settings.quality)
        self.quality_combo.setToolTip("If the selected quality is not available, the closest lower "
                                      "quality is downloaded automatically.")
        quality_row = QHBoxLayout()
        quality_label = QLabel("Quality")
        quality_label.setObjectName("Muted")
        quality_row.addWidget(quality_label)
        quality_row.addWidget(self.quality_combo, 1)
        options.body.addLayout(quality_row)
        mp4_note = QLabel("Output: MP4 (H.264/AV1 video + AAC audio)")
        mp4_note.setObjectName("Faint")
        options.body.addWidget(mp4_note)

        self.folder_edit = QLineEdit(self.settings.download_path)
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setToolTip(self.settings.download_path)
        self.browse_button = make_button("", None, "Choose download folder")
        self.browse_button.setFixedWidth(44)
        folder_row = QHBoxLayout()
        folder_row.setSpacing(8)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(self.browse_button)
        options.body.addLayout(folder_row)

        disk_row = QHBoxLayout()
        disk_row.setSpacing(6)
        self.disk_icon = QLabel()
        self.disk_label = QLabel("—")
        self.disk_label.setObjectName("Muted")
        self.open_folder_button = make_button("Open folder", "link")
        disk_row.addWidget(self.disk_icon)
        disk_row.addWidget(self.disk_label, 1)
        disk_row.addWidget(self.open_folder_button)
        options.body.addLayout(disk_row)
        layout.addWidget(options)

        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName("Transparent")

        # Progress + controls
        progress = Card(margins=16, spacing=10)
        progress.body.addWidget(section_title("Overall progress"))
        percent_row = QHBoxLayout()
        self.overall_percent = QLabel("0%")
        self.overall_percent.setObjectName("BigNumber")
        self.overall_counts = QLabel("No downloads yet")
        self.overall_counts.setObjectName("Muted")
        self.overall_counts.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        percent_row.addWidget(self.overall_percent)
        percent_row.addStretch(1)
        percent_row.addWidget(self.overall_counts)
        progress.body.addLayout(percent_row)
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 1000)
        self.overall_bar.setValue(0)
        progress.body.addWidget(self.overall_bar)
        stats_row = QHBoxLayout()
        self.speed_label = QLabel("Speed —")
        self.speed_label.setObjectName("Muted")
        self.eta_label = QLabel("ETA —")
        self.eta_label.setObjectName("Muted")
        stats_row.addWidget(self.speed_label)
        stats_row.addStretch(1)
        stats_row.addWidget(self.eta_label)
        progress.body.addLayout(stats_row)

        self.start_button = make_button("Start Download", "primary")
        self.start_button.setMinimumHeight(42)
        self.pause_button = make_button("Pause")
        self.resume_button = make_button("Resume")
        self.cancel_button = make_button("Cancel", "danger")
        grid = QGridLayout()
        grid.setSpacing(8)
        grid.addWidget(self.start_button, 0, 0, 1, 3)
        grid.addWidget(self.pause_button, 1, 0)
        grid.addWidget(self.resume_button, 1, 1)
        grid.addWidget(self.cancel_button, 1, 2)
        progress.body.addLayout(grid)


        # Progress and controls stay pinned below the scrollable cards so the
        # Start/Pause/Resume/Cancel buttons are always visible.
        sidebar = QWidget()
        sidebar.setObjectName("Transparent")
        sidebar.setFixedWidth(self.SIDEBAR_WIDTH)
        column = QVBoxLayout(sidebar)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(14)
        column.addWidget(scroll, 1)
        column.addWidget(progress)
        return sidebar

    def _build_video_card(self) -> Card:
        card = Card(margins=12, spacing=8)
        header = QHBoxLayout()
        header.setContentsMargins(6, 4, 6, 0)
        self.videos_icon = QLabel()
        header.addWidget(self.videos_icon)
        header.addWidget(section_title("Videos"))
        header.addStretch(1)
        self.list_summary = QLabel("")
        self.list_summary.setObjectName("Muted")
        header.addWidget(self.list_summary)
        card.body.addLayout(header)

        self.video_list = QListView()
        self.video_list.setObjectName("VideoList")
        self.video_list.setModel(self._model)
        self.video_list.setItemDelegate(VideoItemDelegate(self.video_list))
        self.video_list.setUniformItemSizes(True)
        self.video_list.setMouseTracking(True)
        self.video_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.video_list.verticalScrollBar().setSingleStep(24)
        self.video_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.video_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.video_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.video_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.empty_state = EmptyState()
        self.list_stack = QStackedWidget()
        self.list_stack.addWidget(self.empty_state)
        self.list_stack.addWidget(self.video_list)
        card.body.addWidget(self.list_stack, 1)
        return card

    def _refresh_icons(self) -> None:
        p = ThemeManager.palette()
        self.settings_button.setIcon(svg_icon("settings", p.text_muted))
        self.about_button.setIcon(svg_icon("alert", p.text_muted))
        self.paste_button.setIcon(svg_icon("clipboard", p.text_muted))
        self.load_button.setIcon(svg_icon("search", p.accent_text))
        self.browse_button.setIcon(svg_icon("folder", p.text_muted))
        self.start_button.setIcon(svg_icon("download", p.accent_text))
        self.pause_button.setIcon(svg_icon("pause", p.text_muted))
        self.resume_button.setIcon(svg_icon("play", p.text_muted))
        self.cancel_button.setIcon(svg_icon("x", p.danger))
        self.url_action.setIcon(svg_icon("link", p.text_faint))
        self.log_panel.icon.setPixmap(svg_pixmap("terminal", p.text_muted, 16))
        self.log_panel.clear_button.setIcon(svg_icon("trash", p.text_muted, 16))
        self.log_panel.open_button.setIcon(svg_icon("external", p.text_muted, 16))
        self.videos_icon.setPixmap(svg_pixmap("list", p.text_muted, 16))
        self.disk_icon.setPixmap(svg_pixmap("drive", p.text_muted, 16))
        self.empty_state.refresh_icon()
        self.header_card.thumbnail.update()
        self.video_list.viewport().update()

    def _connect_signals(self) -> None:
        self.load_button.clicked.connect(self._load_playlist)
        self.url_edit.returnPressed.connect(self._load_playlist)
        self.url_edit.textChanged.connect(self._clear_url_error)
        self.paste_button.clicked.connect(self._paste_url)
        self.browse_button.clicked.connect(self._browse_folder)
        self.open_folder_button.clicked.connect(lambda: self._open_path(self._output_dir()))
        self.quality_combo.currentTextChanged.connect(self._on_quality_changed)
        self.start_button.clicked.connect(self._start_download)
        self.pause_button.clicked.connect(self._manager.pause)
        self.resume_button.clicked.connect(self._resume_download)
        self.cancel_button.clicked.connect(self._cancel_download)
        self.header_card.estimateRequested.connect(lambda: self._start_size_estimate(force=True))
        self.log_panel.open_button.clicked.connect(lambda: self._open_path(logs_dir() / "app.log"))
        self.video_list.customContextMenuRequested.connect(self._show_context_menu)
        self.video_list.doubleClicked.connect(self._on_item_double_clicked)

        self._model.thumbnailRequested.connect(
            lambda key, url: self._thumbs.request(key, url, VideoItemDelegate.THUMB_LOAD_SIZE))
        self._thumbs.loaded.connect(self._on_thumbnail_loaded)

        self._manager.progress.connect(self._on_item_progress)
        self._manager.statusChanged.connect(self._on_item_status)
        self._manager.itemFinished.connect(self._on_item_finished)
        self._manager.stateChanged.connect(self._on_manager_state)
        self._manager.queueFinished.connect(self._on_queue_finished)

    # ============================================================ playlist
    def _load_playlist(self) -> None:
        if self._manager.is_busy or (self._load_task and self._load_task.running):
            return
        try:
            url, kind = normalize_url(self.url_edit.text())
        except InvalidUrlError as exc:
            self._show_url_error(exc.info.message)
            log.warning("Invalid URL: %s", exc.info.message)
            return
        if kind == "video":
            log.info("This link points to a single video; it will be downloaded on its own.")

        self._cancel_estimate()
        self._thumbs.clear_pending()
        self._playlist = None
        self._model.clear()
        self.header_card.set_playlist(None)
        self.empty_state.show_loading()
        self.list_stack.setCurrentWidget(self.empty_state)
        self.load_button.setText("Loading…")
        self._set_status("Loading playlist…")

        task = playlist_load_task(url)
        task.signals.succeeded.connect(lambda info, t=task: self._on_playlist_loaded(t, info))
        task.signals.failed.connect(lambda exc, t=task: self._on_playlist_failed(t, exc))
        task.signals.finished.connect(lambda t=task: self._on_load_finished(t))
        self._load_task = task.start()
        self._update_controls()

    def _on_playlist_loaded(self, task: BackgroundTask, playlist: PlaylistInfo) -> None:
        if task is not self._load_task:
            return
        self._playlist = playlist
        self._job_rows = []
        self._model.set_items(playlist.videos)
        self.header_card.set_playlist(playlist)
        self.list_stack.setCurrentWidget(self.video_list)
        if playlist.thumbnail_url:
            hq = playlist.thumbnail_url.replace("mqdefault", "hqdefault")
            self._thumbs.request(_HEADER_THUMB_KEY, hq, QSize(640, 360))
        if playlist.unavailable_count:
            log.warning("%d video(s) in this playlist are private, removed or otherwise unavailable "
                        "and will be skipped.", playlist.unavailable_count)
        self._set_status(f"Loaded {playlist.video_count} videos from “{playlist.title}”")
        self._reset_overall()
        self._update_list_summary()
        if self.settings.auto_estimate_size and playlist.available_count <= AUTO_ESTIMATE_LIMIT:
            self._start_size_estimate()
        elif playlist.available_count > AUTO_ESTIMATE_LIMIT:
            self.header_card.estimate_status.setText("Large playlist — click to estimate")

    def _on_playlist_failed(self, task: BackgroundTask, exc: Exception) -> None:
        if task is not self._load_task:
            return
        info = exc.info if isinstance(exc, AppError) else classify_error(exc)
        log.error("Could not load playlist: %s%s", info.message,
                  f" ({info.detail})" if info.detail and info.detail != info.message else "")
        self.empty_state.show_error(info.message)
        self._set_status("Failed to load playlist")
        self._show_error("Couldn't load playlist", info)

    def _on_load_finished(self, task: BackgroundTask) -> None:
        if task is self._load_task:
            self.load_button.setText("Load Playlist")
            self._update_controls()

    def _on_thumbnail_loaded(self, key: str, pixmap: QPixmap) -> None:
        if key == _HEADER_THUMB_KEY:
            self.header_card.thumbnail.set_image(pixmap)
        else:
            self._model.set_thumbnail(key, pixmap)

    # ======================================================= size estimate
    def _start_size_estimate(self, force: bool = False) -> None:
        if not self._playlist:
            return
        self._cancel_estimate()
        jobs = [(row, item.url) for row, item in enumerate(self._model.items())
                if item.is_downloadable and item.status is not DownloadStatus.COMPLETED]
        if not jobs:
            return
        for row, _ in jobs:
            self._model.items()[row].estimated_size = None
        self._model.refresh_all()
        self.header_card.set_size(None)
        self.header_card.estimate_button.setEnabled(False)
        self.header_card.estimate_status.setText(f"Estimating 0/{len(jobs)}…")
        if force:
            log.info("Estimating download size for %d video(s)…", len(jobs))

        task = size_estimate_task(jobs, quality_to_height(self.quality_combo.currentText()),
                                  self.settings.prefer_h264)
        state = {"done": 0, "total": len(jobs)}
        task.signals.progress.connect(lambda payload, t=task, s=state: self._on_estimate(t, s, payload))
        task.signals.finished.connect(lambda t=task: self._on_estimate_finished(t))
        self._estimate_task = task.start()

    def _on_estimate(self, task: BackgroundTask, state: dict[str, int], payload: tuple[int, SizeEstimate]) -> None:
        if task is not self._estimate_task:
            return
        row, estimate = payload
        state["done"] += 1
        item = self._model.item(row)
        if item and item.status not in {DownloadStatus.COMPLETED} and not item.status.is_active:
            changes: dict[str, object] = {"estimated_size": estimate.size}
            if estimate.resolution:
                changes["resolution"] = estimate.resolution
            self._model.update_item(row, **changes)
        self.header_card.estimate_status.setText(f"Estimating {state['done']}/{state['total']}…")
        self._update_size_chip(partial=state["done"] < state["total"])

    def _on_estimate_finished(self, task: BackgroundTask) -> None:
        if task is not self._estimate_task:
            return
        self._estimate_task = None
        self.header_card.estimate_button.setEnabled(True)
        if task.cancelled:
            self.header_card.estimate_status.setText("")
            return
        total, unknown = self._update_size_chip(partial=False)
        text = f"{unknown} unknown" if unknown else "Estimate complete"
        self.header_card.estimate_status.setText(text)
        if total:
            log.info("Estimated download size: %s%s", format_bytes(total),
                     f" ({unknown} video(s) without size information)" if unknown else "")

    def _update_size_chip(self, partial: bool) -> tuple[int, int]:
        items = [i for i in self._model.items() if i.is_downloadable]
        total = sum(i.display_size or 0 for i in items)
        unknown = sum(1 for i in items if not i.display_size)
        self.header_card.set_size(total or None, partial=partial or unknown > 0)
        return total, unknown

    def _cancel_estimate(self) -> None:
        if self._estimate_task:
            self._estimate_task.cancel()
            self._estimate_task = None
            self.header_card.estimate_button.setEnabled(True)
            self.header_card.estimate_status.setText("")

    # ============================================================ download
    def _start_download(self) -> None:
        if not self._playlist or self._manager.is_busy:
            return
        if self._ffmpeg is None:
            if self._ffmpeg_detecting:
                QMessageBox.information(self, APP_NAME, "Still checking for FFmpeg — please try again in a moment.")
            else:
                self._show_ffmpeg_missing()
            return

        output_dir = self._output_dir()
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._show_error("Cannot create folder", ErrorInfo(ErrorKind.PERMISSION, f"{output_dir}\n\n{exc}"))
            return
        if not is_writable(output_dir):
            self._show_error("Folder is not writable", ErrorInfo(
                ErrorKind.PERMISSION, f"Files cannot be written to:\n{output_dir}\n\nChoose another folder."))
            return

        rows = [row for row, item in enumerate(self._model.items())
                if item.is_downloadable and item.status is not DownloadStatus.COMPLETED]
        if not rows:
            QMessageBox.information(self, APP_NAME, "All available videos have already been downloaded.")
            return

        if not self._confirm_disk_space(output_dir, rows):
            return

        try:
            jobs = [
                DownloadJob(
                    row=row,
                    url=self._model.items()[row].url,
                    title=self._model.items()[row].title,
                    outtmpl=build_outtmpl(self.settings.filename_format,
                                          index=self._model.items()[row].index,
                                          total=self._playlist.video_count,
                                          playlist_title=self._playlist.title),
                )
                for row in rows
            ]
        except TemplateError as exc:
            self._show_error("Invalid filename format", ErrorInfo(ErrorKind.UNKNOWN, f"{exc}\n\nFix it in Settings."))
            return

        for row in rows:
            item = self._model.items()[row]
            item.reset_progress()
            item.total_bytes = None
        config = WorkerConfig(
            output_dir=output_dir,
            ffmpeg_location=self._ffmpeg.location,
            max_height=quality_to_height(self.quality_combo.currentText()),
            prefer_h264=self.settings.prefer_h264,
            retry_count=self.settings.retry_count,
        )
        self._job_rows = rows
        self._disk_warning_shown = False
        self._jobs = {job.row: job for job in jobs}
        self._worker_config = config
        self._retry_on_resume.clear()
        self._manager.set_max_concurrent(self.settings.max_concurrent_downloads)
        log.info("Saving to %s — quality: %s", output_dir, self.quality_combo.currentText())
        self._manager.start(jobs, config)
        self._overall_timer.start()
        self._update_overall_progress()

    def _confirm_disk_space(self, output_dir: Path, rows: list[int]) -> bool:
        free = free_space(output_dir)
        if free is None:
            return True
        if free < MIN_FREE_SPACE_BYTES:
            self._show_error("Disk almost full", ErrorInfo(
                ErrorKind.DISK_FULL, f"Only {format_bytes(free)} is free on the selected drive. "
                                     "Free some space or choose another folder."))
            return False
        needed = sum(self._model.items()[r].estimated_size or 0 for r in rows)
        if needed and needed > free:
            answer = QMessageBox.warning(
                self, "Not enough disk space",
                f"The estimated download size is {format_bytes(needed)}, but only {format_bytes(free)} "
                "is free.\n\nStart anyway? Downloads will stop when the disk is full.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            return answer == QMessageBox.StandardButton.Yes
        return True

    def _cancel_download(self) -> None:
        answer = QMessageBox.question(
            self, "Cancel downloads",
            "Cancel all remaining downloads?\n\nCompleted videos are kept; partially downloaded files are removed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._manager.cancel()

    def _on_item_progress(self, row: int, snapshot: ProgressSnapshot) -> None:
        item = self._model.item(row)
        if item is None:
            return
        if snapshot.phase is Phase.STARTING:
            self._model.update_item(row, status=DownloadStatus.FETCHING, message=snapshot.message)
            return
        changes: dict[str, object] = {
            "downloaded_bytes": snapshot.downloaded,
            "speed": snapshot.speed,
            "eta": snapshot.eta,
        }
        if snapshot.total:
            changes["total_bytes"] = snapshot.total
        if snapshot.resolution:
            changes["resolution"] = snapshot.resolution
        if snapshot.phase is Phase.PROCESSING:
            changes.update(status=DownloadStatus.PROCESSING, message=snapshot.message, progress=100.0,
                           speed=None, eta=None)
        else:
            changes.update(status=DownloadStatus.DOWNLOADING, progress=snapshot.percent, message="")
        self._model.update_item(row, **changes)

    def _on_item_status(self, row: int, status: str, message: str) -> None:
        self._model.update_item(row, status=DownloadStatus(status), message=message)

    def _on_item_finished(self, row: int, outcome: str, payload: object) -> None:
        item = self._model.item(row)
        if item is None:
            return
        if outcome == WorkerOutcome.COMPLETED.value and isinstance(payload, DownloadResult):
            self._model.update_item(
                row, status=DownloadStatus.COMPLETED, progress=100.0, speed=None, eta=None,
                filepath=str(payload.filepath),
                resolution=payload.resolution or item.resolution,
                total_bytes=payload.filesize,
                message=("Already downloaded · " if payload.already_existed else "Saved · ") + payload.filepath.name,
            )
        elif outcome == WorkerOutcome.FAILED.value:
            info = payload if isinstance(payload, ErrorInfo) else classify_error(str(payload))
            self._model.update_item(row, status=DownloadStatus.FAILED, speed=None, eta=None, message=info.message)
            if info.kind in _PAUSING_ERRORS:
                self._retry_on_resume.add(row)
                self._handle_fatal_error(info)
        elif outcome == WorkerOutcome.PAUSED.value:
            self._model.update_item(row, status=DownloadStatus.PAUSED, speed=None, eta=None, message="")
        elif outcome == WorkerOutcome.CANCELLED.value:
            item.reset_progress()
            self._model.update_item(row, status=DownloadStatus.CANCELLED, total_bytes=None)
        self._update_list_summary()

    def _resume_download(self) -> None:
        """Resume with the current settings and retry videos that failed for a fixable reason."""
        if self._worker_config is None:
            self._manager.resume()
            return
        config = replace(self._worker_config,
                         ffmpeg_location=self._ffmpeg.location if self._ffmpeg else self._worker_config.ffmpeg_location)
        self._worker_config = config
        retry = [self._jobs[row] for row in sorted(self._retry_on_resume) if row in self._jobs]
        for job in retry:
            self._model.items()[job.row].reset_progress()
            self._model.update_item(job.row, status=DownloadStatus.QUEUED, message="Waiting in queue")
        self._retry_on_resume.clear()
        self._disk_warning_shown = False
        self._manager.resume(config, retry)

    def _handle_fatal_error(self, info: ErrorInfo) -> None:
        """Errors that will affect every remaining video pause the queue."""
        if self._disk_warning_shown:
            return
        self._disk_warning_shown = True
        self._manager.pause()
        log.error("Downloads paused: %s", info.message)
        if info.kind is ErrorKind.FFMPEG_MISSING:
            self._show_ffmpeg_missing()
        else:
            self._show_error("Downloads paused", ErrorInfo(
                info.kind, f"{info.message}\n\nResolve the problem, then press Resume."))

    def _on_manager_state(self, state: str) -> None:
        labels = {
            ManagerState.RUNNING.value: "Downloading…",
            ManagerState.PAUSED.value: "Paused — press Resume to continue",
            ManagerState.STOPPING.value: "Cancelling…",
            ManagerState.IDLE.value: "Ready",
        }
        self._set_status(labels.get(state, state))
        if state == ManagerState.PAUSED.value:
            for row in self._job_rows:
                item = self._model.item(row)
                if item and item.status is DownloadStatus.QUEUED:
                    self._model.update_item(row, message="Paused")
        self._update_controls()
        self._update_overall_progress()

    def _on_queue_finished(self, summary: dict[str, int]) -> None:
        self._overall_timer.stop()
        self._update_overall_progress()
        self._update_list_summary()
        completed, failed, cancelled = summary["completed"], summary["failed"], summary["cancelled"]
        text = f"Finished: {completed} completed, {failed} failed"
        if cancelled:
            text += f", {cancelled} cancelled"
        self._set_status(text)
        QApplication.alert(self)
        self.setWindowTitle(APP_NAME)
        if cancelled and not completed and not failed:
            return
        if failed:
            QMessageBox.warning(self, "Downloads finished",
                                f"{text}.\n\nFailed videos show the reason in the list. "
                                "Press Start Download again to retry them.")
        else:
            box = QMessageBox(QMessageBox.Icon.Information, "Downloads finished",
                              f"{text}.\n\nFiles were saved to:\n{self._output_dir()}", parent=self)
            open_button = box.addButton("Open folder", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() is open_button:
                self._open_path(self._output_dir())

    # ======================================================== overall stats
    def _reset_overall(self) -> None:
        self.overall_bar.setValue(0)
        self.overall_percent.setText("0%")
        self.overall_counts.setText("No downloads yet")
        self.speed_label.setText("Speed —")
        self.eta_label.setText("ETA —")

    def _update_overall_progress(self) -> None:
        items = [self._model.item(r) for r in self._job_rows]
        items = [i for i in items if i is not None]
        if not items:
            return
        done = 0.0
        speed = 0.0
        remaining = 0
        sizes_known = True
        counts = {"completed": 0, "failed": 0}
        for item in items:
            if item.status is DownloadStatus.COMPLETED:
                done += 1
                counts["completed"] += 1
                continue
            if item.status in {DownloadStatus.FAILED, DownloadStatus.CANCELLED}:
                done += 1
                counts["failed"] += item.status is DownloadStatus.FAILED
                continue
            done += item.progress / 100.0
            if item.status is DownloadStatus.DOWNLOADING and item.speed:
                speed += item.speed
            size = item.display_size
            if size:
                remaining += max(0, size - item.downloaded_bytes)
            else:
                sizes_known = False

        fraction = done / len(items)
        self.overall_bar.setValue(int(fraction * 1000))
        self.overall_percent.setText(f"{fraction * 100:.0f}%")
        text = f"{counts['completed']} of {len(items)} completed"
        if counts["failed"]:
            text += f" · {counts['failed']} failed"
        self.overall_counts.setText(text)
        running = self._manager.state is ManagerState.RUNNING
        self.speed_label.setText(f"Speed {format_speed(speed) if running else '—'}")
        eta = remaining / speed if running and speed and sizes_known else None
        self.eta_label.setText(f"ETA {format_eta(eta)}")
        self.queue_label.setText(
            f"Active {self._manager.active_count} · Queued {self._manager.queued_count}" if self._manager.is_busy else "")
        if self._manager.is_busy:
            self.setWindowTitle(f"{fraction * 100:.0f}% — {APP_NAME}")

    def _update_list_summary(self) -> None:
        if not self._playlist:
            self.list_summary.setText("")
            return
        counts = self._model.status_counts()
        parts = [f"{self._playlist.video_count} videos"]
        if counts[DownloadStatus.COMPLETED]:
            parts.append(f"{counts[DownloadStatus.COMPLETED]} done")
        if counts[DownloadStatus.FAILED]:
            parts.append(f"{counts[DownloadStatus.FAILED]} failed")
        if counts[DownloadStatus.UNAVAILABLE]:
            parts.append(f"{counts[DownloadStatus.UNAVAILABLE]} unavailable")
        self.list_summary.setText(" · ".join(parts))

    # ============================================================= controls
    def _update_controls(self) -> None:
        state = self._manager.state
        busy = self._manager.is_busy
        loading = bool(self._load_task and self._load_task.running)
        has_videos = bool(self._playlist and self._playlist.available_count)

        self.start_button.setEnabled(has_videos and not busy and not loading)
        self.pause_button.setEnabled(state is ManagerState.RUNNING)
        self.resume_button.setEnabled(state is ManagerState.PAUSED)
        self.cancel_button.setEnabled(state in {ManagerState.RUNNING, ManagerState.PAUSED})
        for widget in (self.load_button, self.url_edit, self.paste_button):
            widget.setEnabled(not busy and not loading)
        self.quality_combo.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)
        self.header_card.estimate_button.setEnabled(has_videos and not busy and self._estimate_task is None)

        has_failed = any(i.status is DownloadStatus.FAILED for i in self._model.items())
        self.start_button.setText("Retry Failed / Continue" if has_failed and not busy else "Start Download")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    # =============================================================== folder
    def _output_dir(self) -> Path:
        base = Path(self.settings.download_path).expanduser()
        if self._playlist and self.settings.create_playlist_folder and not self._playlist.is_single_video:
            return base / sanitize_filename(self._playlist.title)
        return base

    def _browse_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose download folder", self.settings.download_path,
                                                  QFileDialog.Option.ShowDirsOnly)
        if not folder:
            return
        path = str(Path(folder))
        self._config.update(download_path=path)
        self.folder_edit.setText(path)
        self.folder_edit.setToolTip(path)
        self._update_disk_space()
        log.info("Download folder set to %s", path)

    def _update_disk_space(self) -> None:
        free = free_space(self.settings.download_path)
        if free is None:
            self.disk_label.setText("Free space unknown")
            return
        self.disk_label.setText(f"{format_bytes(free)} free")
        low = free < MIN_FREE_SPACE_BYTES * 5
        self.disk_label.setObjectName("ErrorText" if low else "Muted")
        repolish(self.disk_label)

    def _on_quality_changed(self, label: str) -> None:
        self._config.update(quality=label)
        if self._playlist and any(i.estimated_size for i in self._model.items()):
            if self._playlist.available_count <= AUTO_ESTIMATE_LIMIT:
                self._start_size_estimate()
            else:
                self.header_card.estimate_status.setText("Quality changed — estimate again")

    # =============================================================== ffmpeg
    def _detect_ffmpeg(self) -> None:
        self._ffmpeg_detecting = True
        self.ffmpeg_badge.setText("Checking FFmpeg…")
        self.ffmpeg_badge.setProperty("state", "")
        repolish(self.ffmpeg_badge)
        task = ffmpeg_detect_task(self.settings.ffmpeg_path or None)
        task.signals.succeeded.connect(self._on_ffmpeg_detected)
        task.signals.failed.connect(lambda _exc: self._on_ffmpeg_detected(None))
        self._ffmpeg_task = task.start()

    def _on_ffmpeg_detected(self, info: FFmpegInfo | None) -> None:
        self._ffmpeg_detecting = False
        self._ffmpeg = info
        if info:
            self.ffmpeg_badge.setText(f"✓ FFmpeg {info.short_version}")
            self.ffmpeg_badge.setToolTip(f"{info.ffmpeg_path}\nSource: {info.source}")
            self.ffmpeg_badge.setProperty("state", "ok")
            log.info("FFmpeg %s found (%s)", info.short_version, info.source)
        else:
            self.ffmpeg_badge.setText("✗ FFmpeg missing")
            self.ffmpeg_badge.setToolTip("FFmpeg is required to produce MP4 files. Click to configure.")
            self.ffmpeg_badge.setProperty("state", "error")
            log.error("FFmpeg was not found. It is required to merge video and audio into MP4.")
        repolish(self.ffmpeg_badge)

    def _show_ffmpeg_missing(self) -> None:
        box = QMessageBox(QMessageBox.Icon.Warning, "FFmpeg is required",
                          "FFmpeg was not found on this computer.\n\nYouTube delivers HD video and audio as "
                          "separate streams; FFmpeg merges them into a single MP4 file.\n\n" + install_hint(),
                          parent=self)
        settings_button = box.addButton("Open Settings", QMessageBox.ButtonRole.ActionRole)
        recheck = box.addButton("Check again", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        if box.clickedButton() is settings_button:
            self._open_settings(tab=2)
        elif box.clickedButton() is recheck:
            self._detect_ffmpeg()

    # ============================================================= settings
    def _open_settings(self, tab: int = 0) -> None:
        dialog = SettingsDialog(self.settings, self._ffmpeg, self)
        dialog.tabs.setCurrentIndex(tab)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        old = self.settings
        new = dialog.result_settings()
        self._config.replace_all(new)

        if new.theme != old.theme:
            ThemeManager.apply(QApplication.instance(), new.theme)  # type: ignore[arg-type]
            self._refresh_icons()
        if new.max_concurrent_downloads != old.max_concurrent_downloads:
            self._manager.set_max_concurrent(new.max_concurrent_downloads)
        if new.download_path != old.download_path:
            self.folder_edit.setText(new.download_path)
            self.folder_edit.setToolTip(new.download_path)
            self._update_disk_space()
        if new.quality != old.quality and not self._manager.is_busy:
            self.quality_combo.setCurrentText(new.quality)
        if new.ffmpeg_path != old.ffmpeg_path or self._ffmpeg is None:
            self._detect_ffmpeg()
        log.info("Settings saved")

    # ======================================================== context menu
    def _show_context_menu(self, pos: QPoint) -> None:
        index = self.video_list.indexAt(pos)
        if not index.isValid():
            return
        item = index.data(VideoRoles.ITEM)
        p = ThemeManager.palette()
        menu = QMenu(self)
        open_file = menu.addAction(svg_icon("play", p.text_muted, 16), "Play video")
        open_dir = menu.addAction(svg_icon("folder", p.text_muted, 16), "Show in folder")
        has_file = bool(item.filepath and Path(item.filepath).exists())
        open_file.setEnabled(has_file)
        open_dir.setEnabled(has_file)
        menu.addSeparator()
        browser = menu.addAction(svg_icon("external", p.text_muted, 16), "Open on YouTube")
        copy = menu.addAction(svg_icon("copy", p.text_muted, 16), "Copy video URL")
        if item.message:
            copy_error = menu.addAction(svg_icon("alert", p.text_muted, 16), "Copy status message")
        else:
            copy_error = None
        chosen = menu.exec(self.video_list.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is open_file:
            self._open_path(Path(item.filepath))
        elif chosen is open_dir:
            self._reveal_in_folder(Path(item.filepath))
        elif chosen is browser:
            QDesktopServices.openUrl(QUrl(item.url))
        elif chosen is copy:
            QGuiApplication.clipboard().setText(item.url)
        elif copy_error is not None and chosen is copy_error:
            QGuiApplication.clipboard().setText(item.message)

    def _on_item_double_clicked(self, index) -> None:  # noqa: ANN001
        item = index.data(VideoRoles.ITEM)
        if item and item.filepath and Path(item.filepath).exists():
            self._open_path(Path(item.filepath))

    # ================================================================ misc
    def _paste_url(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if text:
            self.url_edit.setText(text)
            self.url_edit.setFocus()

    def _show_url_error(self, message: str) -> None:
        self.url_error.setText(message)
        self.url_error.show()
        self.url_edit.setProperty("error", True)
        repolish(self.url_edit)

    def _clear_url_error(self) -> None:
        if self.url_error.isVisible():
            self.url_error.hide()
            self.url_edit.setProperty("error", False)
            repolish(self.url_edit)

    def _show_error(self, title: str, info: ErrorInfo) -> None:
        box = QMessageBox(QMessageBox.Icon.Critical if info.kind is not ErrorKind.UNKNOWN else QMessageBox.Icon.Warning,
                          title, info.message, parent=self)
        if info.detail and info.detail != info.message:
            box.setDetailedText(info.detail)
        box.exec()

    def _show_about(self) -> None:
        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<h3>{APP_NAME} <span style='font-weight:400'>v{APP_VERSION}</span></h3>"
            "<p>Download complete YouTube playlists as MP4 files with video and audio merged.</p>"
            f"<p><b>Created by {AUTHOR}</b></p>"
            f"<p>{COPYRIGHT}</p>"
            "<p style='color:gray'>Built with Python, PySide6, yt-dlp and FFmpeg.<br>"
            "Only download content you have the right to download.</p>",
        )

    @staticmethod
    def _open_path(path: Path) -> None:
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        elif path.parent.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    @staticmethod
    def _reveal_in_folder(path: Path) -> None:
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])  # noqa: S603, S607
                return
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(path)])  # noqa: S603, S607
                return
        except OSError:
            pass
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    # ======================================================= drag and drop
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        data = event.mimeData()
        text = data.urls()[0].toString() if data.hasUrls() else data.text()
        if text and not self._manager.is_busy:
            self.url_edit.setText(text.strip())
            self._load_playlist()

    # ====================================================== window state
    def _restore_geometry(self) -> None:
        geometry = self.settings.window_geometry
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        else:
            self.resize(1280, 820)
        splitter = self.settings.splitter_state
        if splitter:
            self.splitter.restoreState(QByteArray.fromBase64(splitter.encode()))

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._manager.is_busy:
            answer = QMessageBox.question(
                self, "Quit while downloading?",
                "Downloads are still running.\n\nQuit anyway? Partially downloaded videos will continue "
                "from where they stopped the next time you download this playlist.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._cancel_estimate()
        if self._load_task:
            self._load_task.cancel()
        self._overall_timer.stop()
        self._disk_timer.stop()
        self._config.update(
            window_geometry=bytes(self.saveGeometry().toBase64()).decode(),
            splitter_state=bytes(self.splitter.saveState().toBase64()).decode(),
        )
        self._manager.shutdown()
        event.accept()
