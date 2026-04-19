# -*- coding: utf-8 -*-
"""CLI smoke tests: argv normalisation, where command, dispatch routing."""

from __future__ import annotations

import os
import sys

import pytest

from converter import cli
from converter.cli import _KNOWN_SUBCOMMANDS, _normalise_argv, build_parser


class TestArgvNormalisation:
    def test_explicit_subcommand_unchanged(self):
        assert _normalise_argv(["convert", "a.wav", "-f", "mp3"]) == \
               ["convert", "a.wav", "-f", "mp3"]

    def test_known_subcommands_pass_through(self):
        for sub in _KNOWN_SUBCOMMANDS:
            argv = [sub]
            assert _normalise_argv(argv) == argv

    def test_implicit_convert_gets_prepended(self):
        assert _normalise_argv(["a.wav", "-f", "mp3"]) == \
               ["convert", "a.wav", "-f", "mp3"]

    def test_flags_first_unchanged(self):
        """`convert --gui` is passed through so --gui bypasses subparser."""
        assert _normalise_argv(["--gui"]) == ["--gui"]

    def test_empty_unchanged(self):
        assert _normalise_argv([]) == []


class TestParser:
    def test_help_does_not_crash(self, capsys):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--help"])
        out = capsys.readouterr().out
        assert "convert" in out
        assert "burn" in out

    def test_convert_subcommand_accepts_input(self):
        parser = build_parser()
        args = parser.parse_args(["convert", "in.wav", "-f", "mp3"])
        assert args.input == "in.wav"
        assert args.format == "mp3"

    def test_burn_requires_two_positionals(self):
        parser = build_parser()
        args = parser.parse_args(["burn", "v.mp4", "s.srt", "-o", "out.mp4"])
        assert args.video == "v.mp4"
        assert args.subtitle == "s.srt"
        assert args.output == "out.mp4"

    def test_quality_choices_enforced(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["convert", "in.wav", "-f", "mp3", "-q", "potato"])


class TestWhere:
    def test_where_prints_paths(self, capsys):
        exit_code = cli.cmd_where(None)  # type: ignore[arg-type]
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "ffmpeg" in out
        assert "cache dir" in out


class TestUninstallFfmpegNoOp:
    def test_uninstall_when_nothing_installed(self, capsys, monkeypatch):
        """Uninstall should be idempotent when no cache exists."""
        from converter.ffmpeg import installer
        monkeypatch.setattr(installer, "installed_by_us", lambda: False)
        exit_code = cli.cmd_uninstall_ffmpeg(None)  # type: ignore[arg-type]
        assert exit_code == 0


class TestEndToEndFfmpeg:
    """Requires a working ffmpeg; skipped otherwise (CI-safe)."""

    def test_wav_to_mp3_via_cli(self, tmp_path):
        import subprocess
        from converter.constants import FFMPEG_PATH
        from converter.ffmpeg.probe import check_ffmpeg_available

        if not check_ffmpeg_available():
            pytest.skip("ffmpeg not available")

        src = tmp_path / "in.wav"
        subprocess.run(
            [FFMPEG_PATH, "-y", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=1",
             "-ac", "1", "-ar", "16000", str(src)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        out = tmp_path / "out.mp3"

        exit_code = cli.main([str(src), "-f", "mp3", "-o", str(out)])
        assert exit_code == 0
        assert out.is_file()
        assert out.stat().st_size > 0
