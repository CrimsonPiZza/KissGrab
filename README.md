# KissKH Episode Range Downloader (`kisskh.do`)

A simple, frictionless console menu application powered by [`debakarr/kisskh-dl`](https://github.com/debakarr/kisskh-dl) (`kisskh-downloader`) using **`https://kisskh.do`** as the main site source.

## Quick Start

```bash
./run.sh
```

Or run with Python directly (auto-activates `.venv` if invoked from system Python):

```bash
python3 main.py
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

- `kisskh-downloader>=0.2.4` (already installed in `.venv`)
- `ffmpeg` (already installed via Homebrew for `yt-dlp` stream muxing and soft-embedding subtitles inside `.mp4`/`.mkv`; for **baked-in / hardcoded** subtitles, `ffmpeg-full` with `libass` is required and can be installed via Homebrew right from the menu)
- For automatic `kkey` authentication: Playwright + Chromium (`[4] Auth / kkey & Playwright Setup` in the app menu can install this automatically, or run `.venv/bin/pip install playwright && .venv/bin/playwright install chromium`)

