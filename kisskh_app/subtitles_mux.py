from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".ts", ".webm", ".avi", ".mov", ".m4v", ".flv"}
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}

_LANG_MAP = {
    "en": "eng",
    "eng": "eng",
    "english": "eng",
    "id": "ind",
    "ind": "ind",
    "indonesian": "ind",
    "ms": "msa",
    "may": "msa",
    "msa": "msa",
    "malay": "msa",
    "vi": "vie",
    "vie": "vie",
    "vietnamese": "vie",
    "th": "tha",
    "tha": "tha",
    "thai": "tha",
    "zh": "zho",
    "cn": "zho",
    "chi": "zho",
    "zho": "zho",
    "chinese": "zho",
    "ko": "kor",
    "kr": "kor",
    "kor": "kor",
    "korean": "kor",
    "ja": "jpn",
    "jp": "jpn",
    "jpn": "jpn",
    "japanese": "jpn",
    "ar": "ara",
    "ara": "ara",
    "arabic": "ara",
    "es": "spa",
    "spa": "spa",
    "spanish": "spa",
    "fr": "fra",
    "fre": "fra",
    "fra": "fra",
    "french": "fra",
    "de": "deu",
    "ger": "deu",
    "deu": "deu",
    "german": "deu",
    "pt": "por",
    "por": "por",
    "portuguese": "por",
    "ru": "rus",
    "rus": "rus",
    "russian": "rus",
    "hi": "hin",
    "hin": "hin",
    "hindi": "hin",
    "tl": "tgl",
    "fil": "fil",
    "tagalog": "tgl",
    "filipino": "fil",
}


@dataclass
class FfmpegCapabilities:
    ffmpeg_path: str | None = None
    burn_ffmpeg_path: str | None = None
    has_mov_text: bool = False
    has_libx264: bool = False
    has_videotoolbox: bool = False

    @property
    def can_embed(self) -> bool:
        return self.ffmpeg_path is not None

    @property
    def can_burn(self) -> bool:
        return self.burn_ffmpeg_path is not None and (
            self.has_libx264 or self.has_videotoolbox
        )

    def summary_text(self) -> str:
        if self.can_burn:
            return "Ready (embed + bake)"
        if self.can_embed:
            if sys.platform == "darwin":
                return "Ready (embed; ffmpeg-full needed for bake)"
            return "Ready (embed; libass build needed for bake)"
        return "Not installed (required for video/sub muxing)"


def iso639_2_code(lang: str) -> str:
    cleaned = (lang or "").strip().lower()
    if cleaned in _LANG_MAP:
        return _LANG_MAP[cleaned]
    if len(cleaned) == 3 and cleaned.isalpha():
        return cleaned
    return "und"


def find_brew_binary() -> str | None:
    """Locate Homebrew binary in PATH or standard macOS install prefixes."""
    for raw in (
        shutil.which("brew"),
        "/opt/homebrew/bin/brew",
        "/usr/local/bin/brew",
    ):
        if raw and os.path.isfile(raw) and os.access(raw, os.X_OK):
            return raw
    return None


def find_windows_package_manager() -> tuple[str, str] | None:
    """Locate a Windows package manager (winget, scoop, or choco)."""
    for name in ("winget", "scoop", "choco"):
        path = shutil.which(name)
        if path:
            return name, path
    if sys.platform == "win32":
        local_app = os.getenv("LOCALAPPDATA")
        if local_app:
            winget_exe = Path(local_app) / "Microsoft" / "WindowsApps" / "winget.exe"
            if winget_exe.is_file():
                return "winget", str(winget_exe)
    return None


def _windows_ffmpeg_candidates() -> list[str]:
    candidates: list[str] = []
    local_app = os.getenv("LOCALAPPDATA")
    user_profile = os.getenv("USERPROFILE")
    program_data = os.getenv("ProgramData")

    if user_profile:
        candidates.append(str(Path(user_profile) / "scoop" / "shims" / "ffmpeg.exe"))
    if program_data:
        candidates.append(str(Path(program_data) / "chocolatey" / "bin" / "ffmpeg.exe"))
    if local_app:
        winget_links = Path(local_app) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
        candidates.append(str(winget_links))
        winget_pkgs = Path(local_app) / "Microsoft" / "WinGet" / "Packages"
        if winget_pkgs.is_dir():
            for pkg_dir in winget_pkgs.glob("*FFmpeg*"):
                for exe in pkg_dir.rglob("ffmpeg.exe"):
                    candidates.append(str(exe))
                    break
    return candidates


