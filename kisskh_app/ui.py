from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import click
import requests
from kisskh_downloader.models.drama import Episode
from kisskh_downloader.models.search import DramaInfo

from kisskh_app.client import (
    AuthStatus,
    DramaDetails,
    KissKHService,
    check_auth_status,
    format_episode_num,
    format_episode_tag,
    get_local_downloaded_episodes,
    parse_episode_selection,
    parse_user_input,
    sanitize_name,
)
from kisskh_app.config import (
    DEFAULT_BASE_URL,
    VALID_QUALITIES,
    VALID_SUBTITLE_MODES,
    AppConfig,
    update_env_vars,
)
from kisskh_app.subtitles_mux import detect_ffmpeg_capabilities


def _c(text: str, fg: str | None = None, bold: bool = False, dim: bool = False) -> str:
    return click.style(text, fg=fg, bold=bold, dim=dim)


def _echo(text: str = "") -> None:
    click.echo(text)


def _clear_screen() -> None:
    click.clear()


def _divider(char: str = "─", width: int = 64) -> None:
    _echo(_c(char * width, dim=True))


def _banner(title: str, width: int = 64, clear: bool = True) -> None:
    if clear:
        _clear_screen()
    _echo(_c("=" * width, fg="cyan"))
    _echo(_c(f"  {title}", fg="cyan", bold=True))
    _echo(_c("=" * width, fg="cyan"))


def _show_flash(flash: tuple[str, str] | None) -> None:
    if flash:
        msg, color = flash
        _echo(_c(f"  {msg}", fg=color, bold=(color == "red")))
        _divider()


def _prompt(label: str, default: str | None = None) -> str:
    try:
        raw = input(label)
    except EOFError:
        return "" if default is None else default
    stripped = raw.strip()
    if not stripped and default is not None:
        return default
    return stripped


def _pause(msg: str = "Press Enter to continue...") -> None:
    try:
        input(_c(f"\n{msg}", dim=True))
    except (EOFError, KeyboardInterrupt):
        _echo()


def _mask_secret(val: str | None) -> str:
    if not val:
        return "Not set"
    if len(val) <= 10:
        return "*" * len(val)
    return f"{val[:6]}...{val[-4:]}"


def _install_playwright_flow() -> bool:
    """Install playwright Python package (if missing) and Chromium browser."""
    status = check_auth_status()
    if not status.playwright_installed:
        _echo(_c("\nInstalling playwright into the active Python environment...", fg="cyan"))
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "playwright"],
            check=False,
        )
        if res.returncode != 0:
            _echo(_c("Failed to install playwright via pip.", fg="red"))
            return False

    _echo(_c("\nInstalling Playwright Chromium browser...", fg="cyan"))
    res = subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=False,
    )
    if res.returncode != 0:
        _echo(_c("Failed to install Chromium via playwright.", fg="red"))
        return False

    _echo(_c("Playwright + Chromium installed successfully!", fg="green", bold=True))
    return True


def _configure_manual_kkeys() -> bool:
    _echo()
    _echo("Paste your kkey tokens (leave blank to cancel):")
    stream_key = _prompt("  KISSKH_STREAM_KEY : ")
    if not stream_key:
        return False
    sub_key = _prompt("  KISSKH_SUB_KEY    : ")
    if not sub_key:
        return False

    update_env_vars({"KISSKH_STREAM_KEY": stream_key, "KISSKH_SUB_KEY": sub_key})
    return True


def _configure_decrypt_keys(config: AppConfig) -> bool:
    _echo()
    _echo("Subtitle AES-CBC Decryption Keys (saved to .env):")
    current_key = os.getenv("KISSKH_KEY", "")
    current_iv = os.getenv("KISSKH_INITIALIZATION_VECTOR", "")
    _echo(f"  Current KISSKH_KEY : {_mask_secret(current_key)}")
    _echo(f"  Current KISSKH_IV  : {_mask_secret(current_iv)}")
    new_key = _prompt("  Enter KISSKH_KEY (Enter to keep current): ")
    new_iv = _prompt("  Enter KISSKH_INITIALIZATION_VECTOR (Enter to keep current): ")
    updates: dict[str, str | None] = {}
    if new_key:
        updates["KISSKH_KEY"] = new_key
    if new_iv:
        updates["KISSKH_INITIALIZATION_VECTOR"] = new_iv
    if updates:
        update_env_vars(updates)

    if os.getenv("KISSKH_KEY") and os.getenv("KISSKH_INITIALIZATION_VECTOR"):
        config.decrypt_subtitle = True
        config.save()
        return True
    return False


