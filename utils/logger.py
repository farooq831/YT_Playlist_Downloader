"""Logging setup.

Three sinks are configured:

* a rotating log file in the user's app-data directory (DEBUG and above),
* stderr (WARNING and above, or DEBUG with ``--debug``),
* a Qt bridge that forwards INFO and above to the in-app log panel.

The Qt bridge emits a signal, so records produced on worker threads are
delivered to the GUI thread safely through a queued connection.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QObject, Signal

from utils.paths import logs_dir

LOGGER_NAME = "ytpd"
_FILE_FORMAT = "%(asctime)s [%(levelname)-7s] %(threadName)s %(name)s: %(message)s"


class QtLogEmitter(QObject):
    """Carries log records across threads to the GUI."""

    message = Signal(int, str)  # level, formatted message


class QtLogHandler(logging.Handler):
    """``logging.Handler`` that re-emits records as a Qt signal."""

    def __init__(self, level: int = logging.INFO) -> None:
        super().__init__(level)
        self.emitter = QtLogEmitter()
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401 - Qt naming
        try:
            self.emitter.message.emit(record.levelno, self.format(record))
        except RuntimeError:
            # The emitter was destroyed during shutdown; nothing to do.
            pass
        except Exception:  # pragma: no cover - never let logging crash the app
            self.handleError(record)


def setup_logging(debug: bool = False) -> QtLogHandler:
    """Configure the application logger and return the Qt bridge handler."""
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(logging.DEBUG)
    root.propagate = False
    for handler in list(root.handlers):
        root.removeHandler(handler)

    file_handler = RotatingFileHandler(
        logs_dir() / "app.log", maxBytes=2 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if debug else logging.WARNING)
    console.setFormatter(logging.Formatter(_FILE_FORMAT))
    root.addHandler(console)

    qt_handler = QtLogHandler(logging.INFO)
    root.addHandler(qt_handler)
    return qt_handler


def get_logger(name: str) -> logging.Logger:
    """Return a child of the application logger."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}")
