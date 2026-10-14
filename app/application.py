"""Application bootstrap: Qt app, logging, configuration, theme, main window."""

from __future__ import annotations

import argparse
import sys
import traceback
from types import TracebackType

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from config.constants import APP_ID, APP_NAME, APP_VERSION, AUTHOR, COPYRIGHT, ORG_NAME
from config.settings import ConfigManager
from ui.icons import app_icon
from ui.main_window import MainWindow
from ui.theme import ThemeManager
from utils.logger import get_logger, setup_logging

log = get_logger("app")


class Application:
    """Owns the ``QApplication`` and the main window."""

    def __init__(self, argv: list[str]) -> None:
        args = self._parse_args(argv)
        self._set_windows_app_id()
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

        self.qt_app = QApplication(argv[:1])
        self.qt_app.setApplicationName(APP_NAME)
        self.qt_app.setApplicationDisplayName(APP_NAME)
        self.qt_app.setApplicationVersion(APP_VERSION)
        self.qt_app.setOrganizationName(ORG_NAME)
        self.qt_app.setWindowIcon(app_icon())
        self.qt_app.setFont(self._default_font())

        self.log_handler = setup_logging(debug=args.debug)
        sys.excepthook = self._excepthook
        log.debug("Starting %s %s by %s on Python %s", APP_NAME, APP_VERSION, AUTHOR, sys.version.split()[0])
        log.info("%s v%s — %s", APP_NAME, APP_VERSION, COPYRIGHT)

        self.config = ConfigManager()
        settings = self.config.load()
        ThemeManager.apply(self.qt_app, settings.theme)

        self.window = MainWindow(self.config, self.log_handler)

    def run(self) -> int:
        self.window.show()
        return self.qt_app.exec()

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _parse_args(argv: list[str]) -> argparse.Namespace:
        parser = argparse.ArgumentParser(prog="ytpd", description=APP_NAME)
        parser.add_argument("--debug", action="store_true", help="verbose logging to the console")
        args, _unknown = parser.parse_known_args(argv[1:])
        return args

    @staticmethod
    def _default_font() -> QFont:
        if sys.platform == "win32":
            family = "Segoe UI Variable Text"
            font = QFont(family, 10)
            if font.exactMatch():
                return font
            return QFont("Segoe UI", 10)
        if sys.platform == "darwin":
            return QFont(".AppleSystemUIFont", 13)
        return QFont("Inter", 10) if QFont("Inter").exactMatch() else QApplication.font()

    @staticmethod
    def _set_windows_app_id() -> None:
        """Give the process its own taskbar identity (correct icon grouping)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{ORG_NAME}.{APP_ID}.{APP_VERSION}")
        except (AttributeError, OSError):
            pass

    @staticmethod
    def _excepthook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Unhandled exception:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        if QApplication.instance():
            QMessageBox.critical(None, APP_NAME,
                                 f"An unexpected error occurred:\n\n{exc}\n\nDetails were written to the log file.")


def main(argv: list[str] | None = None) -> int:
    return Application(list(sys.argv if argv is None else argv)).run()