def _pick_quality(current: str) -> str:
    _echo()
    _echo("Select quality:")
    for idx, q in enumerate(VALID_QUALITIES, start=1):
        marker = " *" if q == current else ""
        _echo(f"  [{idx}] {q}{_c(marker, fg='green')}")
    choice = _prompt(f"Choice [1-{len(VALID_QUALITIES)}] (Enter to keep {current}): ")
    if not choice:
        return current
    if choice.isdigit() and 1 <= int(choice) <= len(VALID_QUALITIES):
        return VALID_QUALITIES[int(choice) - 1]
    if choice in VALID_QUALITIES:
        return choice
    return current


def _pick_sub_langs(current: list[str]) -> list[str]:
    _echo()
    _echo("Subtitle languages (examples: 'en', 'en,id', 'all', or 'none'):")
    raw = _prompt(f"Languages [current: {', '.join(current) if current else 'none'}]: ")
    if not raw:
        return current
    lowered = raw.strip().lower()
    if lowered in {"none", "off", "no"}:
        return []
    if lowered == "all":
        return ["all"]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _pick_output_dir(current: str) -> str:
    _echo()
    _echo(f"Current output directory: {current}")
    _echo("Tip: enter '.' for current folder, '~/Downloads', or any custom path.")
    raw = _prompt("New output directory (Enter to keep current): ")
    if not raw:
        return current
    return str(Path(raw).expanduser())


def _pick_subtitle_mode(current: str) -> str:
    caps = detect_ffmpeg_capabilities()
    embed_note = _c("ready", fg="green") if caps.can_embed else _c("ffmpeg missing", fg="red")
    burn_note = (
        _c("ready", fg="green")
        if caps.can_burn
        else _c("needs ffmpeg-full / libass", fg="yellow")
    )

    options = [
        ("separate", "Separate .srt file beside video"),
        ("embed", f"Embed inside video (.mp4/.mkv track, fast/lossless) [{embed_note}]"),
        ("burn", f"Bake into video frames (permanent hardsubs) [{burn_note}]"),
    ]
    _echo()
    _echo("Select how subtitles are handled with video:")
    for idx, (key, desc) in enumerate(options, start=1):
        marker = _c(" *", fg="green") if key == current else ""
        _echo(f"  [{idx}] {desc}{marker}")

    choice = _prompt("Choice [1-3] (Enter to keep current): ").lower()
    if not choice:
        return current
    if choice.isdigit() and 1 <= int(choice) <= len(options):
        return options[int(choice) - 1][0]
    if choice in VALID_SUBTITLE_MODES:
        return choice
    return current


def _install_ffmpeg_full_flow() -> bool:
    brew = shutil.which("brew")
    if not brew:
        _echo(_c("Homebrew ('brew') not found in PATH. Install an ffmpeg build with libass manually.", fg="red"))
        return False
    _echo(_c("\nRunning 'brew install ffmpeg-full' (adds libass for baked-in subtitles)...", fg="cyan"))
    res = subprocess.run([brew, "install", "ffmpeg-full"], check=False)
    if res.returncode != 0:
        _echo(_c("Failed to install ffmpeg-full via Homebrew.", fg="red"))
        return False
    caps = detect_ffmpeg_capabilities()
    if not caps.can_burn:
        _echo(_c("ffmpeg-full installed, but 'subtitles' filter was not detected.", fg="yellow"))
        return False
    _echo(_c("ffmpeg-full is ready for baked-in subtitles!", fg="green", bold=True))
    return True