def _candidate_ffmpeg_binaries() -> list[str]:
    raw_list: list[str | None] = [
        os.getenv("FFMPEG_BIN"),
        shutil.which("ffmpeg"),
    ]
    if sys.platform == "win32":
        raw_list.extend(_windows_ffmpeg_candidates())
    else:
        raw_list.extend([
            "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg",
            "/usr/local/opt/ffmpeg-full/bin/ffmpeg",
            "/opt/homebrew/bin/ffmpeg",
            "/usr/local/bin/ffmpeg",
        ])

    candidates: list[str] = []
    for raw in raw_list:
        if raw and raw not in candidates and os.path.isfile(raw) and os.access(raw, os.X_OK):
            candidates.append(raw)
    return candidates


def _probe_ffmpeg(binary: str) -> tuple[bool, bool, bool, bool]:
    """Return (has_subtitles_filter, has_mov_text, has_libx264, has_videotoolbox)."""
    has_sub_filter = False
    has_mov_text = False
    has_libx264 = False
    has_videotoolbox = False

    try:
        filters_res = subprocess.run(
            [binary, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in filters_res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "subtitles":
                has_sub_filter = True
                break
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        enc_res = subprocess.run(
            [binary, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in enc_res.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                codec = parts[1]
                if codec == "mov_text":
                    has_mov_text = True
                elif codec == "libx264":
                    has_libx264 = True
                elif codec == "h264_videotoolbox":
                    has_videotoolbox = True
    except (OSError, subprocess.SubprocessError):
        pass

    return has_sub_filter, has_mov_text, has_libx264, has_videotoolbox


def detect_ffmpeg_capabilities() -> FfmpegCapabilities:
    candidates = _candidate_ffmpeg_binaries()
    if not candidates:
        return FfmpegCapabilities()

    caps = FfmpegCapabilities(ffmpeg_path=candidates[0])
    for binary in candidates:
        has_sub, has_mov, has_x264, has_vt = _probe_ffmpeg(binary)
        caps.has_mov_text = caps.has_mov_text or has_mov
        caps.has_libx264 = caps.has_libx264 or has_x264
        caps.has_videotoolbox = caps.has_videotoolbox or has_vt
        if has_sub and caps.burn_ffmpeg_path is None:
            caps.burn_ffmpeg_path = binary
            caps.ffmpeg_path = binary

    return caps


def find_downloaded_video(target_dir: Path, stem_prefix: str) -> Path | None:
    if not target_dir.is_dir():
        return None
    prefix = f"{stem_prefix}."
    matches: list[Path] = []
    for entry in target_dir.iterdir():
        if not entry.is_file():
            continue
        if (
            entry.name.startswith(prefix)
            and entry.suffix.lower() in VIDEO_EXTENSIONS
            and ".muxing." not in entry.name
            and ".burning." not in entry.name
        ):
            try:
                if entry.stat().st_size > 0:
                    matches.append(entry)
            except OSError:
                continue
    if not matches:
        return None
    # Prefer .mp4 or .mkv if multiple exist
    matches.sort(key=lambda p: (0 if p.suffix.lower() == ".mp4" else 1, p.name))
    return matches[0]


def find_downloaded_subtitles(target_dir: Path, stem_prefix: str) -> list[tuple[Path, str]]:
    """Find subtitle files matching stem_prefix.<lang>.<ext> -> list of (path, lang)."""
    if not target_dir.is_dir():
        return []
    prefix = f"{stem_prefix}."
    found: list[tuple[Path, str]] = []
    for entry in sorted(target_dir.iterdir(), key=lambda p: p.name):
        if not entry.is_file():
            continue
        if entry.name.startswith(prefix) and entry.suffix.lower() in SUBTITLE_EXTENSIONS:
            remainder = entry.name[len(prefix) : -len(entry.suffix)]
            lang = remainder.strip(".") or "und"
            try:
                if entry.stat().st_size > 0:
                    found.append((entry, lang))
            except OSError:
                continue
    return found


def escape_ffmpeg_filter_path(path: Path) -> str:
    """Escape a filesystem path for FFmpeg's filtergraph option syntax."""
    # Forward slashes avoid Windows backslash escaping quirks inside -vf subtitles='...'
    s = path.resolve().as_posix()
    s = s.replace("\\", "\\\\")
    s = s.replace(":", "\\:")
    s = s.replace("'", "\\'")
    s = s.replace("[", "\\[")
    s = s.replace("]", "\\]")
    return s


def _replace_video_atomically(original_video: Path, temp_output: Path, final_ext: str) -> Path:
    final_path = original_video.with_suffix(final_ext)
    if final_path == original_video:
        temp_output.replace(final_path)
    else:
        temp_output.replace(final_path)
        try:
            original_video.unlink(missing_ok=True)
        except OSError:
            pass
    return final_path


def embed_subtitles_in_video(
    video_path: Path,
    sub_entries: list[tuple[Path, str, str]],
    ffmpeg_bin: str,
    keep_srt: bool = False,
) -> Path:
    """Mux subtitle tracks into the video container without re-encoding.

    sub_entries: list of (sub_path, lang_code, label)
    """
    if not sub_entries:
        return video_path

    use_mkv_first = video_path.suffix.lower() in {".mkv", ".webm"}
    attempts = [(".mkv", "srt")] if use_mkv_first else [(".mp4", "mov_text"), (".mkv", "srt")]

    last_err = ""
    for target_ext, sub_codec in attempts:
        temp_output = video_path.with_name(f"{video_path.stem}.muxing{target_ext}")
        cmd = [ffmpeg_bin, "-y", "-hide_banner", "-loglevel", "error", "-i", str(video_path)]
        for sub_path, _, _ in sub_entries:
            cmd.extend(["-i", str(sub_path)])

        cmd.extend(["-map", "0:v", "-map", "0:a?"])
        for idx in range(len(sub_entries)):
            cmd.extend(["-map", f"{idx + 1}:0"])

        cmd.extend(["-c:v", "copy", "-c:a", "copy", "-c:s", sub_codec])
        if target_ext == ".mp4":
            cmd.extend(["-movflags", "+faststart"])

        for idx, (_, lang, label) in enumerate(sub_entries):
            iso_lang = iso639_2_code(lang)
            cmd.extend([f"-metadata:s:s:{idx}", f"language={iso_lang}"])
            if label:
                cmd.extend([f"-metadata:s:s:{idx}", f"title={label}"])
        cmd.extend(["-disposition:s:0", "default"])
        cmd.append(str(temp_output))

        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode == 0 and temp_output.is_file() and temp_output.stat().st_size > 0:
            final_video = _replace_video_atomically(video_path, temp_output, target_ext)
            if not keep_srt:
                for sub_path, _, _ in sub_entries:
                    try:
                        sub_path.unlink(missing_ok=True)
                    except OSError:
                        pass
            return final_video

        last_err = (res.stderr or res.stdout or f"ffmpeg exited with code {res.returncode}").strip()
        try:
            temp_output.unlink(missing_ok=True)
        except OSError:
            pass

    raise RuntimeError(f"Failed to embed subtitles with ffmpeg: {last_err}")


def burn_subtitle_into_video(
    video_path: Path,
    primary_sub: Path,
    all_sub_paths: list[Path],
    ffmpeg_bin: str,
    has_libx264: bool = True,
    has_videotoolbox: bool = False,
    keep_srt: bool = False,
) -> Path:
    """Hardcode (bake) a subtitle file permanently onto the video frames."""
    temp_output = video_path.with_name(f"{video_path.stem}.burning.mp4")
    escaped_sub = escape_ffmpeg_filter_path(primary_sub)

    if has_libx264:
        video_codec_args = [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
        ]
    elif has_videotoolbox:
        video_codec_args = ["-c:v", "h264_videotoolbox", "-q:v", "65"]
    else:
        raise RuntimeError("No supported H.264 encoder (libx264 or h264_videotoolbox) found in ffmpeg.")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-stats",
        "-i",
        str(video_path),
        "-vf",
        f"subtitles='{escaped_sub}'",
        *video_codec_args,
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        str(temp_output),
    ]

    res = subprocess.run(cmd, check=False)
    if res.returncode != 0 or not temp_output.is_file() or temp_output.stat().st_size == 0:
        try:
            temp_output.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError(f"ffmpeg failed while baking subtitles (exit code {res.returncode}).")

    final_video = _replace_video_atomically(video_path, temp_output, ".mp4")
    if not keep_srt:
        for sub_path in all_sub_paths:
            try:
                sub_path.unlink(missing_ok=True)
            except OSError:
                pass
    return final_video

