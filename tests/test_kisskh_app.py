from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from kisskh_downloader.models.drama import Episode
from kisskh_downloader.models.sub import SubItem

from kisskh_app.client import (
    DramaDetails,
    KissKHService,
    format_episode_num,
    format_episode_tag,
    get_local_downloaded_episodes,
    parse_episode_selection,
    parse_user_input,
    sanitize_name,
    slugify_title,
)
from kisskh_app.config import DEFAULT_BASE_URL, AppConfig, update_env_vars
from kisskh_app.subtitles_mux import (
    burn_subtitle_into_video,
    detect_ffmpeg_capabilities,
    embed_subtitles_in_video,
    escape_ffmpeg_filter_path,
    iso639_2_code,
)
from kisskh_app.ui import KissKHConsoleApp


def _sample_episodes() -> list[Episode]:
    return [
        Episode(id=101, number=1.0, sub=1),
        Episode(id=102, number=2.0, sub=1),
        Episode(id=103, number=3.0, sub=1),
        Episode(id=104, number=4.0, sub=1),
        Episode(id=105, number=5.0, sub=1),
        Episode(id=106, number=5.1, sub=0),
    ]


class TestInputAndRangeParsing(unittest.TestCase):
    def test_parse_drama_url_from_kisskh_do(self) -> None:
        parsed = parse_user_input("https://kisskh.do/Drama/A-Business-Proposal?id=4608")
        self.assertTrue(parsed.is_url)
        self.assertEqual(parsed.drama_id, 4608)
        self.assertIsNone(parsed.episode_id)
        self.assertIsNone(parsed.episode_number)

    def test_parse_episode_url_without_scheme_and_with_quotes(self) -> None:
        parsed = parse_user_input(
            '"kisskh.do/Drama/Alchemy-of-Souls/Episode-4?id=5043&ep=99123&page=0"'
        )
        self.assertTrue(parsed.is_url)
        self.assertEqual(parsed.drama_id, 5043)
        self.assertEqual(parsed.episode_id, 99123)
        self.assertEqual(parsed.episode_number, 4.0)

    def test_parse_url_missing_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_user_input("https://kisskh.do/Drama/Missing-Id")

    def test_parse_search_query(self) -> None:
        parsed = parse_user_input("  Lovely Runner  ")
        self.assertFalse(parsed.is_url)
        self.assertEqual(parsed.query, "Lovely Runner")
        self.assertIsNone(parsed.drama_id)

    def test_parse_episode_selection_variants(self) -> None:
        eps = _sample_episodes()

        self.assertEqual(
            [e.number for e in parse_episode_selection("2-4", eps, skip_recap=True)],
            [2.0, 3.0, 4.0],
        )
        self.assertEqual(
            [e.number for e in parse_episode_selection("1, 3-4", eps, skip_recap=True)],
            [1.0, 3.0, 4.0],
        )
        self.assertEqual(
            [e.number for e in parse_episode_selection("4-", eps, skip_recap=True)],
            [4.0, 5.0],
        )
        self.assertEqual(
            [e.number for e in parse_episode_selection("-2", eps, skip_recap=True)],
            [1.0, 2.0],
        )
        self.assertEqual(
            [e.number for e in parse_episode_selection("last 2", eps, skip_recap=True)],
            [4.0, 5.0],
        )
        self.assertEqual(
            [e.number for e in parse_episode_selection("all", eps, skip_recap=True)],
            [1.0, 2.0, 3.0, 4.0, 5.0],
        )
        self.assertEqual(
            [e.number for e in parse_episode_selection("all", eps, skip_recap=False)],
            [1.0, 2.0, 3.0, 4.0, 5.0, 5.1],
        )
        # Explicit fractional episode overrides skip_recap
        self.assertEqual(
            [e.number for e in parse_episode_selection("5.1", eps, skip_recap=True)],
            [5.1],
        )
        # Empty uses default_ep when provided
        self.assertEqual(
            [e.number for e in parse_episode_selection("", eps, default_ep=3.0, skip_recap=True)],
            [3.0],
        )

    def test_parse_episode_selection_invalid_range(self) -> None:
        eps = _sample_episodes()
        with self.assertRaises(ValueError):
            parse_episode_selection("5-2", eps)
        with self.assertRaises(ValueError):
            parse_episode_selection("abc", eps)

    def test_formatting_and_sanitization(self) -> None:
        self.assertEqual(format_episode_tag(1.0), "E01")
        self.assertEqual(format_episode_tag(16.1), "E16.1")
        self.assertEqual(format_episode_num(1.0), "1")
        self.assertEqual(format_episode_num(16.1), "16.1")
        self.assertEqual(sanitize_name("Show: Part/1?"), "Show_ Part_1_")
        self.assertEqual(slugify_title("#Alive: Part 2"), "Alive-Part-2")