class KissKHConsoleApp:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.load()
        self.service = KissKHService(base_url=self.config.base_url)

    def _refresh_service_source(self) -> None:
        self.service.close()
        self.service = KissKHService(base_url=self.config.base_url)

    def _set_download_logging(self, active: bool) -> None:
        root_logger = logging.getLogger("kisskh_downloader")
        if active and self.config.verbose:
            if not logging.getLogger().handlers:
                logging.basicConfig(format="  %(levelname)s: %(message)s", level=logging.DEBUG)
            root_logger.setLevel(logging.DEBUG)
        else:
            root_logger.setLevel(logging.WARNING)

    def run(self, initial_query: str | None = None) -> None:
        self._set_download_logging(False)
        flash: tuple[str, str] | None = None
        try:
            if initial_query:
                self._search_or_url_flow(initial_input=initial_query)

            while True:
                choice = self._show_main_menu(flash=flash)
                flash = None
                if choice in {"", "1"}:
                    self._search_or_url_flow()
                elif choice == "2":
                    flash = self._recent_series_flow()
                elif choice == "3":
                    self._settings_menu()
                elif choice == "4":
                    self._auth_menu()
                elif choice in {"5", "q", "quit", "exit"}:
                    _echo(_c("Goodbye!", fg="cyan"))
                    break
                else:
                    flash = ("Unknown option. Choose 1-5.", "yellow")
        except KeyboardInterrupt:
            _echo(_c("\nExiting cleanly.", dim=True))
        finally:
            self.service.close()

    def _show_main_menu(self, flash: tuple[str, str] | None = None) -> str:
        auth = check_auth_status()
        auth_color = "green" if auth.is_ready else "yellow"

        _banner("KissKH Episode Range Downloader")
        _echo(f"  Source  : {_c(self.config.base_url, fg='green', bold=True)}")
        _echo(
            f"  Format  : {_c(self.config.quality, bold=True)}"
            f" | Subs: {_c(self.config.formatted_sub_langs(), bold=True)}"
            f" ({self.config.formatted_subtitle_mode()})"
        )
        _echo(
            f"  Mode    : {'Subtitles Only' if self.config.subs_only else 'Video + Subtitles'}"
            f" | Skip Existing: {'On' if self.config.skip_existing else 'Off'}"
        )
        _echo(f"  Output  : {self.config.resolved_output_dir()}")
        _echo(f"  Auth    : {_c(auth.summary_text(), fg=auth_color)}")
        _divider()
        _show_flash(flash)

        recent_count = len(self.config.recent_dramas)
        recent_hint = f" ({recent_count})" if recent_count else " (empty)"

        _echo(f"  {_c('[1]', fg='cyan', bold=True)} Search or Paste URL & Download  {_c('(Enter)', dim=True)}")
        _echo(f"  {_c('[2]', fg='cyan', bold=True)} Recent Series{recent_hint}")
        _echo(f"  {_c('[3]', fg='cyan', bold=True)} Settings & Defaults")
        _echo(f"  {_c('[4]', fg='cyan', bold=True)} Auth / kkey & Playwright Setup")
        _echo(f"  {_c('[5]', fg='cyan', bold=True)} Exit")
        _echo()
        return _prompt("Select option [1]: ", default="1").lower()

    def _search_or_url_flow(self, initial_input: str | None = None) -> None:
        raw_input = initial_input
        flash: tuple[str, str] | None = None
        while True:
            if not raw_input:
                _banner("Search or Open URL")
                _show_flash(flash)
                flash = None
                raw_input = _prompt("Drama name or KissKH URL (or 'b' back): ")
            if not raw_input or raw_input.lower() in {"b", "back"}:
                return

            try:
                parsed = parse_user_input(raw_input)
            except ValueError as exc:
                flash = (f"Error: {exc}", "red")
                raw_input = None
                continue

            if parsed.is_url and parsed.drama_id is not None:
                _echo(_c(f"Loading drama #{parsed.drama_id} from {self.config.base_url}...", fg="cyan"))
                try:
                    drama = self.service.get_drama(parsed.drama_id)
                except requests.RequestException as exc:
                    flash = (f"Failed to fetch drama: {exc}", "red")
                    raw_input = None
                    continue
                self.config.add_recent_drama(
                    drama_id=drama.id,
                    title=drama.title,
                    episodes_count=drama.episodes_count,
                    label=drama.status,
                )
                self._download_drama_flow(drama, default_ep=parsed.episode_number)
                return

            # Search by title
            _echo(_c(f"Searching {self.config.base_url} for '{parsed.query}'...", fg="cyan"))
            try:
                results = self.service.search(parsed.query)
            except requests.RequestException as exc:
                flash = (f"Search failed: {exc}", "red")
                raw_input = None
                continue

            if not results:
                flash = (f"No dramas matched '{parsed.query}'. Try another title or paste a URL.", "yellow")
                raw_input = None
                continue

            selected = self._pick_search_result(results, query=parsed.query)
            if selected == "re_search":
                raw_input = None
                continue
            if selected is None:
                return

            _echo(_c(f"Loading episodes for '{selected.title}'...", fg="cyan"))
            try:
                drama = self.service.get_drama(selected.id)
            except requests.RequestException as exc:
                flash = (f"Failed to load drama details: {exc}", "red")
                raw_input = None
                continue

            self.config.add_recent_drama(
                drama_id=drama.id,
                title=drama.title,
                episodes_count=drama.episodes_count,
                label=selected.label or drama.status,
            )
            self._download_drama_flow(drama)
            return

    def _pick_search_result(
        self,
        results: list[DramaInfo],
        query: str = "",
    ) -> DramaInfo | str | None:
        flash: tuple[str, str] | None = None
        while True:
            header = f"Search Results: {query}" if query else "Search Results"
            _banner(header)
            _echo(f"  {'#':>2}  {'Title':<42} {'Eps':>4}  {'Label'}")
            _divider()
            for idx, item in enumerate(results, start=1):
                title = item.title if len(item.title) <= 42 else item.title[:39] + "..."
                _echo(f"  {idx:>2}. {title:<42} {item.episodes_count:>4}  {item.label}")
            _divider()
            _show_flash(flash)
            flash = None

            raw = _prompt(
                f"Pick # [1-{len(results)}, Enter=1] ('s' search again, 'b' back): ",
                default="1",
            ).lower()
            if raw in {"b", "back"}:
                return None
            if raw in {"s", "search"}:
                return "re_search"
            if raw.isdigit() and 1 <= int(raw) <= len(results):
                return results[int(raw) - 1]
            flash = (f"Please enter a number from 1 to {len(results)}.", "yellow")

    def _recent_series_flow(self) -> tuple[str, str] | None:
        if not self.config.recent_dramas:
            return ("No recent series yet. Search or paste a URL first.", "yellow")

        flash: tuple[str, str] | None = None
        while True:
            _banner("Recent Series")
            for idx, item in enumerate(self.config.recent_dramas, start=1):
                meta = f"{item.episodes_count} eps" if item.episodes_count else ""
                if item.label:
                    meta = f"{meta} | {item.label}" if meta else item.label
                _echo(
                    f"  [{idx}] {item.title}"
                    + (f"  {_c(f'({meta})', dim=True)}" if meta else "")
                )
            _divider()
            _show_flash(flash)
            flash = None
            _echo("  [Enter/#] Open series   [c] Clear list   [b] Back")
            _echo()

            raw = _prompt(
                f"Pick # [1-{len(self.config.recent_dramas)}, Enter=1]: ",
                default="1",
            ).lower()
            if raw in {"b", "back"}:
                return None
            if raw == "c":
                self.config.recent_dramas = []
                self.config.save()
                return ("Recent series list cleared.", "green")
            if raw.isdigit() and 1 <= int(raw) <= len(self.config.recent_dramas):
                break
            flash = (f"Enter a number from 1 to {len(self.config.recent_dramas)}.", "yellow")

        chosen = self.config.recent_dramas[int(raw) - 1]
        _echo(_c(f"Refreshing episodes for '{chosen.title}'...", fg="cyan"))
        try:
            drama = self.service.get_drama(chosen.id)
        except requests.RequestException as exc:
            return (f"Failed to load drama: {exc}", "red")

        self.config.add_recent_drama(
            drama_id=drama.id,
            title=drama.title,
            episodes_count=drama.episodes_count,
            label=chosen.label or drama.status,
        )
        self._download_drama_flow(drama)
        return None

    def _render_drama_header(
        self,
        drama: DramaDetails,
        run_cfg: AppConfig,
        local_eps: set[float],
    ) -> tuple[str, str]:
        non_recap = drama.non_recap_episodes
        recaps = drama.recap_episodes
        pool = non_recap if (run_cfg.skip_recap and non_recap) else drama.episodes
        first_num = format_episode_num(pool[0].number)
        last_num = format_episode_num(pool[-1].number)

        _banner(drama.title)
        meta_parts = [p for p in [drama.type, drama.country, drama.status, drama.release_date] if p]
        if meta_parts:
            _echo(f"  Info      : {' | '.join(meta_parts)}")
        ep_line = f"{len(pool)} episodes (Ep {first_num} .. Ep {last_num})"
        if recaps:
            recap_tags = ", ".join(format_episode_num(r.number) for r in recaps[:5])
            suffix = "..." if len(recaps) > 5 else ""
            ep_line += f"  [+{len(recaps)} special/recap: {recap_tags}{suffix}]"
        _echo(f"  Episodes  : {ep_line}")

        if local_eps:
            sorted_local = sorted(local_eps)
            preview = ", ".join(format_episode_tag(n) for n in sorted_local[:8])
            if len(sorted_local) > 8:
                preview += f" ... ({len(sorted_local)} total)"
            _echo(f"  On Disk   : {_c(preview, fg='green')}")

        return first_num, last_num

    def _download_drama_flow(
        self,
        drama: DramaDetails,
        default_ep: float | None = None,
    ) -> None:
        if not drama.episodes:
            _echo(_c("\nNo episodes found for this series on kisskh.do.", fg="yellow"))
            _pause()
            return

        run_cfg = replace(self.config, sub_langs=list(self.config.sub_langs))
        local_eps = get_local_downloaded_episodes(
            output_dir=run_cfg.resolved_output_dir(),
            drama_title=drama.title,
            episodes=drama.episodes,
            subs_only=run_cfg.subs_only,
        )

        selected_episodes: list[Episode] = []
        flash: tuple[str, str] | None = None
        while True:
            first_num, last_num = self._render_drama_header(drama, run_cfg, local_eps)
            _divider()
            _show_flash(flash)
            flash = None
            _echo("  Examples:  1-5 (range) | 3 (single) | 5- (to end) | last 3 | 1-3, 7 | all")
            if default_ep is not None:
                default_label = f"Enter = Ep {format_episode_num(default_ep)}"
            else:
                default_label = f"Enter = all ({first_num}-{last_num})"
            _echo()

            expr = _prompt(f"Episode range [{default_label}] (or 'b' back): ")
            if expr.lower() in {"b", "back"}:
                return
            try:
                selected_episodes = parse_episode_selection(
                    expr=expr,
                    available_episodes=drama.episodes,
                    default_ep=default_ep,
                    skip_recap=run_cfg.skip_recap,
                )
            except ValueError as exc:
                flash = (str(exc), "yellow")
                continue

            if not selected_episodes:
                flash = (
                    f"No episodes matched '{expr}'. Available: {first_num} to {last_num}.",
                    "yellow",
                )
                continue
            break

        # Clean confirm & quick override screen (redraws cleanly on each change)
        flash = None
        while True:
            drama_dir = run_cfg.resolved_output_dir() / sanitize_name(drama.title)
            ep_tags = [format_episode_tag(ep.number) for ep in selected_episodes]
            if len(ep_tags) <= 6:
                ep_preview = ", ".join(ep_tags)
            else:
                ep_preview = f"{ep_tags[0]} .. {ep_tags[-1]} ({len(ep_tags)} episodes)"

            on_disk_selected = (
                len([ep for ep in selected_episodes if ep.number in local_eps])
                if run_cfg.skip_existing
                else 0
            )
            to_fetch = len(selected_episodes) - on_disk_selected

            _banner(f"Confirm Download: {drama.title}")
            _echo(f"  Episodes  : {_c(ep_preview, bold=True)}")
            if run_cfg.skip_existing and on_disk_selected > 0:
                _echo(
                    f"  Queue     : {to_fetch} to download, {on_disk_selected} already on disk (will skip)"
                )
            _echo(
                f"  Quality   : {run_cfg.quality}"
                f"   | Mode: {'Subtitles Only' if run_cfg.subs_only else 'Video + Subtitles'}"
            )
            _echo(
                f"  Subtitles : {run_cfg.formatted_sub_langs()} ({run_cfg.formatted_subtitle_mode()})"
                f"   | Skip Existing: {'On' if run_cfg.skip_existing else 'Off'}"
            )
            _echo(f"  Save To   : {drama_dir}")
            _divider()
            _show_flash(flash)
            flash = None
            _echo(
                "  [Enter] Start Download   [q] Quality   [s] Subtitles   [b] Sub Mode\n"
                "  [m] Video/Subs-Only      [o] Output    [x] Skip Existing  [c] Cancel"
            )
            action = _prompt("Action [Start]: ", default="").lower()

            if action == "":
                break
            elif action == "c":
                return
            elif action == "q":
                run_cfg.quality = _pick_quality(run_cfg.quality)
            elif action == "s":
                run_cfg.sub_langs = _pick_sub_langs(run_cfg.sub_langs)
            elif action == "b":
                run_cfg.subtitle_mode = _pick_subtitle_mode(run_cfg.subtitle_mode)
            elif action == "m":
                run_cfg.subs_only = not run_cfg.subs_only
                local_eps = get_local_downloaded_episodes(
                    output_dir=run_cfg.resolved_output_dir(),
                    drama_title=drama.title,
                    episodes=drama.episodes,
                    subs_only=run_cfg.subs_only,
                )
            elif action == "o":
                run_cfg.output_dir = _pick_output_dir(run_cfg.output_dir)
                local_eps = get_local_downloaded_episodes(
                    output_dir=run_cfg.resolved_output_dir(),
                    drama_title=drama.title,
                    episodes=drama.episodes,
                    subs_only=run_cfg.subs_only,
                )
            elif action == "x":
                run_cfg.skip_existing = not run_cfg.skip_existing
            else:
                flash = ("Unknown option.", "yellow")

        # Ensure authentication & ffmpeg subtitle capabilities are ready
        if not self._ensure_auth_ready():
            return
        if not self._ensure_ffmpeg_for_subtitle_mode(run_cfg):
            return

        _banner(f"Downloading: {drama.title}")
        self._set_download_logging(True)
        try:
            summary = self.service.download_episodes(
                drama=drama,
                episodes=selected_episodes,
                config=run_cfg,
                on_status=lambda msg: _echo(f"  {msg}"),
            )
        finally:
            self._set_download_logging(False)

        _echo()
        _divider("=")
        _echo(_c("  Download Summary", fg="cyan", bold=True))
        _divider("=")
        _echo(f"  Total selected : {summary.total}")
        _echo(f"  Downloaded     : {_c(str(summary.downloaded), fg='green', bold=True)}")
        if summary.skipped:
            _echo(f"  Skipped        : {summary.skipped}")
        if summary.unreleased:
            _echo(f"  Unreleased     : {_c(str(summary.unreleased), fg='yellow')}")
        if summary.cancelled:
            _echo(f"  Status         : {_c('Cancelled by user', fg='yellow')}")
        if summary.failed:
            _echo(f"  Failed         : {_c(str(len(summary.failed)), fg='red', bold=True)}")
            for ep_num, reason in summary.failed:
                _echo(f"    - {format_episode_tag(ep_num)}: {reason}")
        if summary.output_folder:
            _echo(f"  Folder         : {summary.output_folder}")
        _pause()

    def _ensure_ffmpeg_for_subtitle_mode(self, run_cfg: AppConfig) -> bool:
        if run_cfg.subs_only or not run_cfg.sub_langs or run_cfg.subtitle_mode == "separate":
            return True

        caps = detect_ffmpeg_capabilities()
        if run_cfg.subtitle_mode == "embed":
            if caps.can_embed:
                return True
            _banner("ffmpeg Not Found")
            _echo("  Embedding subtitles into the video requires ffmpeg.")
            _echo("  [1] Continue with separate .srt files")
            _echo("  [2] Cancel")
            if _prompt("Select option [1]: ", default="1") == "1":
                run_cfg.subtitle_mode = "separate"
                return True
            return False

        if run_cfg.subtitle_mode == "burn":
            if caps.can_burn:
                return True
            _banner("Baked-In Subtitles Require ffmpeg-full (libass)")
            _echo(
                f"  Detected ffmpeg ({caps.ffmpeg_path or 'none'}) lacks the 'subtitles' (libass) filter."
            )
            _echo()
            _echo("  [1] Install ffmpeg-full via Homebrew now (enables baked-in subtitles)")
            _echo("  [2] Switch to 'embed' mode (puts subtitle track inside .mp4 — instant)")
            _echo("  [3] Keep separate .srt files")
            _echo("  [4] Cancel")
            choice = _prompt("Select option [2]: ", default="2").lower()
            if choice == "1":
                return _install_ffmpeg_full_flow()
            if choice == "2":
                if not caps.can_embed:
                    run_cfg.subtitle_mode = "separate"
                else:
                    run_cfg.subtitle_mode = "embed"
                return True
            if choice == "3":
                run_cfg.subtitle_mode = "separate"
                return True
            return False

        return True

    def _ensure_auth_ready(self) -> bool:
        auth: AuthStatus = check_auth_status()
        if auth.is_ready:
            return True

        _banner("Authentication Setup Required (kkey)")
        _echo("  KissKH requires a 'kkey' token to fetch streams & subtitles.")
        if auth.playwright_installed and not auth.chromium_installed:
            _echo("  Playwright is installed, but its Chromium browser is missing.")
        else:
            _echo("  Neither Playwright+Chromium nor manual kkeys are configured yet.")
        _echo()
        _echo("  [1] Install Playwright + Chromium now (recommended, automatic)")
        _echo("  [2] Enter KISSKH_STREAM_KEY & KISSKH_SUB_KEY manually")
        _echo("  [3] Try downloading anyway")
        _echo("  [4] Cancel")
        choice = _prompt("Select option [1]: ", default="1").lower()
        if choice == "1":
            return _install_playwright_flow()
        if choice == "2":
            return _configure_manual_kkeys()
        if choice == "3":
            return True
        return False

    def _settings_menu(self) -> None:
        flash: tuple[str, str] | None = None
        while True:
            _banner("Settings & Defaults")
            _echo(f"  [1] Site Source URL       : {self.config.base_url}")
            _echo(f"  [2] Default Quality       : {self.config.quality}")
            _echo(f"  [3] Subtitle Languages    : {self.config.formatted_sub_langs()}")
            _echo(f"  [4] Subtitle Placement    : {self.config.formatted_subtitle_mode()}")
            _echo(f"  [5] Keep .srt After Merge : {'On' if self.config.keep_separate_srt else 'Off'}")
            _echo(f"  [6] Download Mode         : {'Subtitles Only' if self.config.subs_only else 'Video + Subtitles'}")
            _echo(f"  [7] Output Directory      : {self.config.resolved_output_dir()}")
            _echo(f"  [8] Skip Existing Files   : {'On' if self.config.skip_existing else 'Off'}")
            _echo(f"  [9] Skip Recap Episodes   : {'On' if self.config.skip_recap else 'Off'}")
            _echo(f"  [a] Decrypt Subtitles     : {'On' if self.config.decrypt_subtitle else 'Off'}")
            _echo(f"  [v] Verbose Debug Logs    : {'On' if self.config.verbose else 'Off'}")
            _echo("  [0] Back to Main Menu")
            _divider()
            _show_flash(flash)
            flash = None

            choice = _prompt("Edit setting [0-9, a, v]: ", default="0").lower()
            if choice in {"0", "b", "back", ""}:
                return
            elif choice == "1":
                raw = _prompt(
                    f"Site URL [default {DEFAULT_BASE_URL}, current {self.config.base_url}]: "
                )
                if raw:
                    if not raw.startswith(("http://", "https://")):
                        raw = f"https://{raw}"
                    self.config.base_url = raw.rstrip("/")
                    update_env_vars({"KISSKH_BASE_URL": self.config.base_url})
                    self.config.save()
                    self._refresh_service_source()
                    flash = (f"Site source updated to {self.config.base_url}", "green")
            elif choice == "2":
                self.config.quality = _pick_quality(self.config.quality)
                self.config.save()
                flash = (f"Default quality: {self.config.quality}", "green")
            elif choice == "3":
                self.config.sub_langs = _pick_sub_langs(self.config.sub_langs)
                self.config.save()
                flash = (f"Subtitle languages: {self.config.formatted_sub_langs()}", "green")
            elif choice == "4":
                self.config.subtitle_mode = _pick_subtitle_mode(self.config.subtitle_mode)
                self.config.save()
                flash = (f"Subtitle placement: {self.config.formatted_subtitle_mode()}", "green")
            elif choice == "5":
                self.config.keep_separate_srt = not self.config.keep_separate_srt
                self.config.save()
                flash = (f"Keep .srt after merge: {'On' if self.config.keep_separate_srt else 'Off'}", "green")
            elif choice == "6":
                self.config.subs_only = not self.config.subs_only
                self.config.save()
                flash = (
                    f"Download mode: {'Subtitles Only' if self.config.subs_only else 'Video + Subtitles'}",
                    "green",
                )
            elif choice == "7":
                self.config.output_dir = _pick_output_dir(self.config.output_dir)
                self.config.save()
                flash = (f"Output directory: {self.config.resolved_output_dir()}", "green")
            elif choice == "8":
                self.config.skip_existing = not self.config.skip_existing
                self.config.save()
                flash = (f"Skip existing files: {'On' if self.config.skip_existing else 'Off'}", "green")
            elif choice == "9":
                self.config.skip_recap = not self.config.skip_recap
                self.config.save()
                flash = (f"Skip recap episodes: {'On' if self.config.skip_recap else 'Off'}", "green")
            elif choice == "a":
                if not self.config.decrypt_subtitle:
                    if _configure_decrypt_keys(self.config):
                        flash = ("Subtitle decryption enabled.", "green")
                else:
                    self.config.decrypt_subtitle = False
                    self.config.save()
                    flash = ("Subtitle decryption disabled.", "green")
            elif choice == "v":
                self.config.verbose = not self.config.verbose
                self.config.save()
                flash = (f"Verbose debug logs: {'On' if self.config.verbose else 'Off'}", "green")
            else:
                flash = ("Invalid choice.", "yellow")

    def _auth_menu(self) -> None:
        flash: tuple[str, str] | None = None
        while True:
            auth = check_auth_status()
            _banner("Authentication / kkey & Playwright Setup")
            _echo(f"  Overall Status     : {auth.summary_text()}")
            _echo(
                f"  Playwright Package : {'Installed' if auth.playwright_installed else 'Not installed'}"
            )
            _echo(
                f"  Chromium Browser   : {'Installed' if auth.chromium_installed else 'Not installed'}"
            )
            _echo(f"  KISSKH_STREAM_KEY  : {_mask_secret(os.getenv('KISSKH_STREAM_KEY'))}")
            _echo(f"  KISSKH_SUB_KEY     : {_mask_secret(os.getenv('KISSKH_SUB_KEY'))}")
            _echo(
                f"  Subtitle Decrypt   : Key={'Set' if auth.decrypt_key_set else 'Not set'}, "
                f"IV={'Set' if auth.decrypt_iv_set else 'Not set'}"
            )
            _divider()
            _show_flash(flash)
            flash = None
            _echo("  [1] Install / Verify Playwright + Chromium (auto kkey)")
            _echo("  [2] Set Manual KISSKH_STREAM_KEY & KISSKH_SUB_KEY (.env)")
            _echo("  [3] Clear Saved Manual kkeys (use Playwright auto mode)")
            _echo("  [4] Set / Update Subtitle Decryption Keys (.env)")
            _echo(f"  [5] Test Connection to {self.config.base_url}")
            _echo("  [0] Back to Main Menu")
            _echo()

            choice = _prompt("Select option [0-5]: ", default="0").lower()
            if choice in {"0", "b", "back", ""}:
                return
            elif choice == "1":
                if _install_playwright_flow():
                    flash = ("Playwright + Chromium ready.", "green")
                else:
                    flash = ("Playwright setup failed.", "red")
                _pause()
            elif choice == "2":
                if _configure_manual_kkeys():
                    flash = ("Saved kkeys to .env and activated.", "green")
                else:
                    flash = ("Cancelled (keys unchanged).", "yellow")
            elif choice == "3":
                update_env_vars({"KISSKH_STREAM_KEY": None, "KISSKH_SUB_KEY": None})
                flash = ("Cleared KISSKH_STREAM_KEY and KISSKH_SUB_KEY.", "green")
            elif choice == "4":
                if _configure_decrypt_keys(self.config):
                    flash = ("Subtitle decryption keys updated.", "green")
            elif choice == "5":
                _echo(_c(f"\nTesting connection to {self.config.base_url}...", fg="cyan"))
                try:
                    results = self.service.search("Proposal")
                    flash = (
                        f"Success! {self.config.base_url} responded ({len(results)} search results).",
                        "green",
                    )
                except Exception as exc:
                    flash = (f"Connection test failed: {exc}", "red")
            else:
                flash = ("Invalid choice.", "yellow")
