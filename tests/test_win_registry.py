# -*- coding: utf-8 -*-
"""Tests for the Windows shell-integration module.

On non-Windows systems ``winreg`` is missing, so we exercise the pure
string-building helpers everywhere and gate the actual registry I/O behind
``sys.platform``.
"""

from __future__ import annotations

import sys

import pytest

from converter.shell import win_registry
from converter.shell.win_registry import (
    CASCADE_ROOT_REL,
    CASCADE_TITLE,
    CF_SEPARATOR_BEFORE,
    DEFAULT_EXTENSIONS,
    DEFAULT_SUBCOMMANDS,
    VERB_ID,
    PlatformError,
    SubCommand,
    build_command_line,
    cascade_root_path,
    extended_subcommand_path,
    legacy_command_store_path,
    parent_fallback_args,
    shell_verb_path,
    sub_commands_field,
)


class TestPaths:
    def test_cascade_root_lives_in_hkcu_software_classes(self):
        root = cascade_root_path()
        assert root == CASCADE_ROOT_REL
        assert root.startswith("Software\\Classes\\")

    def test_cascade_root_does_not_sit_under_command_store(self):
        # The old (broken) layout placed subcommands under
        # Software\Classes\CommandStore\shell, which Explorer does not read.
        # Guard against regressing to that location.
        assert "CommandStore" not in cascade_root_path()

    def test_extended_subcommand_path_shape(self):
        p = extended_subcommand_path("ToMP3")
        assert p.startswith(f"{CASCADE_ROOT_REL}\\shell\\")
        assert p.endswith("ToMP3")

    def test_legacy_path_still_points_at_command_store(self):
        # ``unregister`` relies on this pointing at the historical (broken)
        # location so pre-existing installs get scrubbed on upgrade.
        legacy = legacy_command_store_path("ToMP3")
        assert "CommandStore" in legacy
        assert legacy.endswith(f"{VERB_ID}.ToMP3")

    def test_shell_verb_path_adds_leading_dot(self):
        assert shell_verb_path("mp4") == shell_verb_path(".mp4")
        assert ".mp4" in shell_verb_path(".mp4")

    def test_every_default_extension_has_dot(self):
        for ext in DEFAULT_EXTENSIONS:
            assert ext.startswith(".")
            assert " " not in ext


class TestCommandLine:
    def test_quotes_exe_path(self):
        line = build_command_line(r"C:\Program Files\Vertenda\Vertenda.exe",
                                   'convert "%1" -f mp3')
        assert line.startswith('"C:\\')
        assert line.endswith('-f mp3')

    def test_strips_trailing_space(self):
        line = build_command_line("exe", "")
        assert not line.endswith(" ")


class TestSubCommands:
    def test_sub_commands_field_is_semicolon_separated(self):
        field = sub_commands_field(DEFAULT_SUBCOMMANDS)
        parts = field.split(";")
        assert len(parts) == len(DEFAULT_SUBCOMMANDS)
        for p in parts:
            assert p.startswith(f"{VERB_ID}.")

    def test_every_subid_unique_and_safe(self):
        ids = [sc.subid for sc in DEFAULT_SUBCOMMANDS]
        assert len(ids) == len(set(ids))
        for i in ids:
            assert "." not in i
            assert " " not in i

    def test_title_is_chinese_friendly(self):
        for sc in DEFAULT_SUBCOMMANDS:
            # REG_SZ + winreg's implicit UTF-16 encoding - non-empty is enough.
            assert sc.title

    def test_cascade_title_is_the_top_level_label(self):
        assert CASCADE_TITLE
        assert CASCADE_TITLE != ""


class TestSeparatorFlag:
    def test_open_ui_has_separator_before(self):
        open_ui = next(sc for sc in DEFAULT_SUBCOMMANDS if sc.subid == "OpenUI")
        assert open_ui.separator_before is True

    def test_other_entries_have_no_separator(self):
        for sc in DEFAULT_SUBCOMMANDS:
            if sc.subid == "OpenUI":
                continue
            assert sc.separator_before is False

    def test_command_flag_bit_matches_shellapi(self):
        # 0x20 == ECF_SEPARATORBEFORE in Windows SDK headers.
        assert CF_SEPARATOR_BEFORE == 0x20


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

    def test_separator_is_opt_in(self):
        sc = SubCommand("X", "x", "")
        assert sc.separator_before is False
        assert sc.position == ""


class TestParentFallback:
    """The cascade-parent command that fires when Explorer fails to expand
    the submenu (Windows 11 compact context menu). Must perform a direct
    conversion, never open the GUI, and never be empty."""

    def test_video_extensions_fallback_to_mp4_convert(self):
        for ext in (".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv"):
            tail = parent_fallback_args(ext)
            assert tail.startswith("convert "), f"{ext}: {tail}"
            assert tail.endswith("-f mp4"), f"{ext}: {tail}"

    def test_audio_extensions_fallback_to_mp3_convert(self):
        for ext in (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus"):
            tail = parent_fallback_args(ext)
            assert tail.startswith("convert "), f"{ext}: {tail}"
            assert tail.endswith("-f mp3"), f"{ext}: {tail}"

    def test_subtitle_extensions_fallback_to_srt_convert(self):
        for ext in (".srt", ".ass", ".ssa", ".vtt"):
            tail = parent_fallback_args(ext)
            assert tail.startswith("convert "), f"{ext}: {tail}"
            assert tail.endswith("-f srt"), f"{ext}: {tail}"

    def test_case_insensitive_and_dot_tolerant(self):
        assert parent_fallback_args("MP4") == parent_fallback_args(".mp4")
        assert parent_fallback_args(".MP4") == parent_fallback_args(".mp4")

    def test_every_default_extension_resolves_to_convert(self):
        # Regression guard: every shipped extension must get a concrete
        # conversion target. If this fires, either DEFAULT_EXTENSIONS grew
        # a new type or the classification sets drifted out of sync.
        for ext in DEFAULT_EXTENSIONS:
            assert parent_fallback_args(ext).startswith("convert "), ext

    def test_unknown_extension_falls_back_to_gui(self):
        tail = parent_fallback_args(".unknownext")
        assert "--gui" in tail
        assert '"%1"' in tail
