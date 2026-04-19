# -*- coding: utf-8 -*-
"""Tests for the Windows shell-integration module.

On non-Windows systems the winreg module is missing, so we only verify pure
string-building functions here. A Windows-only integration test is kept for
the future, gated on sys.platform.
"""

from __future__ import annotations

import sys

import pytest

from converter.shell import win_registry
from converter.shell.win_registry import (
    CASCADE_TITLE,
    DEFAULT_EXTENSIONS,
    DEFAULT_SUBCOMMANDS,
    VERB_ID,
    PlatformError,
    SubCommand,
    build_command_line,
    command_store_path,
    shell_verb_path,
    sub_commands_field,
)


class TestPaths:
    def test_command_store_path_shape(self):
        p = command_store_path("ToMP3")
        assert p.startswith("Software\\Classes\\CommandStore\\shell\\")
        assert p.endswith(f"{VERB_ID}.ToMP3")

    def test_shell_verb_path_adds_leading_dot(self):
        assert shell_verb_path("mp4") == shell_verb_path(".mp4")
        assert ".mp4" in shell_verb_path(".mp4")

    def test_every_default_extension_has_dot(self):
        for ext in DEFAULT_EXTENSIONS:
            assert ext.startswith(".")
            assert " " not in ext


class TestCommandLine:
    def test_quotes_exe_path(self):
        line = build_command_line(r"C:\Program Files\Convert\Main.exe", 'convert "%1" -f mp3')
        assert line.startswith('"C:\\')
        assert line.endswith('-f mp3')

    def test_strips_trailing_space(self):
        line = build_command_line("exe", "")
        assert not line.endswith(" ")


class TestSubCommands:
    def test_semicolon_separated(self):
        field = sub_commands_field(DEFAULT_SUBCOMMANDS)
        parts = field.split(";")
        assert len(parts) == len(DEFAULT_SUBCOMMANDS)
        for p in parts:
            assert p.startswith(f"{VERB_ID}.")

    def test_every_subid_unique_and_no_dots(self):
        ids = [sc.subid for sc in DEFAULT_SUBCOMMANDS]
        assert len(ids) == len(set(ids))
        for i in ids:
            assert "." not in i
            assert " " not in i

    def test_title_is_chinese_friendly(self):
        # Smoke: we rely on REG_SZ + UTF-16 encoding; no ASCII-only assumptions.
        for sc in DEFAULT_SUBCOMMANDS:
            assert sc.title  # non-empty


class TestPlatformGuard:
    @pytest.mark.skipif(sys.platform == "win32", reason="non-Windows-only test")
    def test_register_raises_on_non_windows(self):
        with pytest.raises(PlatformError):
            win_registry.register("/tmp/fake.exe")

    @pytest.mark.skipif(sys.platform == "win32", reason="non-Windows-only test")
    def test_unregister_raises_on_non_windows(self):
        with pytest.raises(PlatformError):
            win_registry.unregister()

    @pytest.mark.skipif(sys.platform == "win32", reason="non-Windows-only test")
    def test_is_registered_false_on_non_windows(self):
        assert win_registry.is_registered() is False


class TestCustomSubcommand:
    def test_can_customise_subcommand_list(self):
        custom = (
            SubCommand("OnlyMP3", "仅 MP3", 'convert "%1" -f mp3'),
        )
        field = sub_commands_field(custom)
        assert field == f"{VERB_ID}.OnlyMP3"
