from __future__ import annotations

import importlib.util
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import requests
import validators
from kisskh_downloader.downloader import Downloader
from kisskh_downloader.helper.decrypt_subtitle import SubtitleDecrypter
from kisskh_downloader.kisskh_api import KissKHApi
from kisskh_downloader.models.drama import Drama, Episode
from kisskh_downloader.models.search import DramaInfo
from kisskh_downloader.models.sub import SubItem
from pydantic import ValidationError

from kisskh_app.config import DEFAULT_BASE_URL, AppConfig
from kisskh_app.subtitles_mux import (
    SUBTITLE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    FfmpegCapabilities,
    burn_subtitle_into_video,
    detect_ffmpeg_capabilities,
    embed_subtitles_in_video,
    find_downloaded_subtitles,
    find_downloaded_video,
)

logger = logging.getLogger(__name__)


@dataclass
class ParsedInput:
    is_url: bool
    drama_id: int | None = None
    episode_id: int | None = None
    episode_number: float | None = None
    query: str = ""


@dataclass
class DramaDetails:
    id: int
    title: str
    description: str
    country: str
    status: str
    type: str
    release_date: str
    episodes_count: int
    episodes: list[Episode]

    @property
    def non_recap_episodes(self) -> list[Episode]:
        return [ep for ep in self.episodes if ep.number == int(ep.number)]

    @property
    def recap_episodes(self) -> list[Episode]:
        return [ep for ep in self.episodes if ep.number != int(ep.number)]


@dataclass
class AuthStatus:
    stream_key_set: bool
    sub_key_set: bool
    playwright_installed: bool
    chromium_installed: bool
    decrypt_key_set: bool
    decrypt_iv_set: bool

    @property
    def has_manual_kkeys(self) -> bool:
        return self.stream_key_set and self.sub_key_set

    @property
    def is_ready(self) -> bool:
        return self.has_manual_kkeys or (self.playwright_installed and self.chromium_installed)

    def summary_text(self) -> str:
        if self.has_manual_kkeys:
            return "Ready (Manual kkeys from env/.env)"
        if self.playwright_installed and self.chromium_installed:
            return "Ready (Auto via Playwright + Chromium)"
        if self.playwright_installed and not self.chromium_installed:
            return "Setup needed (Playwright installed, Chromium missing)"
        return "Setup needed (Install Playwright or set kkeys)"


@dataclass
class DownloadSummary:
    total: int = 0
    downloaded: int = 0
    skipped: int = 0
    unreleased: int = 0
    failed: list[tuple[float, str]] = field(default_factory=list)
    output_folder: Path | None = None
    cancelled: bool = False


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


def sanitize_name(name: str) -> str:
    """Sanitize a drama title for safe cross-platform folder and file names."""
    sanitized = re.sub(r'[\\\0-\037/;:|*?"<>]', "_", name)
    sanitized = sanitized.replace("..", "_")
    cleaned = sanitized.strip(". ") or "_"
    if cleaned.upper() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"{cleaned}_"
    return cleaned


