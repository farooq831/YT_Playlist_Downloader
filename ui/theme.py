"""Color palettes and the Qt stylesheet built from them."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from models.video import DownloadStatus
from utils.paths import assets_dir


@dataclass(frozen=True, slots=True)
class Palette:
    name: str
    window: str
    surface: str
    surface_alt: str
    surface_hover: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_faint: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_text: str
    success: str
    warning: str
    danger: str
    info: str
    track: str
    log_bg: str

    @property
    def is_dark(self) -> bool:
        return self.name == "dark"


DARK = Palette(
    name="dark",
    window="#0d0f14",
    surface="#151821",
    surface_alt="#1b1f2a",
    surface_hover="#232836",
    border="#262b38",
    border_strong="#343a4a",
    text="#e8eaf0",
    text_muted="#9097a8",
    text_faint="#5c6375",
    accent="#f43f5e",
    accent_hover="#fb5a75",
    accent_pressed="#e11d48",
    accent_text="#ffffff",
    success="#22c55e",
    warning="#f59e0b",
    danger="#ef4444",
    info="#38bdf8",
    track="#262b38",
    log_bg="#10131a",
)

LIGHT = Palette(
    name="light",
    window="#f3f4f8",
    surface="#ffffff",
    surface_alt="#f6f7fa",
    surface_hover="#eceef4",
    border="#e1e4eb",
    border_strong="#cfd4de",
    text="#151923",
    text_muted="#5d6577",
    text_faint="#9aa1b1",
    accent="#e11d48",
    accent_hover="#f43f5e",
    accent_pressed="#be123c",
    accent_text="#ffffff",
    success="#16a34a",
    warning="#d97706",
    danger="#dc2626",
    info="#0284c7",
    track="#e4e7ee",
    log_bg="#fafbfc",
)

_PALETTES = {"dark": DARK, "light": LIGHT}


def status_color(status: DownloadStatus, palette: Palette) -> str:
    """Color used for a status chip and its progress bar."""
    return {
        DownloadStatus.DOWNLOADING: palette.accent,
        DownloadStatus.FETCHING: palette.info,
        DownloadStatus.PROCESSING: palette.info,
        DownloadStatus.RETRYING: palette.warning,
        DownloadStatus.PAUSED: palette.warning,
        DownloadStatus.COMPLETED: palette.success,
        DownloadStatus.FAILED: palette.danger,
        DownloadStatus.UNAVAILABLE: palette.text_faint,
    }.get(status, palette.text_muted)


class ThemeManager:
    """Holds the active palette and applies it to the application."""

    _current: ClassVar[Palette] = DARK

    @classmethod
    def palette(cls) -> Palette:
        return cls._current

    @classmethod
    def apply(cls, app: QApplication, name: str) -> Palette:
        palette = _PALETTES.get(name, DARK)
        cls._current = palette
        app.setStyle("Fusion")
        app.setPalette(_qt_palette(palette))
        app.setStyleSheet(build_stylesheet(palette))
        return palette


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after changing a dynamic property."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def _qt_palette(p: Palette) -> QPalette:
    pal = QPalette()
    roles = {
        QPalette.ColorRole.Window: p.window,
        QPalette.ColorRole.WindowText: p.text,
        QPalette.ColorRole.Base: p.surface_alt,
        QPalette.ColorRole.AlternateBase: p.surface,
        QPalette.ColorRole.Text: p.text,
        QPalette.ColorRole.Button: p.surface_alt,
        QPalette.ColorRole.ButtonText: p.text,
        QPalette.ColorRole.Highlight: p.accent,
        QPalette.ColorRole.HighlightedText: p.accent_text,
        QPalette.ColorRole.ToolTipBase: p.surface,
        QPalette.ColorRole.ToolTipText: p.text,
        QPalette.ColorRole.PlaceholderText: p.text_faint,
        QPalette.ColorRole.Link: p.accent,
        QPalette.ColorRole.Mid: p.border,
        QPalette.ColorRole.Dark: p.border_strong,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(p.text_faint))
    return pal


def _rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def build_stylesheet(p: Palette) -> str:
    icons = assets_dir().joinpath("icons").as_posix()
    chevron = f"{icons}/chevron-down-{'light' if p.is_dark else 'dark'}.svg"
    chevron_up = f"{icons}/chevron-up-{'light' if p.is_dark else 'dark'}.svg"
    check = f"{icons}/check.svg"
    return f"""
