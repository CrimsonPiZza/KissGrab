from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv, set_key, unset_key
from kisskh_downloader.enums.quality import Quality

DEFAULT_BASE_URL = "https://kisskh.do"
DEFAULT_SUBTITLE_MODE = "embed"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.json"
ENV_PATH = PROJECT_ROOT / ".env"
VALID_QUALITIES: list[str] = [q.value for q in Quality]
VALID_SUBTITLE_MODES: tuple[str, ...] = ("separate", "embed", "burn")
MAX_RECENT_DRAMAS = 10


def _ensure_valid_base_url(url: str | None) -> str:
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        return DEFAULT_BASE_URL
    if not cleaned.startswith(("http://", "https://")):
        cleaned = f"https://{cleaned}"
    return cleaned


@dataclass
class RecentDrama:
    id: int
    title: str
    episodes_count: int = 0
    label: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecentDrama | None:
        try:
            return cls(
                id=int(data["id"]),
                title=str(data["title"]),
                episodes_count=int(data.get("episodes_count") or 0),
                label=str(data.get("label") or ""),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass
class AppConfig:
    base_url: str = DEFAULT_BASE_URL
    quality: str = "1080p"
    sub_langs: list[str] = field(default_factory=lambda: ["en"])
    subtitle_mode: str = DEFAULT_SUBTITLE_MODE  # "separate", "embed", or "burn"
    keep_separate_srt: bool = False
    subs_only: bool = False
    output_dir: str = field(default_factory=lambda: str(Path.home() / "Downloads"))
    skip_existing: bool = True
    skip_recap: bool = True
    decrypt_subtitle: bool = False
    verbose: bool = False
    recent_dramas: list[RecentDrama] = field(default_factory=list)

    @classmethod
    def load(
        cls,
        config_path: Path = CONFIG_PATH,
        env_path: Path = ENV_PATH,
    ) -> AppConfig:
        if env_path.exists():
            load_dotenv(env_path, override=False)

        env_base_url = os.getenv("KISSKH_BASE_URL")
        cfg = cls()

        if config_path.exists():
            try:
                raw = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    cfg.base_url = _ensure_valid_base_url(raw.get("base_url") or env_base_url or DEFAULT_BASE_URL)
                    quality = str(raw.get("quality") or "1080p")
                    cfg.quality = quality if quality in VALID_QUALITIES else "1080p"

                    sub_langs = raw.get("sub_langs")
                    if isinstance(sub_langs, list):
                        cfg.sub_langs = [str(x).strip() for x in sub_langs if str(x).strip()]
                    elif isinstance(sub_langs, str):
                        cfg.sub_langs = [x.strip() for x in sub_langs.split(",") if x.strip()]

                    sub_mode = str(raw.get("subtitle_mode") or DEFAULT_SUBTITLE_MODE).strip().lower()
                    cfg.subtitle_mode = sub_mode if sub_mode in VALID_SUBTITLE_MODES else DEFAULT_SUBTITLE_MODE
                    cfg.keep_separate_srt = bool(raw.get("keep_separate_srt", False))

                    cfg.subs_only = bool(raw.get("subs_only", False))
                    output_dir = str(raw.get("output_dir") or "").strip()
                    if output_dir:
                        cfg.output_dir = output_dir
                    cfg.skip_existing = bool(raw.get("skip_existing", True))
                    cfg.skip_recap = bool(raw.get("skip_recap", True))
                    cfg.decrypt_subtitle = bool(raw.get("decrypt_subtitle", False))
                    cfg.verbose = bool(raw.get("verbose", False))

                    raw_recent = raw.get("recent_dramas")
                    if isinstance(raw_recent, list):
                        parsed_recent: list[RecentDrama] = []
                        for item in raw_recent:
                            if isinstance(item, dict):
                                entry = RecentDrama.from_dict(item)
                                if entry is not None:
                                    parsed_recent.append(entry)
                        cfg.recent_dramas = parsed_recent[:MAX_RECENT_DRAMAS]
            except (OSError, json.JSONDecodeError):
                # Fall back cleanly to defaults if config file is unreadable/corrupt
                pass
        elif env_base_url:
            cfg.base_url = _ensure_valid_base_url(env_base_url)

        os.environ["KISSKH_BASE_URL"] = cfg.base_url
        return cfg

    def save(self, config_path: Path = CONFIG_PATH) -> None:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        tmp_path = config_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        tmp_path.replace(config_path)

    def add_recent_drama(
        self,
        drama_id: int,
        title: str,
        episodes_count: int = 0,
        label: str = "",
        config_path: Path = CONFIG_PATH,
    ) -> None:
        entry = RecentDrama(
            id=drama_id,
            title=title,
            episodes_count=episodes_count,
            label=label,
        )
        filtered = [d for d in self.recent_dramas if d.id != drama_id]
        self.recent_dramas = [entry, *filtered][:MAX_RECENT_DRAMAS]
        self.save(config_path=config_path)

    def resolved_output_dir(self) -> Path:
        return Path(self.output_dir).expanduser().resolve()

    def formatted_sub_langs(self) -> str:
        if not self.sub_langs:
            return "none"
        return ", ".join(self.sub_langs)

    def formatted_subtitle_mode(self) -> str:
        labels = {
            "separate": "Separate .srt",
            "embed": "Embed in Video",
            "burn": "Bake into Video",
        }
        return labels.get(self.subtitle_mode, "Separate .srt")


def update_env_vars(updates: dict[str, str | None], env_path: Path = ENV_PATH) -> None:
    """Persist environment variables to .env and update os.environ immediately."""
    if not env_path.exists():
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text("", encoding="utf-8")

    for key, value in updates.items():
        if value is None or value == "":
            os.environ.pop(key, None)
            unset_key(str(env_path), key)
        else:
            os.environ[key] = value
            set_key(str(env_path), key, value)

