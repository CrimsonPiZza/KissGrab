# KissKH Episode Range Downloader (`kisskh.do`)

A simple, frictionless console menu application powered by [`debakarr/kisskh-dl`](https://github.com/debakarr/kisskh-dl) (`kisskh-downloader`) using **`https://kisskh.do`** as the main site source.

## Quick Start

### macOS / Linux (First-Time Setup)

Run the included setup script to install Homebrew (if missing on macOS), `ffmpeg`, `.venv`, `kisskh-downloader`, and Playwright + Chromium:

```bash
./setup.sh
```

*(Pass `./setup.sh --full` if you also want `ffmpeg-full` for baked-in/hardcoded subtitles.)*

### Windows (First-Time Setup)

Double-click `setup.bat` or run it in Command Prompt / PowerShell to check/install FFmpeg (via `winget` / `scoop` / `choco`), create `.venv`, install `kisskh-downloader`, and set up Playwright + Chromium:

```cmd
setup.bat
```

### Launch

**macOS / Linux:**
```bash
./run.sh
```

**Windows:**
```cmd
run.bat
```

Or run with Python directly on any OS (auto-activates `.venv` if invoked from system Python):

```bash
python main.py
```

You can also jump straight into searching or opening a URL from the command line:

```bash
./run.sh "Business Proposal"
./run.sh "https://kisskh.do/Drama/A-Business-Proposal?id=4608"
```

## Features

- **Main source `https://kisskh.do`** configured by default.
- **One-input search or URL**: type a drama name *or* paste any KissKH drama/episode URL.
- **Live episode inspection**: displays available episodes and any episodes already on disk before prompting for a range.
- **Flexible episode range syntax**: `1-5`, `3`, `5-`, `last 3`, `1-3, 7`, or press `Enter` for all episodes.
- **Skip existing files**: safely resume interrupted range downloads without re-downloading completed episodes.
- **Automatic subtitle integration**: choose between **Separate `.srt`**, **Embed in Video** (muxed track inside `.mp4`/`.mkv` — instant & lossless), or **Bake into Video** (hardcoded permanent subtitles via `ffmpeg-full` / `libass`).
- **Recent series quick-pick**: resume ongoing or partially downloaded shows with one keypress.
- **Frictionless `kkey` setup**: checks Playwright + Chromium or saved `.env` keys (`KISSKH_STREAM_KEY`, `KISSKH_SUB_KEY`) and guides setup right inside the menu.

## Requirements

- Python 3.10+ and `kisskh-downloader>=0.2.4`
- `ffmpeg` (for `yt-dlp` stream muxing and soft-embedding subtitles inside `.mp4`/`.mkv`; on macOS `ffmpeg-full` adds `libass` for baked-in subtitles, while on Windows `Gyan.FFmpeg` via `winget` already includes `libass`)
- For automatic `kkey` authentication: Playwright + Chromium (`[4] Setup & Tools` in the app menu can install this automatically)