* {{ outline: none; }}
QWidget {{ color: {p.text}; font-size: 10pt; }}
QMainWindow, QDialog, QWidget#Central {{ background: {p.window}; }}
QScrollArea {{ background: transparent; border: none; }}
QWidget#Transparent {{ background: transparent; }}

QFrame#Card {{
    background: {p.surface};
    border: 1px solid {p.border};
    border-radius: 14px;
}}
QLabel {{ background: transparent; }}
QLabel#AppTitle {{ font-size: 15pt; font-weight: 700; }}
QLabel#AppSubtitle, QLabel#Muted {{ color: {p.text_muted}; }}
QLabel#Faint {{ color: {p.text_faint}; font-size: 9pt; }}
QLabel#SectionTitle {{ color: {p.text_muted}; font-size: 8.5pt; font-weight: 700; }}
QLabel#PlaylistTitle {{ font-size: 12.5pt; font-weight: 700; }}
QLabel#BigNumber {{ font-size: 18pt; font-weight: 700; }}
QLabel#EmptyTitle {{ font-size: 13pt; font-weight: 700; }}
QLabel#Chip {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 11px;
    padding: 3px 10px;
    color: {p.text_muted};
    font-size: 9pt;
}}
QLabel#Badge {{
    border-radius: 11px; padding: 4px 12px; font-size: 9pt; font-weight: 600;
    background: {p.surface_alt}; color: {p.text_muted}; border: 1px solid {p.border};
}}
QLabel#Badge[state="ok"] {{
    background: {_rgba(p.success, 0.12)}; color: {p.success}; border: 1px solid {_rgba(p.success, 0.35)};
}}
QLabel#Badge[state="error"] {{
    background: {_rgba(p.danger, 0.12)}; color: {p.danger}; border: 1px solid {_rgba(p.danger, 0.35)};
}}
QLabel#ErrorText {{ color: {p.danger}; font-size: 9pt; }}
QLabel#Thumbnail {{ background: {p.surface_alt}; border-radius: 10px; }}

QLineEdit, QComboBox, QSpinBox {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 8px 12px;
    selection-background-color: {p.accent};
    selection-color: {p.accent_text};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {p.border_strong}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {p.accent}; }}
QLineEdit[error="true"] {{ border-color: {p.danger}; }}
QLineEdit:read-only {{ color: {p.text_muted}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{ color: {p.text_faint}; background: {p.surface}; }}
QLineEdit#UrlInput {{ font-size: 10.5pt; padding: 10px 14px; }}

QComboBox {{ padding-right: 30px; }}
QComboBox::drop-down {{ border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("{chevron}"); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{
    background: {p.surface};
    border: 1px solid {p.border_strong};
    border-radius: 8px;
    padding: 4px;
    outline: none;
    selection-background-color: {p.surface_hover};
    selection-color: {p.text};
}}
QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 0 8px; border-radius: 6px; }}

