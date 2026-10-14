"""Settings dialog."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from config.constants import (
    FILENAME_PRESETS,
    MAX_CONCURRENT_LIMIT,
    MAX_RETRY_LIMIT,
    QUALITY_OPTIONS,
)
from config.settings import AppSettings
from core.ffmpeg import FFmpegInfo
from core.filename_template import PLACEHOLDER_HELP, TemplateError, preview
from core.js_runtime import runtime_description
from ui.icons import svg_icon
from ui.theme import ThemeManager, repolish
from ui.widgets import make_button
from workers.background_jobs import ffmpeg_detect_task
from workers.task import BackgroundTask


class SettingsDialog(QDialog):
    """Edits a copy of :class:`AppSettings`; read it back with :meth:`result_settings`."""

    def __init__(self, settings: AppSettings, ffmpeg: FFmpegInfo | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)
        self._original = settings
        self._ffmpeg = ffmpeg
        self._detect_task: BackgroundTask | None = None

        self.tabs = tabs = QTabWidget()
        tabs.addTab(self._general_tab(), "General")
        tabs.addTab(self._downloads_tab(), "Downloads")
        tabs.addTab(self._advanced_tab(), "Advanced")

        self.error_label = QLabel()
        self.error_label.setObjectName("ErrorText")
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        defaults_button = make_button("Restore defaults", "ghost")
        defaults_button.clicked.connect(self._restore_defaults)
        cancel_button = make_button("Cancel")
        cancel_button.clicked.connect(self.reject)
        save_button = make_button("Save", "primary")
        save_button.setDefault(True)
        save_button.clicked.connect(self._on_save)

        buttons = QHBoxLayout()
        buttons.addWidget(defaults_button)
        buttons.addStretch(1)
        buttons.addWidget(cancel_button)
        buttons.addWidget(save_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(tabs)
        layout.addWidget(self.error_label)
        layout.addLayout(buttons)

        self._load(settings)
        self._update_ffmpeg_status(ffmpeg, initial=True)

    # ------------------------------------------------------------------ tabs
    @staticmethod
    def _form() -> tuple[QWidget, QFormLayout]:
        page = QWidget()
        page.setObjectName("Transparent")
        form = QFormLayout(page)
        form.setContentsMargins(18, 18, 18, 18)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(14)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return page, form

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Faint")
        label.setWordWrap(True)
        return label

    def _general_tab(self) -> QWidget:
        page, form = self._form()
        p = ThemeManager.palette()

        self.path_edit = QLineEdit()
        browse = make_button("Browse…")
        browse.setIcon(svg_icon("folder", p.text_muted))
        browse.clicked.connect(self._browse_download_path)
        row = QHBoxLayout()
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        form.addRow("Download folder", row)

        self.subfolder_check = QCheckBox("Create a sub-folder named after the playlist")
        form.addRow("", self.subfolder_check)

        self.filename_combo = QComboBox()
        self.filename_combo.setEditable(True)
        self.filename_combo.addItems(FILENAME_PRESETS)
        self.filename_combo.editTextChanged.connect(self._update_preview)
        self.filename_preview = self._hint("")
        form.addRow("Filename format", self.filename_combo)
        form.addRow("", self.filename_preview)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.addItem("Light", "light")
        form.addRow("Theme", self.theme_combo)
        return page

    def _downloads_tab(self) -> QWidget:
        page, form = self._form()
        self.quality_combo = QComboBox()
        for label, _ in QUALITY_OPTIONS:
            self.quality_combo.addItem(label)
        form.addRow("Default quality", self.quality_combo)

        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, MAX_CONCURRENT_LIMIT)
        form.addRow("Concurrent downloads", self.concurrent_spin)

        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, MAX_RETRY_LIMIT)
        form.addRow("Auto-retry attempts", self.retry_spin)
        form.addRow("", self._hint("Failed downloads caused by network problems are retried "
                                   "automatically and continue from where they stopped."))

        self.h264_check = QCheckBox("Prefer H.264 (best compatibility with all players)")
        form.addRow("Codec", self.h264_check)
        self.estimate_check = QCheckBox("Estimate download size after loading a playlist")
        form.addRow("", self.estimate_check)
        return page

    def _advanced_tab(self) -> QWidget:
        page, form = self._form()
        p = ThemeManager.palette()

        self.ffmpeg_edit = QLineEdit()
        self.ffmpeg_edit.setPlaceholderText("Auto-detect")
        browse = make_button("Browse…")
        browse.setIcon(svg_icon("folder", p.text_muted))
        browse.clicked.connect(self._browse_ffmpeg)
        self.detect_button = make_button("Detect")
        self.detect_button.setIcon(svg_icon("search", p.text_muted))
        self.detect_button.clicked.connect(self._detect_ffmpeg)
        row = QHBoxLayout()
        row.addWidget(self.ffmpeg_edit, 1)
        row.addWidget(browse)
        row.addWidget(self.detect_button)
        form.addRow("FFmpeg location", row)
        self.ffmpeg_status = QLabel()
        self.ffmpeg_status.setObjectName("Badge")
        self.ffmpeg_status.setWordWrap(True)
        form.addRow("", self.ffmpeg_status)

        form.addRow("YouTube engine", self._hint(
            f"JavaScript runtime: {runtime_description()}\n"
            "No YouTube account or sign-in is needed — just paste a link."))
        return page

    # -------------------------------------------------------------- behaviour
    def _load(self, s: AppSettings) -> None:
        self.path_edit.setText(s.download_path)
        self.subfolder_check.setChecked(s.create_playlist_folder)
        self.filename_combo.setEditText(s.filename_format)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(s.theme)))
        self.quality_combo.setCurrentText(s.quality)
        self.concurrent_spin.setValue(s.max_concurrent_downloads)
        self.retry_spin.setValue(s.retry_count)
        self.h264_check.setChecked(s.prefer_h264)
        self.estimate_check.setChecked(s.auto_estimate_size)
        self.ffmpeg_edit.setText(s.ffmpeg_path)
        self._update_preview()

    def result_settings(self) -> AppSettings:
        return replace(
            self._original,
            download_path=self.path_edit.text().strip(),
            create_playlist_folder=self.subfolder_check.isChecked(),
            filename_format=self.filename_combo.currentText().strip(),
            theme=self.theme_combo.currentData(),
            quality=self.quality_combo.currentText(),
            max_concurrent_downloads=self.concurrent_spin.value(),
            retry_count=self.retry_spin.value(),
            prefer_h264=self.h264_check.isChecked(),
            auto_estimate_size=self.estimate_check.isChecked(),
            ffmpeg_path=self.ffmpeg_edit.text().strip(),
        ).validated()

    def _on_save(self) -> None:
        try:
            preview(self.filename_combo.currentText())
        except TemplateError as exc:
            self._show_error(str(exc))
            return
        path = Path(self.path_edit.text().strip()).expanduser()
        if not self.path_edit.text().strip():
            self._show_error("Please choose a download folder.")
            return
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._show_error(f"The download folder cannot be created: {exc}")
            return
        ffmpeg_text = self.ffmpeg_edit.text().strip()
        if ffmpeg_text and not Path(ffmpeg_text).expanduser().exists():
            self._show_error("The FFmpeg location does not exist. Clear it to use auto-detection.")
            return
        self.accept()

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def _update_preview(self) -> None:
        try:
            example = preview(self.filename_combo.currentText())
            self.filename_preview.setText(f"Example: {example}\nPlaceholders: {PLACEHOLDER_HELP}")
            self.error_label.hide()
        except TemplateError as exc:
            self.filename_preview.setText(f"⚠ {exc}\nPlaceholders: {PLACEHOLDER_HELP}")

    def _restore_defaults(self) -> None:
        defaults = AppSettings()
        self._load(replace(defaults, window_geometry=self._original.window_geometry,
                           splitter_state=self._original.splitter_state))

    def _browse_download_path(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose download folder", self.path_edit.text(),
                                                  QFileDialog.Option.ShowDirsOnly)
        if folder:
            self.path_edit.setText(str(Path(folder)))

    def _browse_ffmpeg(self) -> None:
        file, _ = QFileDialog.getOpenFileName(self, "Select the FFmpeg executable", self.ffmpeg_edit.text(),
                                              "FFmpeg (ffmpeg ffmpeg.exe);;All files (*)")
        if file:
            self.ffmpeg_edit.setText(str(Path(file)))
            self._detect_ffmpeg()

    def _detect_ffmpeg(self) -> None:
        self.detect_button.setEnabled(False)
        self.ffmpeg_status.setText("Detecting FFmpeg…")
        self.ffmpeg_status.setProperty("state", "")
        repolish(self.ffmpeg_status)
        task = ffmpeg_detect_task(self.ffmpeg_edit.text().strip() or None)
        task.signals.succeeded.connect(self._update_ffmpeg_status)
        task.signals.failed.connect(lambda _exc: self._update_ffmpeg_status(None))
        task.signals.finished.connect(lambda: self.detect_button.setEnabled(True))
        self._detect_task = task.start()

    def _update_ffmpeg_status(self, info: FFmpegInfo | None, initial: bool = False) -> None:
        if info:
            self._ffmpeg = info
            self.ffmpeg_status.setText(f"✓ FFmpeg {info.short_version} — {info.ffmpeg_path} ({info.source})")
            self.ffmpeg_status.setProperty("state", "ok")
        elif initial and self._ffmpeg is None:
            self.ffmpeg_status.setText("FFmpeg has not been detected yet. Click Detect.")
            self.ffmpeg_status.setProperty("state", "")
        else:
            self.ffmpeg_status.setText("✗ FFmpeg was not found. Install it or select ffmpeg manually.")
            self.ffmpeg_status.setProperty("state", "error")
        repolish(self.ffmpeg_status)
