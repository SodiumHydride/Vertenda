# -*- coding: utf-8 -*-
"""Windows-only Explorer context-menu integration.

Registers a single cascading "转换 (Kurisu)" menu under each supported file
extension. The cascade exposes a few quick conversions + "用 Kurisu 打开" and
lives entirely under ``HKCU`` so no admin rights are required.

Registry layout (per-user, no admin)::

    HKCU\\Software\\Classes\\SystemFileAssociations\\.mp4\\shell\\KurisuConvert
        MUIVerb                 = "转换 (Kurisu)"
        Icon                    = "<exe>,0"
        ExtendedSubCommandsKey  = "Software\\Classes\\Vertenda.KurisuCascade"

    HKCU\\Software\\Classes\\Vertenda.KurisuCascade\\shell\\ToMP3
        (Default) = "转为 MP3 (仅音频)"
        Icon      = "<exe>,0"
    HKCU\\Software\\Classes\\Vertenda.KurisuCascade\\shell\\ToMP3\\command
        (Default) = "\"<exe>\" convert \"%1\" -f mp3"

Why ``ExtendedSubCommandsKey`` and not ``SubCommands``
------------------------------------------------------
``SubCommands`` is resolved by Explorer against one fixed machine-wide path:
``HKLM\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\CommandStore\\shell``.
Writing there needs admin rights, and nothing else will do - Explorer does not
fall back to ``HKCU\\Software\\Classes\\CommandStore\\shell`` (which is where
earlier versions of this module wrote, causing cascades to render as empty
submenus). ``ExtendedSubCommandsKey`` lets Explorer read the cascade from any
sub-tree we point it at; it is supported since Windows 7 and works cleanly in
the per-user hive.

Upgrade path
------------
``unregister()`` also scrubs the legacy-layout keys written by earlier
versions of this module (flat ``SubCommands`` value + stray
``HKCU\\...\\CommandStore\\shell\\KurisuConvert.*`` entries), so toggling the
checkbox once on an upgraded install cleans up old state transparently.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


VERB_ID = "KurisuConvert"
CASCADE_TITLE = "转换 (Kurisu)"

# Container for the extended-subcommand tree. Dotted pseudo-ProgID keeps it
# out of conventional ProgID lookups while still living in Software\Classes.
CASCADE_ROOT_REL = r"Software\Classes\Vertenda.KurisuCascade"

# Historical (broken) subcommand location used by earlier versions. Kept as a
# constant so unregister() can scrub leftovers after an upgrade.
_LEGACY_COMMAND_STORE_REL = r"Software\Classes\CommandStore\shell"


# Extended-verb command flags - see ntshellapi.h / Raymond Chen's archive.
CF_SEPARATOR_BEFORE = 0x20
CF_SEPARATOR_AFTER = 0x40


@dataclass(frozen=True)
class SubCommand:
    subid: str                       # unique id, no dots / spaces
    title: str                       # visible label
    exe_args: str                    # tail appended after exe path; %1 is the file
    separator_before: bool = False   # draw a menu separator above this entry
    position: str = ""               # "Top" | "Bottom" | "" (default ordering)


# One cascade shared across every supported file type. Kept deliberately
# short - the GUI is always a click away via "用 Kurisu 打开".
DEFAULT_SUBCOMMANDS: tuple[SubCommand, ...] = (
    SubCommand("ToMP3",  "转为 MP3 (仅音频)", 'convert "%1" -f mp3'),
    SubCommand("ToMP4",  "转为 MP4",          'convert "%1" -f mp4'),
    SubCommand("ToMKV",  "转为 MKV",          'convert "%1" -f mkv'),
    SubCommand("OpenUI", "用 Kurisu 打开",    '--gui',
               separator_before=True),
)


DEFAULT_EXTENSIONS: tuple[str, ...] = (
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv",
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".srt", ".ass", ".ssa", ".vtt",
)


# Extension classification for the cascade-parent fallback command.
# When a user's shell fails to expand the cascade submenu (e.g. Windows 11's
# compact context menu), clicking the parent item still needs to Do Something
# Useful instead of erroring out or opening the GUI. The mapping below picks
# a sensible "quick convert" target per input type so the click completes the
# conversion in the background without any extra UI.
_VIDEO_PARENT_EXTS = frozenset({
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv", ".ts", ".rmvb",
})
_AUDIO_PARENT_EXTS = frozenset({
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
})
_SUBTITLE_PARENT_EXTS = frozenset({
    ".srt", ".ass", ".ssa", ".vtt", ".lrc",
})


def parent_fallback_args(extension: str) -> str:
    """Return the ``tail`` for the cascade-parent direct command on *extension*.

    The returned string is ``convert "%1" -f <target>`` with a target format
    that's safe to apply even when the input shares the same extension — the
    CLI deduplicates output filenames so ``foo.mp4 -> foo_1.mp4`` instead of
    clobbering the source.
    """
    ext = extension.lower() if extension.startswith(".") else "." + extension.lower()
    if ext in _VIDEO_PARENT_EXTS:
        return 'convert "%1" -f mp4'
    if ext in _AUDIO_PARENT_EXTS:
        return 'convert "%1" -f mp3'
    if ext in _SUBTITLE_PARENT_EXTS:
        return 'convert "%1" -f srt'
    # Unknown extension: open the GUI with the file preloaded. This branch is
    # only reachable if a caller extends DEFAULT_EXTENSIONS without updating
    # the classification sets above.
    return '--gui "%1"'


class PlatformError(RuntimeError):
    """Raised when shell integration is invoked on a non-Windows platform."""


def _require_windows() -> None:
    if sys.platform != "win32":
        raise PlatformError("Windows 右键集成只在 Windows 上可用。")


# ----------------------------------------------------------------------
# Pure string builders (testable on any platform)
# ----------------------------------------------------------------------

def shell_verb_path(extension: str) -> str:
    """HKCU-relative path of the cascade verb on one extension."""
    ext = extension if extension.startswith(".") else "." + extension
    return rf"Software\Classes\SystemFileAssociations\{ext}\shell\{VERB_ID}"


def cascade_root_path() -> str:
    """HKCU-relative path of the extended-subcommand container key."""
    return CASCADE_ROOT_REL


def extended_subcommand_path(subid: str) -> str:
    """HKCU-relative path of one entry inside the cascade."""
    return rf"{CASCADE_ROOT_REL}\shell\{subid}"


def legacy_command_store_path(subid: str) -> str:
    """HKCU-relative path of the *old* subcommand location.

    Used only by ``unregister`` for cleanup of pre-upgrade installs; new
    registrations do not write here.
    """
    return rf"{_LEGACY_COMMAND_STORE_REL}\{VERB_ID}.{subid}"


def build_command_line(exe_path: str, tail: str) -> str:
    """Concatenate the exe path (always quoted) and tail args.

    ``tail`` is written verbatim; callers are responsible for keeping any
    ``%1`` placeholders already quoted to survive paths with spaces.
    """
    return f'"{exe_path}" {tail}'.rstrip()


def sub_commands_field(subcommands: tuple[SubCommand, ...]) -> str:
    """Format the flat ``SubCommands`` REG_SZ value.

    Retained for callers/tests that still reason about the classic shape;
    the current ``register`` implementation no longer writes it.
    """
    return ";".join(f"{VERB_ID}.{sc.subid}" for sc in subcommands)


# ----------------------------------------------------------------------
# winreg wrappers (only importable on Windows)
# ----------------------------------------------------------------------

def _winreg():  # pragma: no cover - trivial passthrough
    import winreg  # type: ignore
    return winreg


def _write_string(root, path: str, name: str | None, value: str) -> None:
    w = _winreg()
    with w.CreateKey(root, path) as key:
        w.SetValueEx(key, name or "", 0, w.REG_SZ, value)


def _write_dword(root, path: str, name: str, value: int) -> None:
    w = _winreg()
    with w.CreateKey(root, path) as key:
        w.SetValueEx(key, name, 0, w.REG_DWORD, value)


def _delete_value(root, path: str, name: str) -> None:
    """Best-effort single-value delete; silent on missing key/value."""
    w = _winreg()
    try:
        hkey = w.OpenKey(root, path, 0, w.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return
    try:
        try:
            w.DeleteValue(hkey, name)
        except FileNotFoundError:
            pass
    finally:
        w.CloseKey(hkey)


def _delete_tree(root, path: str) -> bool:
    """Recursive registry-key delete. Returns True if anything was removed."""
    w = _winreg()
    try:
        hkey = w.OpenKey(root, path, 0, w.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return False
    try:
        while True:
            try:
                child = w.EnumKey(hkey, 0)
            except OSError:
                break
            _delete_tree(root, path + "\\" + child)
    finally:
        w.CloseKey(hkey)
    try:
        w.DeleteKey(root, path)
    except OSError:
        return False
    return True


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def register(
    exe_path: str,
    *,
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    subcommands: tuple[SubCommand, ...] = DEFAULT_SUBCOMMANDS,
) -> None:
    """Install the cascading Explorer context menu under HKCU.

    Idempotent: re-running overwrites values, never duplicates. Any prior
    legacy-layout keys from earlier versions are removed first so the new
    menu is not shadowed by stale ``SubCommands`` wiring.
    """
    _require_windows()
    if not os.path.isfile(exe_path):
        raise FileNotFoundError(f"Executable not found: {exe_path}")

    w = _winreg()
    root = w.HKEY_CURRENT_USER

    # Scrub legacy layout so Explorer cannot read a mix of old + new values.
    _cleanup_legacy(root, extensions, subcommands)

    icon_value = f'"{exe_path}",0'

    # 1) Cascade entries under the extended-subcommand tree.
    for sc in subcommands:
        base = extended_subcommand_path(sc.subid)
        _write_string(root, base, None, sc.title)
        _write_string(root, base, "Icon", icon_value)
        if sc.position:
            _write_string(root, base, "Position", sc.position)
        flags = 0
        if sc.separator_before:
            flags |= CF_SEPARATOR_BEFORE
        if flags:
            _write_dword(root, base, "CommandFlags", flags)
        _write_string(root, base + r"\command", None,
                      build_command_line(exe_path, sc.exe_args))

    # 2) Top-level verb on each extension, pointing into the cascade root.
    #
    # Some Windows shells (notably the Windows 11 compact context menu) don't
    # expand ExtendedSubCommandsKey cascades and instead surface the parent
    # verb as a single clickable item. Without a direct command that click
    # yields either "No application is associated..." or (with a --gui
    # fallback) an empty GUI — neither matches the "quick convert" intent.
    # Per-extension fallback: dispatch straight to a sensible convert target
    # so clicking the parent actually performs the conversion in the
    # background, saving output next to the source file.
    cascade_rel = cascade_root_path()
    for ext in extensions:
        verb = shell_verb_path(ext)
        with w.CreateKey(root, verb) as key:
            w.SetValueEx(key, "MUIVerb",                0, w.REG_SZ, CASCADE_TITLE)
            w.SetValueEx(key, "Icon",                   0, w.REG_SZ, icon_value)
            w.SetValueEx(key, "ExtendedSubCommandsKey", 0, w.REG_SZ, cascade_rel)
        _write_string(root, verb + r"\command", None,
                      build_command_line(exe_path, parent_fallback_args(ext)))
        # Remove the obsolete SubCommands value if an older build left it behind.
        _delete_value(root, verb, "SubCommands")


def unregister(
    *,
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    subcommands: tuple[SubCommand, ...] = DEFAULT_SUBCOMMANDS,
) -> None:
    """Remove everything ``register`` writes, including legacy leftovers."""
    _require_windows()
    w = _winreg()
    root = w.HKEY_CURRENT_USER

    for ext in extensions:
        _delete_tree(root, shell_verb_path(ext))

    _delete_tree(root, cascade_root_path())
    _cleanup_legacy(root, extensions, subcommands)


def is_registered(extensions: tuple[str, ...] = DEFAULT_EXTENSIONS) -> bool:
    """True iff at least one of the known extensions carries our verb."""
    if sys.platform != "win32":
        return False
    w = _winreg()
    root = w.HKEY_CURRENT_USER
    for ext in extensions:
        try:
            w.OpenKey(root, shell_verb_path(ext)).Close()
            return True
        except FileNotFoundError:
            continue
    return False


# ----------------------------------------------------------------------
# Legacy cleanup
# ----------------------------------------------------------------------

def _cleanup_legacy(
    root,
    extensions: tuple[str, ...],
    subcommands: tuple[SubCommand, ...],
) -> None:
    # Old subcommand locations from the pre-ExtendedSubCommandsKey layout.
    for sc in subcommands:
        _delete_tree(root, legacy_command_store_path(sc.subid))
    # Stale SubCommands value on each verb. The verb key itself is reused
    # by the new registration, so only the value is cleared here.
    for ext in extensions:
        _delete_value(root, shell_verb_path(ext), "SubCommands")