QSpinBox {{ padding-right: 26px; }}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; width: 24px; border: none; background: transparent;
}}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-arrow {{ image: url("{chevron_up}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow {{ image: url("{chevron}"); width: 10px; height: 10px; }}

QPushButton {{
    background: {p.surface_alt};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 8px 16px;
    font-weight: 600;
    color: {p.text};
}}
QPushButton:hover {{ background: {p.surface_hover}; border-color: {p.border_strong}; }}
QPushButton:pressed {{ background: {p.border}; }}
QPushButton:disabled {{ color: {p.text_faint}; background: {p.surface}; border-color: {p.border}; }}
QPushButton[variant="primary"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {p.accent}, stop:1 {p.accent_pressed});
    border: 1px solid {p.accent_pressed};
    color: {p.accent_text};
}}
QPushButton[variant="primary"]:hover {{ background: {p.accent_hover}; border-color: {p.accent_hover}; }}
QPushButton[variant="primary"]:pressed {{ background: {p.accent_pressed}; }}
QPushButton[variant="primary"]:disabled {{
    background: {_rgba(p.accent, 0.25)}; border-color: transparent; color: {_rgba(p.accent_text, 0.55)};
}}
QPushButton[variant="danger"] {{ color: {p.danger}; }}
QPushButton[variant="danger"]:hover {{ background: {_rgba(p.danger, 0.12)}; border-color: {_rgba(p.danger, 0.45)}; }}
QPushButton[variant="danger"]:disabled {{ color: {p.text_faint}; }}
QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; padding: 6px 10px; }}
QPushButton[variant="ghost"]:hover {{ background: {p.surface_hover}; }}
QPushButton[variant="link"] {{
    background: transparent; border: none; padding: 2px 4px; color: {p.accent}; font-weight: 600;
}}
QPushButton[variant="link"]:hover {{ color: {p.accent_hover}; text-decoration: underline; }}
QPushButton[variant="link"]:disabled {{ color: {p.text_faint}; }}

QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid {p.border_strong}; background: {p.surface_alt};
}}
QCheckBox::indicator:hover {{ border-color: {p.accent}; }}
QCheckBox::indicator:checked {{ background: {p.accent}; border-color: {p.accent}; image: url("{check}"); }}

QProgressBar {{
    background: {p.track};
    border: none;
    border-radius: 5px;
    min-height: 10px;
    max-height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    border-radius: 5px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.accent_pressed}, stop:1 {p.accent_hover});
}}
QProgressBar#BusyBar {{ min-height: 4px; max-height: 4px; border-radius: 2px; }}

QListView#VideoList {{ background: transparent; border: none; }}
QPlainTextEdit#LogView {{
    background: {p.log_bg};
    border: 1px solid {p.border};
    border-radius: 10px;
    padding: 6px 8px;
    font-family: "Cascadia Mono", "JetBrains Mono", "Consolas", "Menlo", monospace;
    font-size: 9pt;
    selection-background-color: {_rgba(p.accent, 0.35)};
}}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p.border_strong}; border-radius: 3px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {p.text_faint}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p.border_strong}; border-radius: 3px; min-width: 36px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

QSplitter::handle {{ background: transparent; }}
QSplitter::handle:vertical {{ height: 10px; }}
QSplitter::handle:horizontal {{ width: 10px; }}

QToolTip {{
    background: {p.surface}; color: {p.text}; border: 1px solid {p.border_strong};
    padding: 6px 8px; border-radius: 6px;
}}

QTabWidget::pane {{ border: 1px solid {p.border}; border-radius: 12px; background: {p.surface}; top: -1px; }}
QTabBar::tab {{
    background: transparent; color: {p.text_muted}; padding: 9px 18px; margin-right: 4px;
    border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:hover {{ color: {p.text}; }}
QTabBar::tab:selected {{ color: {p.text}; border-bottom: 2px solid {p.accent}; }}

QMenu {{ background: {p.surface}; border: 1px solid {p.border_strong}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 7px 22px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p.surface_hover}; }}
QMenu::item:disabled {{ color: {p.text_faint}; }}
QMenu::separator {{ height: 1px; background: {p.border}; margin: 4px 6px; }}

QStatusBar {{ background: {p.surface}; border-top: 1px solid {p.border}; color: {p.text_muted}; }}
QStatusBar::item {{ border: none; }}
QStatusBar QLabel {{ color: {p.text_muted}; padding: 0 6px; }}
QMessageBox QLabel {{ color: {p.text}; }}
"""
