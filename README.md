# YT Playlist Downloader

**Created by Muhammad Farooq** · © 2026 Muhammad Farooq. All rights reserved.

A modern desktop app (Python + PySide6 + yt-dlp) that downloads an entire YouTube playlist as **MP4 files with audio**.

- Dark theme by default, plus a light theme.
- Thumbnails, per-video progress, speed and ETA.
- Pause, resume and cancel.
- Automatic retries.
- Interrupted downloads continue where they stopped.

## Features

| Area | What you get |
|---|---|
| **Playlist** | Paste a playlist URL. Watch URLs with `&list=`, single videos and channel `/videos` pages also work. Shows title, thumbnail, video count, total duration and estimated size. |
| **Video list** | Each row shows a thumbnail, title, duration, resolution, file size, speed, ETA, progress and a status chip. The list is painted by a delegate, so it stays smooth with thousands of videos. Right-click a video to play it, show it in its folder, open it on YouTube or copy its URL. |
| **Quality** | Best Available, 2160p, 1440p, 1080p, 720p, 480p or 360p. If the chosen quality doesn't exist, the closest lower one is used. |
| **Format** | **MP4 only.** Video and audio are always merged into a single `.mp4`. The app never keeps audio-only files, WEBM or MKV. |
| **Engine** | Uses the yt-dlp Python API. Runs 1–8 downloads at once on a `QThreadPool`. Retries with exponential back-off. Partial downloads are kept as `.part` files and resumed with HTTP range requests. |
| **FFmpeg** | Found automatically from Settings, `PATH`, winget, scoop, chocolatey, Homebrew or `imageio-ffmpeg`. It is checked by running it, and the result shows in the header badge. |
| **Storage** | Native folder picker. The last folder is remembered. Shows free disk space and warns before starting if the estimated size won't fit. |
| **Errors** | Clear messages for invalid URLs, private playlists and videos, removed videos, age restrictions, region blocks, members-only videos, network errors, rate limiting, disk full, permission problems and missing FFmpeg. |
| **Settings** | Download folder, optional playlist sub-folder (off by default), filename format (with live preview), theme, default quality, concurrent downloads, retry count, H.264 preference, auto size estimate and FFmpeg path. |

## Installation

### 1. Python 3.11 or newer

Check your version with `python --version`.

### 2. Create a virtual environment and install dependencies