def slugify_title(title: str) -> str:
    """Create a URL-safe slug for KissKH episode referer URLs."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-")
    return slug or "Drama"


def format_episode_tag(num: float) -> str:
    """Format an episode number for filenames (E01, E16.1)."""
    if num == int(num):
        return f"E{int(num):02d}"
    return f"E{num:g}"


def format_episode_num(num: float) -> str:
    """Format an episode number for human display (1, 16.1)."""
    if num == int(num):
        return str(int(num))
    return f"{num:g}"


def parse_user_input(raw: str) -> ParsedInput:
    """Parse either a KissKH drama/episode URL or a search query."""
    cleaned = raw.strip().strip("\"'")
    if not cleaned:
        raise ValueError("Please enter a drama name or KissKH URL.")

    candidate = cleaned
    looks_like_url = (
        candidate.startswith(("http://", "https://"))
        or bool(re.match(r"^(?:www\.)?kisskh\.[a-z]{2,}/", candidate, re.IGNORECASE))
        or ("id=" in candidate and ("/" in candidate or "kisskh" in candidate.lower()))
    )
    if looks_like_url and not candidate.startswith(("http://", "https://")):
        candidate = f"https://{candidate}"

    if looks_like_url and validators.url(candidate):
        parsed = urlparse(candidate)
        params = parse_qs(parsed.query)
        ids = params.get("id")
        if not ids or not ids[0].isdigit():
            raise ValueError(
                "KissKH URL must contain a numeric ?id=... parameter "
                "(e.g. https://kisskh.do/Drama/Show-Name?id=1234)."
            )

        drama_id = int(ids[0])
        ep_ids = params.get("ep")
        episode_id = int(ep_ids[0]) if ep_ids and ep_ids[0].isdigit() else None

        episode_number: float | None = None
        if ep_match := re.search(r"Episode-(\d+(?:\.\d+)?)", parsed.path, re.IGNORECASE):
            episode_number = float(ep_match.group(1))

        return ParsedInput(
            is_url=True,
            drama_id=drama_id,
            episode_id=episode_id,
            episode_number=episode_number,
            query=cleaned,
        )

    return ParsedInput(is_url=False, query=cleaned)


def parse_episode_selection(
    expr: str,
    available_episodes: list[Episode],
    default_ep: float | None = None,
    skip_recap: bool = True,
) -> list[Episode]:
    """Parse flexible episode range expressions into matching Episode objects.

    Supported formats:
      - "" (empty): default_ep if given, else all available episodes
      - "all" / "*": all available episodes
      - "last" / "latest": latest episode
      - "last N": last N episodes
      - "5": single episode 5 (or "16.1")
      - "1-5", "1..5", "1:5", "1 to 5": inclusive range
      - "5-", "5-end", "5..": from 5 to the end
      - "-5", "..5": from start to 5
      - Comma-separated combinations: "1-3, 5, 8-10"
    """
    if not available_episodes:
        return []

    sorted_eps = sorted(available_episodes, key=lambda ep: ep.number)
    by_number: dict[float, Episode] = {ep.number: ep for ep in sorted_eps}
    filtered_pool = [
        ep for ep in sorted_eps if not (skip_recap and ep.number != int(ep.number))
    ]
    if not filtered_pool:
        filtered_pool = sorted_eps

    cleaned = expr.strip().lower()

    if not cleaned:
        if default_ep is not None and default_ep in by_number:
            return [by_number[default_ep]]
        return filtered_pool

    if cleaned in {"all", "*"}:
        return filtered_pool

    if cleaned in {"last", "latest"}:
        return [filtered_pool[-1]]

    if m := re.fullmatch(r"(?:last|latest)\s+(\d+)", cleaned):
        count = int(m.group(1))
        if count <= 0:
            raise ValueError("Episode count must be greater than 0.")
        return filtered_pool[-count:]

    selected_numbers: set[float] = set()
    tokens = [tok.strip() for tok in cleaned.split(",") if tok.strip()]
    if not tokens:
        raise ValueError("Please enter a valid episode selection.")

    for token in tokens:
        normalized = re.sub(r"\s+to\s+", "-", token)
        normalized = normalized.replace("..", "-").replace(":", "-")

        # Single exact episode number (e.g. "3" or "16.1")
        if re.fullmatch(r"\d+(?:\.\d+)?", normalized):
            num = float(normalized)
            if num in by_number:
                selected_numbers.add(num)
            continue

        # Open-ended start: "-5"
        if m := re.fullmatch(r"-(\d+(?:\.\d+)?)", normalized):
            stop = float(m.group(1))
            for ep in filtered_pool:
                if ep.number <= stop:
                    selected_numbers.add(ep.number)
            continue

        # Open-ended end: "5-" or "5-end"
        if m := re.fullmatch(r"(\d+(?:\.\d+)?)-(?:end)?", normalized):
            start = float(m.group(1))
            for ep in filtered_pool:
                if ep.number >= start:
                    selected_numbers.add(ep.number)
            continue

        # Closed range: "1-5"
        if m := re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", normalized):
            start = float(m.group(1))
            stop = float(m.group(2))
            if start > stop:
                raise ValueError(
                    f"Invalid range '{token}': start ({format_episode_num(start)}) "
                    f"cannot be greater than end ({format_episode_num(stop)})."
                )
            for ep in filtered_pool:
                if start <= ep.number <= stop:
                    selected_numbers.add(ep.number)
            continue

        raise ValueError(
            f"Unrecognized episode expression '{token}'. "
            "Try examples like '1-5', '3', '5-', 'last 3', or 'all'."
        )

    return [ep for ep in sorted_eps if ep.number in selected_numbers]


def _playwright_cache_dirs() -> list[Path]:
    dirs: list[Path] = []
    env_path = os.getenv("PLAYWRIGHT_BROWSERS_PATH")
    if env_path and env_path != "0":
        dirs.append(Path(env_path).expanduser())
    if sys.platform == "darwin":
        dirs.append(Path.home() / "Library" / "Caches" / "ms-playwright")
    elif sys.platform == "win32":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            dirs.append(Path(local_app_data) / "ms-playwright")
    else:
        dirs.append(Path.home() / ".cache" / "ms-playwright")
    return dirs


def is_chromium_installed() -> bool:
    for cache_dir in _playwright_cache_dirs():
        if not cache_dir.exists():
            continue
        try:
            for item in cache_dir.iterdir():
                if item.is_dir() and item.name.startswith("chromium"):
                    return True
        except OSError:
            continue
    return False


def check_auth_status() -> AuthStatus:
    playwright_installed = importlib.util.find_spec("playwright") is not None
    chromium_installed = is_chromium_installed() if playwright_installed else False
    return AuthStatus(
        stream_key_set=bool(os.getenv("KISSKH_STREAM_KEY")),
        sub_key_set=bool(os.getenv("KISSKH_SUB_KEY")),
        playwright_installed=playwright_installed,
        chromium_installed=chromium_installed,
        decrypt_key_set=bool(os.getenv("KISSKH_KEY")),
        decrypt_iv_set=bool(os.getenv("KISSKH_INITIALIZATION_VECTOR")),
    )


def get_local_downloaded_episodes(
    output_dir: Path,
    drama_title: str,
    episodes: list[Episode],
    subs_only: bool = False,
) -> set[float]:
    """Return episode numbers that already appear to exist in the output folder."""
    drama_dir_name = sanitize_name(drama_title)
    target_dir = output_dir / drama_dir_name
    if not target_dir.is_dir():
        return set()

    valid_exts = SUBTITLE_EXTENSIONS if subs_only else VIDEO_EXTENSIONS
    found: set[float] = set()
    try:
        entries = list(target_dir.iterdir())
    except OSError:
        return set()

    for ep in episodes:
        ep_tag = format_episode_tag(ep.number)
        prefix = f"{drama_dir_name}_{ep_tag}."
        for entry in entries:
            if not entry.is_file():
                continue
            if entry.name.startswith(prefix) and entry.suffix.lower() in valid_exts:
                try:
                    if entry.stat().st_size > 0:
                        found.add(ep.number)
                        break
                except OSError:
                    continue
    return found


def _filter_subtitles(subtitles: list[SubItem], sub_langs: list[str]) -> list[SubItem]:
    if not sub_langs:
        return []
    wanted = {lang.strip().lower() for lang in sub_langs if lang.strip()}
    if "all" in wanted:
        return list(subtitles)
    return [
        sub
        for sub in subtitles
        if sub.land.strip().lower() in wanted or sub.label.strip().lower() in wanted
    ]


class KissKHService:
    """High-level wrapper over debakarr/kisskh-dl defaulting to kisskh.do."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api = KissKHApi(base_url=self.base_url)
        self.downloader = Downloader(referer=self.base_url)

    def search(self, query: str) -> list[DramaInfo]:
        results = self.api.search_dramas_by_query(query)
        return list(results)

    def get_drama(self, drama_id: int) -> DramaDetails:
        drama_api_url = self.api._drama_api_url(drama_id=drama_id)
        response = self.api._request(drama_api_url)
        raw_data = response.json()

        try:
            drama = Drama.model_validate(raw_data)
            return DramaDetails(
                id=drama.id,
                title=drama.title,
                description=drama.description,
                country=drama.country,
                status=drama.status,
                type=drama.type,
                release_date=drama.release_date,
                episodes_count=drama.episodes_count,
                episodes=list(drama.episodes),
            )
        except ValidationError:
            # Defensive fallback if kisskh.do returns null for optional string fields
            episodes: list[Episode] = []
            for item in raw_data.get("episodes") or []:
                try:
                    episodes.append(Episode.model_validate(item))
                except ValidationError:
                    continue
            episodes.sort(key=lambda ep: ep.number)
            return DramaDetails(
                id=int(raw_data.get("id") or drama_id),
                title=str(raw_data.get("title") or f"Drama_{drama_id}"),
                description=str(raw_data.get("description") or ""),
                country=str(raw_data.get("country") or ""),
                status=str(raw_data.get("status") or ""),
                type=str(raw_data.get("type") or ""),
                release_date=str(raw_data.get("releaseDate") or ""),
                episodes_count=int(raw_data.get("episodesCount") or len(episodes)),
                episodes=episodes,
            )

    def download_episodes(
        self,
        drama: DramaDetails,
        episodes: list[Episode],
        config: AppConfig,
        on_status: Callable[[str], None] | None = None,
    ) -> DownloadSummary:
        emit = on_status or (lambda _msg: None)
        output_root = config.resolved_output_dir()
        drama_dir_name = sanitize_name(drama.title)
        target_dir = output_root / drama_dir_name
        target_dir.mkdir(parents=True, exist_ok=True)

        summary = DownloadSummary(total=len(episodes), output_folder=target_dir)

        decrypter: SubtitleDecrypter | None = None
        if config.decrypt_subtitle:
            key = os.getenv("KISSKH_KEY")
            iv = os.getenv("KISSKH_INITIALIZATION_VECTOR")
            if key and iv:
                decrypter = SubtitleDecrypter(key=key, initialization_vector=iv)
            else:
                emit("[warn] Subtitle decryption is enabled, but KISSKH_KEY / KISSKH_INITIALIZATION_VECTOR are not set. Skipping decryption.")

        existing_eps: set[float] = set()
        if config.skip_existing:
            existing_eps = get_local_downloaded_episodes(
                output_dir=output_root,
                drama_title=drama.title,
                episodes=episodes,
                subs_only=config.subs_only,
            )

        need_subtitles = config.subs_only or bool(config.sub_langs)
        drama_slug = slugify_title(drama.title)
        ffmpeg_caps: FfmpegCapabilities | None = None
        if not config.subs_only and config.subtitle_mode in ("embed", "burn"):
            ffmpeg_caps = detect_ffmpeg_capabilities()

        try:
            for idx, episode in enumerate(episodes, start=1):
                ep_tag = format_episode_tag(episode.number)
                filepath_prefix = target_dir / f"{drama_dir_name}_{ep_tag}"

                if config.skip_existing and episode.number in existing_eps:
                    summary.skipped += 1
                    emit(f"[{idx}/{len(episodes)}] {ep_tag}: Already exists — skipped.")
                    continue

                emit(f"[{idx}/{len(episodes)}] {ep_tag}: Preparing authentication...")
                try:
                    kkeys = self.api.generate_kkeys(
                        drama_id=drama.id,
                        episode_id=episode.id,
                        episode_number=int(episode.number),
                        drama_title=drama_slug,
                    )
                except Exception as exc:
                    msg = f"Auth/kkey error: {exc}"
                    summary.failed.append((episode.number, msg))
                    emit(f"[{idx}/{len(episodes)}] {ep_tag}: Failed — {msg}")
                    continue

                matched_subs: list[SubItem] = []
                if need_subtitles:
                    try:
                        all_subs = self.api.get_subtitles(
                            episode.id, kkeys.get("sub", ""), "all"
                        )
                        if config.subs_only and not config.sub_langs:
                            matched_subs = all_subs
                        else:
                            matched_subs = _filter_subtitles(all_subs, config.sub_langs)

                        if not matched_subs and all_subs:
                            avail = ", ".join(
                                f"{s.land} ({s.label})" for s in all_subs[:8]
                            )
                            emit(
                                f"[{idx}/{len(episodes)}] {ep_tag}: No subtitles matched "
                                f"'{config.formatted_sub_langs()}'. Available: {avail}"
                            )
                    except requests.HTTPError as exc:
                        status_code = exc.response.status_code if exc.response is not None else "?"
                        emit(
                            f"[{idx}/{len(episodes)}] {ep_tag}: Could not fetch subtitles "
                            f"(HTTP {status_code})."
                        )
                        if config.subs_only:
                            summary.failed.append((episode.number, f"Subtitle HTTP {status_code}"))
                            continue
                    except Exception as exc:
                        emit(f"[{idx}/{len(episodes)}] {ep_tag}: Subtitle lookup failed ({exc}).")
                        if config.subs_only:
                            summary.failed.append((episode.number, f"Subtitle error: {exc}"))
                            continue

                if config.subs_only:
                    if not matched_subs:
                        emit(f"[{idx}/{len(episodes)}] {ep_tag}: No matching subtitles to download.")
                        summary.skipped += 1
                        continue
                    try:
                        self._download_subs_safely(matched_subs, str(filepath_prefix), decrypter, emit)
                        summary.downloaded += 1
                        emit(f"[{idx}/{len(episodes)}] {ep_tag}: Subtitles saved.")
                    except Exception as exc:
                        summary.failed.append((episode.number, str(exc)))
                        emit(f"[{idx}/{len(episodes)}] {ep_tag}: Subtitle download failed — {exc}")
                    continue

                # Video + subtitles
                try:
                    video_stream_url = self.api.get_stream_url(
                        episode.id, kkeys.get("stream", "")
                    )
                except requests.HTTPError as exc:
                    status_code = exc.response.status_code if exc.response is not None else "?"
                    msg = f"Stream API returned HTTP {status_code}"
                    if status_code in (401, 403):
                        msg += " (kkey invalid or expired)"
                    summary.failed.append((episode.number, msg))
                    emit(f"[{idx}/{len(episodes)}] {ep_tag}: Failed — {msg}")
                    continue
                except Exception as exc:
                    summary.failed.append((episode.number, str(exc)))
                    emit(f"[{idx}/{len(episodes)}] {ep_tag}: Failed getting stream URL — {exc}")
                    continue

                if not video_stream_url or "tickcounter" in video_stream_url:
                    summary.unreleased += 1
                    emit(f"[{idx}/{len(episodes)}] {ep_tag}: Not released yet — skipped.")
                    continue

                emit(
                    f"[{idx}/{len(episodes)}] {ep_tag}: Downloading video ({config.quality})..."
                )
                try:
                    self.downloader.download_video_from_stream_url(
                        video_stream_url, str(filepath_prefix), config.quality
                    )
                except Exception as exc:
                    summary.failed.append((episode.number, f"Video download error: {exc}"))
                    emit(f"[{idx}/{len(episodes)}] {ep_tag}: Video download failed — {exc}")
                    continue

                if matched_subs:
                    self._download_subs_safely(matched_subs, str(filepath_prefix), decrypter, emit)
                    if config.subtitle_mode in ("embed", "burn") and ffmpeg_caps is not None:
                        self._merge_subtitles_into_video(
                            target_dir=target_dir,
                            stem_prefix=f"{drama_dir_name}_{ep_tag}",
                            matched_subs=matched_subs,
                            mode=config.subtitle_mode,
                            keep_srt=config.keep_separate_srt,
                            ffmpeg_caps=ffmpeg_caps,
                            ep_label=f"[{idx}/{len(episodes)}] {ep_tag}",
                            emit=emit,
                        )

                summary.downloaded += 1
                emit(f"[{idx}/{len(episodes)}] {ep_tag}: Completed.")

        except KeyboardInterrupt:
            summary.cancelled = True
            emit("\nDownload cancelled by user.")
        finally:
            self.api.cleanup()

        return summary

    def _merge_subtitles_into_video(
        self,
        target_dir: Path,
        stem_prefix: str,
        matched_subs: list[SubItem],
        mode: str,
        keep_srt: bool,
        ffmpeg_caps: FfmpegCapabilities,
        ep_label: str,
        emit: Callable[[str], None],
    ) -> None:
        video_path = find_downloaded_video(target_dir, stem_prefix)
        if video_path is None:
            emit(f"{ep_label}: [warn] Video file not found for subtitle {mode}.")
            return

        sub_files = find_downloaded_subtitles(target_dir, stem_prefix)
        if not sub_files:
            emit(f"{ep_label}: [warn] No downloaded subtitle files found to {mode}.")
            return

        label_by_lang = {sub.land.strip().lower(): sub.label for sub in matched_subs}
        sub_entries = [
            (sub_path, lang, label_by_lang.get(lang.strip().lower(), lang))
            for sub_path, lang in sub_files
        ]

        if mode == "embed":
            if not ffmpeg_caps.can_embed or ffmpeg_caps.ffmpeg_path is None:
                emit(f"{ep_label}: [warn] ffmpeg not found — kept separate subtitle files.")
                return
            emit(f"{ep_label}: Embedding subtitles into video container...")
            try:
                out_video = embed_subtitles_in_video(
                    video_path=video_path,
                    sub_entries=sub_entries,
                    ffmpeg_bin=ffmpeg_caps.ffmpeg_path,
                    keep_srt=keep_srt,
                )
                emit(f"{ep_label}: Embedded subtitles into {out_video.name}.")
            except Exception as exc:
                emit(f"{ep_label}: [warn] {exc} (kept separate subtitle files).")
        elif mode == "burn":
            if not ffmpeg_caps.can_burn or ffmpeg_caps.burn_ffmpeg_path is None:
                emit(
                    f"{ep_label}: [warn] ffmpeg with libass ('subtitles' filter) is not available — "
                    "kept separate subtitle files. Install ffmpeg-full or use 'embed' mode."
                )
                return
            primary_sub = sub_entries[0][0]
            all_sub_paths = [entry[0] for entry in sub_entries]
            emit(f"{ep_label}: Baking subtitles ({sub_entries[0][2]}) into video frames...")
            try:
                out_video = burn_subtitle_into_video(
                    video_path=video_path,
                    primary_sub=primary_sub,
                    all_sub_paths=all_sub_paths,
                    ffmpeg_bin=ffmpeg_caps.burn_ffmpeg_path,
                    has_libx264=ffmpeg_caps.has_libx264,
                    has_videotoolbox=ffmpeg_caps.has_videotoolbox,
                    keep_srt=keep_srt,
                )
                emit(f"{ep_label}: Baked subtitles into {out_video.name}.")
            except Exception as exc:
                emit(f"{ep_label}: [warn] {exc} (kept separate subtitle files).")

    def _download_subs_safely(
        self,
        subtitles: list[SubItem],
        filepath_prefix: str,
        decrypter: SubtitleDecrypter | None,
        emit: Callable[[str], None],
    ) -> None:
        for sub in subtitles:
            try:
                self.downloader.download_subtitles([sub], filepath_prefix, decrypter)
            except Exception as exc:
                if decrypter is not None:
                    # Subtitle file was already written raw before decrypt failure;
                    # inform the user without discarding the episode download.
                    emit(
                        f"  [warn] Decryption failed for {sub.label} ({sub.land}): {exc}. "
                        "Kept raw subtitle file."
                    )
                else:
                    emit(f"  [warn] Failed downloading {sub.label} subtitle: {exc}")

    def close(self) -> None:
        self.api.cleanup()
        if self.api.session is not None:
            try:
                self.api.session.close()
            except Exception:
                pass

