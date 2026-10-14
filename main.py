"""Entry point: ``python main.py`` (add ``--debug`` for verbose console logs).

YT Playlist Downloader — created by Muhammad Farooq.
© 2026 Muhammad Farooq. All rights reserved.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info < (3, 11):  # noqa: UP036 - explicit, friendly runtime check
    sys.exit("YT Playlist Downloader requires Python 3.11 or newer.")

# Make the project packages importable regardless of the working directory.
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.application import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
