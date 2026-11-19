# KissGrab (`kisskh.do`)

A simple, frictionless console menu application to grab episode ranges from **`https://kisskh.do`**, powered by [`debakarr/kisskh-dl`](https://github.com/debakarr/kisskh-dl) (`kisskh-downloader`).

## Installation

### Option A: Install Globally via `pipx` (Recommended)

Run `kissgrab` from **any directory or terminal on your system** (macOS, Windows, Linux).

If you don't have `pipx` yet:
- **macOS:** `brew install pipx && pipx ensurepath`
- **Windows:** `winget install pipx` (or `pip install pipx && pipx ensurepath`)
- **Linux:** `sudo apt install pipx && pipx ensurepath`

#### From GitHub:
```bash
pipx install git+https://github.com/CrimsonPiZza/KissGrab.git
```
*(With Playwright browser support for auto-kkey generation:)*
```bash
pipx install "git+https://github.com/CrimsonPiZza/KissGrab.git[browser]"
```

#### From Local Clone:
```bash
git clone https://github.com/CrimsonPiZza/KissGrab.git
cd KissGrab
pipx install .
```

Now you can run:
```bash
kissgrab
```

---

### Option B: Quick Start (Cloned Repository)

#### macOS / Linux
Run the setup script to install Homebrew (if missing on macOS), `ffmpeg`, `.venv`, `kisskh-downloader`, and Playwright + Chromium:

```bash
./setup.sh
```
*(Pass `./setup.sh --full` if you also want `ffmpeg-full` for baked-in/hardcoded subtitles.)*

Launch:
```bash
./run.sh
```

*(Optional) Make `kissgrab` available anywhere without `pipx` by creating a symlink:*
```bash
ln -s "$(pwd)/run.sh" ~/.local/bin/kissgrab
```

#### Windows
Double-click `setup.bat` or run it in Command Prompt / PowerShell to check/install FFmpeg (via `winget` / `scoop` / `choco`), create `.venv`, install `kisskh-downloader`, and set up Playwright + Chromium:

```cmd
setup.bat
```

Launch:
```cmd
run.bat
```

---

### Option C: Python Direct
Auto-activates `.venv` if invoked from system Python:

```bash
python main.py
```

## CLI Usage

Run KissGrab interactively or pass search queries / URLs directly:

```bash
# Launch interactive menu
kissgrab

# Search for a drama immediately
kissgrab "Queen of Tears"

# Open a KissKH drama or episode URL directly
kissgrab "https://kisskh.do/Drama/A-Business-Proposal?id=4608"

# Merge local videos & subtitles without re-downloading (folder or single episode)
kissgrab merge "/path/to/Tigers Sniff the Rose (2026)"
kissgrab merge "/path/to/Tigers Sniff the Rose (2026)_E36.mp4"

# Show version or help
kissgrab --version
kissgrab --help
```

*(When using `./run.sh` or `python main.py`, pass arguments the same way: `./run.sh merge`)*

## Features

- **Main source `https://kisskh.do`** configured by default.
- **One-input search or URL**: type a drama name *or* paste any KissKH drama/episode URL.
- **Live episode inspection**: displays available episodes and any episodes already on disk before prompting for a range.
- **Flexible episode range syntax**: `1-5`, `3`, `5-`, `last 3`, `1-3, 7`, or press `Enter` for all episodes.
- **Skip existing files**: safely resume interrupted range downloads without re-downloading completed episodes.
- **Automatic subtitle integration**: choose between **Separate `.srt`**, **Embed in Video** (muxed track inside `.mp4`/`.mkv` — instant & lossless), or **Bake into Video** (hardcoded permanent subtitles via `ffmpeg-full` / `libass`).
- **Local Merge Tool**: combine previously downloaded videos and `.txt2` / `.srt` / `.vtt` subtitles locally in seconds without re-downloading!
- **Recent series quick-pick**: resume ongoing or partially downloaded shows with one keypress.
- **Frictionless `kkey` setup**: checks Playwright + Chromium or saved `.env` keys (`KISSKH_STREAM_KEY`, `KISSKH_SUB_KEY`) and guides setup right inside the menu.
- **Cross-platform config persistence**:
  - Global installations automatically persist `config.json` and `.env` in standard OS user config directories:
    - **macOS:** `~/Library/Application Support/kissgrab/`
    - **Windows:** `%APPDATA%\kissgrab\`
    - **Linux:** `~/.config/kissgrab/`
  - Local repository runs keep `config.json` and `.env` right in the local project directory.
  - Can be overridden at any time with `KISSGRAB_CONFIG_DIR=/path/to/custom/dir`.

## Requirements

- Python 3.10+
- `ffmpeg` (for `yt-dlp` stream muxing and soft-embedding subtitles inside `.mp4`/`.mkv`; on macOS `ffmpeg-full` adds `libass` for baked-in subtitles, while on Windows `Gyan.FFmpeg` via `winget` already includes `libass`)
- For automatic `kkey` authentication: Playwright + Chromium (`[4] Setup & Tools` in the app menu can install this automatically)