class TestConfigAndEnv(unittest.TestCase):
    def test_config_roundtrip_and_recent_dramas(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            cfg_path = tmp / "config.json"
            env_path = tmp / ".env"

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("KISSKH_BASE_URL", None)
                cfg = AppConfig.load(config_path=cfg_path, env_path=env_path)
                self.assertEqual(cfg.base_url, DEFAULT_BASE_URL)
                self.assertEqual(os.environ["KISSKH_BASE_URL"], "https://kisskh.do")

                cfg.quality = "720p"
                cfg.sub_langs = ["en", "id"]
                cfg.subtitle_mode = "embed"
                cfg.keep_separate_srt = True
                cfg.add_recent_drama(4608, "A Business Proposal", 12, "Completed", config_path=cfg_path)
                cfg.add_recent_drama(5043, "Alchemy of Souls", 20, "Completed", config_path=cfg_path)
                cfg.add_recent_drama(4608, "A Business Proposal", 12, "Completed", config_path=cfg_path)

                loaded = AppConfig.load(config_path=cfg_path, env_path=env_path)
                self.assertEqual(loaded.quality, "720p")
                self.assertEqual(loaded.sub_langs, ["en", "id"])
                self.assertEqual(loaded.subtitle_mode, "embed")
                self.assertTrue(loaded.keep_separate_srt)
                self.assertEqual([d.id for d in loaded.recent_dramas], [4608, 5043])

    def test_update_env_vars(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            with patch.dict(os.environ, {}, clear=False):
                update_env_vars(
                    {"KISSKH_STREAM_KEY": "abc123", "KISSKH_SUB_KEY": "xyz789"},
                    env_path=env_path,
                )
                self.assertEqual(os.environ["KISSKH_STREAM_KEY"], "abc123")
                self.assertEqual(os.environ["KISSKH_SUB_KEY"], "xyz789")
                self.assertIn("KISSKH_STREAM_KEY", env_path.read_text(encoding="utf-8"))

                update_env_vars({"KISSKH_STREAM_KEY": None}, env_path=env_path)
                self.assertNotIn("KISSKH_STREAM_KEY", os.environ)


class TestKissKHService(unittest.TestCase):
    def test_service_uses_kisskh_do_as_source(self) -> None:
        service = KissKHService()
        self.assertEqual(service.base_url, "https://kisskh.do")
        self.assertEqual(service.api.site_domain, "https://kisskh.do")
        self.assertEqual(service.api.base_url, "https://kisskh.do/api/")
        self.assertEqual(service.downloader.referer, "https://kisskh.do")
        service.close()

    def test_local_downloaded_episodes_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            drama_dir = out_dir / "My_Show"
            drama_dir.mkdir(parents=True)
            (drama_dir / "My_Show_E01.mp4").write_bytes(b"video")
            (drama_dir / "My_Show_E02.mp4.part").write_bytes(b"partial")
            (drama_dir / "My_Show_E03.en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")

            eps = _sample_episodes()
            video_found = get_local_downloaded_episodes(out_dir, "My:Show", eps, subs_only=False)
            self.assertEqual(video_found, {1.0})

            subs_found = get_local_downloaded_episodes(out_dir, "My:Show", eps, subs_only=True)
            self.assertEqual(subs_found, {3.0})

    def test_download_episodes_skips_existing_and_unreleased(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir).resolve()
            drama_dir = out_dir / "Test Drama"
            drama_dir.mkdir(parents=True)
            (drama_dir / "Test Drama_E01.mp4").write_bytes(b"already-here")

            cfg = AppConfig(
                base_url="https://kisskh.do",
                quality="720p",
                sub_langs=["en"],
                output_dir=str(out_dir),
                skip_existing=True,
            )
            drama = DramaDetails(
                id=1234,
                title="Test Drama",
                description="",
                country="KR",
                status="Ongoing",
                type="Drama",
                release_date="2026",
                episodes_count=3,
                episodes=_sample_episodes()[:3],
            )

            service = KissKHService(base_url="https://kisskh.do")
            service.api.generate_kkeys = MagicMock(
                return_value={"stream": "s_key", "sub": "sub_key"}
            )
            service.api.get_subtitles = MagicMock(
                return_value=[
                    SubItem(src="https://kisskh.do/sub.srt", label="English", land="en", default=True)
                ]
            )
            service.api.get_stream_url = MagicMock(
                side_effect=[
                    "https://cdn.example/ep2.m3u8",
                    "https://www.tickcounter.com/countdown/123",
                ]
            )
            service.downloader.download_video_from_stream_url = MagicMock()
            service.downloader.download_subtitles = MagicMock()
            service.api.cleanup = MagicMock()

            summary = service.download_episodes(drama, drama.episodes, cfg)

            self.assertEqual(summary.total, 3)
            self.assertEqual(summary.skipped, 1)
            self.assertEqual(summary.downloaded, 1)
            self.assertEqual(summary.unreleased, 1)
            self.assertEqual(summary.failed, [])
            service.downloader.download_video_from_stream_url.assert_called_once_with(
                "https://cdn.example/ep2.m3u8",
                str(drama_dir / "Test Drama_E02"),
                "720p",
            )
            service.downloader.download_subtitles.assert_called_once()
            service.api.cleanup.assert_called_once()


class TestSubtitleMuxAndBurn(unittest.TestCase):
    def test_iso_and_filter_path_escaping(self) -> None:
        self.assertEqual(iso639_2_code("en"), "eng")
        self.assertEqual(iso639_2_code("id"), "ind")
        self.assertEqual(iso639_2_code("unknown"), "und")
        escaped = escape_ffmpeg_filter_path(Path("/tmp/Show: Part [1]'s.srt"))
        self.assertIn("\\:", escaped)
        self.assertIn("\\[1\\]", escaped)
        self.assertIn("\\'", escaped)

    def test_embed_subtitles_into_real_mp4(self) -> None:
        caps = detect_ffmpeg_capabilities()
        if not caps.can_embed or caps.ffmpeg_path is None:
            self.skipTest("ffmpeg not available")
        ffprobe = shutil.which("ffprobe")
        if ffprobe is None:
            self.skipTest("ffprobe not available")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            video = tmp / "Show_E01.mp4"
            sub = tmp / "Show_E01.en.srt"

            subprocess.run(
                [
                    caps.ffmpeg_path,
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "color=c=black:s=160x90:d=1",
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=r=44100:cl=mono:d=1",
                    "-shortest",
                    "-c:v",
                    "libx264",
                    "-c:a",
                    "aac",
                    str(video),
                ],
                check=True,
                capture_output=True,
            )
            sub.write_text(
                "1\n00:00:00,000 --> 00:00:00,800\nHello KissKH!\n",
                encoding="utf-8",
            )

            out = embed_subtitles_in_video(
                video_path=video,
                sub_entries=[(sub, "en", "English")],
                ffmpeg_bin=caps.ffmpeg_path,
                keep_srt=False,
            )
            self.assertEqual(out, video)
            self.assertTrue(out.is_file())
            self.assertFalse(sub.exists())

            probe = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_type,codec_name:stream_tags=language",
                    "-of",
                    "default=noprint_wrappers=1",
                    str(out),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertIn("codec_type=subtitle", probe.stdout)
            self.assertIn("codec_name=mov_text", probe.stdout)
            self.assertIn("TAG:language=eng", probe.stdout)

    def test_burn_subtitle_command_and_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            video = tmp / "Show_E01.ts"
            video.write_bytes(b"orig")
            sub = tmp / "Show_E01.en.srt"
            sub.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n", encoding="utf-8")

            def fake_run(cmd: list[str], check: bool = False) -> MagicMock:
                Path(cmd[-1]).write_bytes(b"burned-mp4")
                res = MagicMock()
                res.returncode = 0
                return res

            with patch("kisskh_app.subtitles_mux.subprocess.run", side_effect=fake_run) as run_mock:
                out = burn_subtitle_into_video(
                    video_path=video,
                    primary_sub=sub,
                    all_sub_paths=[sub],
                    ffmpeg_bin="/usr/bin/ffmpeg-full",
                    has_libx264=True,
                    keep_srt=False,
                )

            self.assertEqual(out, tmp / "Show_E01.mp4")
            self.assertTrue(out.is_file())
            self.assertFalse(video.exists())
            self.assertFalse(sub.exists())
            called_cmd = run_mock.call_args[0][0]
            self.assertIn("-vf", called_cmd)
            vf_arg = called_cmd[called_cmd.index("-vf") + 1]
            self.assertTrue(vf_arg.startswith("subtitles='"))


class TestConsoleUIExit(unittest.TestCase):
    def test_main_menu_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = AppConfig(output_dir=tmpdir)
            app = KissKHConsoleApp(config=cfg)
            with patch("builtins.input", side_effect=["5"]), patch("click.echo"):
                app.run()


if __name__ == "__main__":
    unittest.main()