```bash
cd YT_Playlist_Downloader
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

> **Windows tip:** if `pip` fails while installing PySide6 with a path-length error, create the venv at a short path, such as `C:\venvs\ytpd`. Or enable long paths in Windows.

### 3. FFmpeg

FFmpeg merges the separate video and audio streams into MP4.

`requirements.txt` includes `imageio-ffmpeg`, which ships a working FFmpeg binary, so **the app works without any extra step**. If you'd rather use a system-wide FFmpeg:

| OS | Command |
|---|---|
| Windows | `winget install Gyan.FFmpeg` (or `choco install ffmpeg` / `scoop install ffmpeg`) |
| macOS | `brew install ffmpeg` |
| Debian/Ubuntu | `sudo apt install ffmpeg` |

You can also put `ffmpeg(.exe)` in a `bin/` folder next to `main.py`, or select it in **Settings › Advanced**.

### 4. Nothing else to install

**No YouTube account, sign-in or cookies are needed.** `requirements.txt` installs the `deno` package, a JavaScript runtime that yt-dlp uses to solve YouTube's player challenges. The app finds it automatically. A Deno or Node.js already on your `PATH` also works.

### 5. Run

```bash
python main.py            # normal start
python main.py --debug    # verbose logging in the console
```

## Usage

1. Paste a playlist URL. You can also drag a link onto the window or use **Paste**.
2. Press **Load Playlist**.
3. Pick a **quality** and a **download folder**.
4. Press **Start Download**. Use **Pause**, **Resume** and **Cancel** at any time.
   - **Pause** stops the active downloads and keeps their partial data. **Resume** continues from the same byte.
   - **Cancel** removes partial files. Completed videos are kept.
   - Run **Start Download** again to retry failed videos. Finished files are detected and skipped.

### No sign-in needed: how YouTube's bot check is avoided

YouTube often blocks its normal web player with *"Sign in to confirm you're not a bot"*. The app doesn't ask users to sign in. Instead it requests videos the way an **embedded player** does, which YouTube doesn't block and which still offers every quality up to 4K. Two clients are added as back-ups for videos that can't be embedded:

1. `web_embedded` + `mweb` + `android`: full quality.
2. If YouTube still refuses a video, the app retries it automatically with `android` alone. This works almost everywhere but is limited to 360p.

The logic lives in [core/ytdlp_common.py](core/ytdlp_common.py).

Some videos can't be downloaded by anyone without an account. These include private, members-only and age-restricted videos. They're marked **Failed** with a clear reason, and the rest of the playlist keeps downloading.

## How MP4-only is guaranteed

The format string, from [core/format_selector.py](core/format_selector.py), is an ordered list of alternatives. **Every alternative includes video**, so audio-only is impossible:

```
bv[height<=H][ext=mp4]+ba[ext=m4a] / bv[height<=H][ext=mp4]+ba / b[height<=H][ext=mp4]
/ bv[height<=H]+ba[ext=m4a] / bv[height<=H]+ba / b[height<=H] / wv+ba / w
```

On top of that:

- `merge_output_format="mp4"` makes FFmpeg merge into MP4, never MKV.
- `FFmpegVideoConvertor(preferedformat="mp4")` converts any non-MP4 single-file fallback.
- The final path is checked to end in `.mp4`.
- yt-dlp deletes intermediate stream files after merging (`keepvideo=False`).

## Project structure

```
YT_Playlist_Downloader/
├── main.py                     # entry point
├── requirements.txt
├── app/
│   └── application.py          # QApplication bootstrap, logging, theme, excepthook
├── ui/
│   ├── main_window.py          # main window: layout + coordination
│   ├── settings_dialog.py      # tabbed settings dialog
│   ├── video_delegate.py       # custom-painted video rows
│   ├── widgets.py              # Card, PlaylistHeader, LogPanel, EmptyState…
│   ├── theme.py                # palettes + Qt stylesheet (dark / light)
│   └── icons.py                # theme-colored SVG icons
├── core/
│   ├── playlist_parser.py      # URL validation + flat playlist extraction
│   ├── downloader.py           # single-video yt-dlp engine (pause/cancel/progress)
│   ├── download_manager.py     # queue + QThreadPool orchestration
│   ├── format_selector.py      # MP4-only format selection
│   ├── ffmpeg.py               # FFmpeg detection and verification
│   ├── size_estimator.py       # download-size estimation
│   ├── filename_template.py    # {index} - {title} → yt-dlp templates
│   ├── errors.py               # error classification + friendly messages
│   ├── ytdlp_common.py         # yt-dlp options + no-sign-in client fallback
│   └── js_runtime.py           # finds the bundled Deno (or Deno/Node on PATH)
├── workers/
│   ├── download_worker.py      # QRunnable with retry policy
│   ├── thumbnail_loader.py     # async QNetworkAccessManager image loader
│   ├── background_jobs.py      # playlist / FFmpeg / size-estimate tasks
│   └── task.py                 # generic daemon-thread task with Qt signals
├── models/
│   ├── video.py                # VideoItem, PlaylistInfo, DownloadStatus
│   └── video_list_model.py     # QAbstractListModel with LRU thumbnail cache
├── config/
│   ├── constants.py            # app constants, quality & filename presets
│   └── settings.py             # AppSettings dataclass + JSON ConfigManager
├── utils/
│   ├── logger.py               # rotating file log + Qt log bridge
│   ├── formatting.py           # bytes / speed / duration / filename helpers
│   ├── disk.py                 # free space + writability checks
│   └── paths.py                # config, log and asset locations
└── assets/
    ├── icon.svg
    └── icons/                  # stylesheet chevrons / check mark
```

### Threading model

- **GUI thread:** widgets, the model and the `DownloadManager`. It never does network or disk-heavy work.
- **QThreadPool:** one `DownloadWorker` per active video, up to the concurrency limit. Workers talk to the GUI only through signals (queued connections), and progress updates are throttled to 4 per second per video.
- **Daemon threads:** playlist loading, FFmpeg detection and size estimation run here, so they never block application exit.
- **Thumbnails:** fetched asynchronously by `QNetworkAccessManager` and center-cropped. They are lazy-loaded when a row first becomes visible and kept in an LRU cache of 400 entries.

## Files written by the app

| What | Windows | macOS | Linux |
|---|---|---|---|
| Config | `%APPDATA%\YTPlaylistDownloader\config.json` | `~/Library/Application Support/YTPlaylistDownloader/` | `~/.config/YTPlaylistDownloader/` |
| Logs | `…\YTPlaylistDownloader\logs\app.log` (rotating, 5 × 2 MB) | same folder | same folder |

## Optional: build a standalone executable

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --name "YT Playlist Downloader" --add-data "assets;assets" --collect-all deno --collect-all imageio_ffmpeg --collect-all yt_dlp_ejs main.py
```

On macOS and Linux, use `--add-data "assets:assets"`.

## Troubleshooting

| Problem | Fix |
|---|---|
| "FFmpeg missing" badge | Install FFmpeg (see above) or select the binary in Settings › Advanced. |
| Videos fail with "temporarily limiting downloads" | YouTube is rate-limiting your network. Wait a while, lower *Concurrent downloads* in Settings, then press **Start Download** again. |
| Requested 4K but got 1080p | That video has no 4K stream. The app picks the next lower available quality. |
| Downloads suddenly fail | Update yt-dlp, since YouTube changes often: `pip install -U "yt-dlp[default]"`. |

## Author

Designed and developed by **Muhammad Farooq**.
© 2026 Muhammad Farooq. All rights reserved.

## Legal

Only download content you have the right to download. Respect YouTube's Terms of Service and the copyright of content creators.
