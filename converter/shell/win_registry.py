# -*- coding: utf-8 -*-
"""Windows-only Explorer context-menu integration.

Registers a single cascading "转换 (Kurisu)" menu under each supported file
extension. The cascade contains 2-3 fixed conversions + an "用 Kurisu 打开"
entry that shells out to the GUI. The menu lives under ``HKCU`` so no admin
rights are needed and registration is fully per-user.

Layout:

  HKCU\\Software\\Classes\\SystemFileAssociations\\.mp4\\shell\\KurisuConvert
    MUIVerb      = "转换 (Kurisu)"
    Icon         = "<exe>,0"
    SubCommands  = "KurisuConvert.ToMP3;KurisuConvert.ToMKV;KurisuConvert.ToGUI"

  HKCU\\Software\\Classes\\CommandStore\\shell\\KurisuConvert.ToMP3
    (Default)    = "转为 MP3 (仅音频)"
    command
      (Default)  = "<exe>" convert "%1" -f mp3

Design notes:
  * We put the verb under ``SystemFileAssociations`` (not under a specific
    ProgID) so the menu appears regardless of which program owns the file
    extension's "open" verb.
  * CommandStore SubCommand IDs use dot notation and avoid spaces/quotes.
  * ``HKCU`` lets us install without UAC prompts; the trade-off is the
    registration is per-user rather than per-machine.

This module is safe to import on non-Windows systems; it just raises
``PlatformError`` from any of the registration calls.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


VERB_ID = "KurisuConvert"
CASCADE_TITLE = "转换 (Kurisu)"


@dataclass(frozen=True)
class SubCommand:
    subid: str            # unique id under CommandStore (no dots, no spaces)
    title: str            # menu text
    exe_args: str         # extra args appended after the exe path - %1 is the file


# One cascade across all file types. We want this small to avoid bloating
# right-click menus - the user can always pop the GUI for full control.
DEFAULT_SUBCOMMANDS: tuple[SubCommand, ...] = (
    SubCommand("ToMP3",  "转为 MP3 (仅音频)", 'convert "%1" -f mp3'),
    SubCommand("ToMP4",  "转为 MP4",          'convert "%1" -f mp4'),
    SubCommand("ToMKV",  "转为 MKV",          'convert "%1" -f mkv'),
    SubCommand("OpenUI", "用 Kurisu 打开",    '--gui'),
)


# File extensions this menu attaches to. Kept deliberately narrow.
DEFAULT_EXTENSIONS: tuple[str, ...] = (
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv",
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".srt", ".ass", ".ssa", ".vtt",
)


class PlatformError(RuntimeError):
    """Raised when shell integration is invoked on a non-Windows platform."""


def _require_windows() -> None:
    if sys.platform != "win32":
        raise PlatformError("Windows 右键集成只在 Windows 上可用。")


# ----------------------------------------------------------------------
# Pure string construction helpers (testable on any platform)
# ----------------------------------------------------------------------

def command_store_path(subid: str) -> str:
    """Registry path (relative to HKCU) for one CommandStore subcommand."""
    return rf"Software\Classes\CommandStore\shell\{VERB_ID}.{subid}"


def shell_verb_path(extension: str) -> str:
    """Registry path (relative to HKCU) for the cascade verb on an extension."""
    ext = extension if extension.startswith(".") else "." + extension
    return rf"Software\Classes\SystemFileAssociations\{ext}\shell\{VERB_ID}"


def build_command_line(exe_path: str, tail: str) -> str:
    """Concatenate exe path (quoted) and tail arguments into a registry command.

    The caller is responsible for passing ``tail`` pre-escaped if it contains
    placeholders like ``%1`` (which must stay un-quoted / already-quoted).
    """
    return f'"{exe_path}" {tail}'.rstrip()


def sub_commands_field(subcommands: tuple[SubCommand, ...]) -> str:
    """Format the ``SubCommands`` REG_SZ value (semicolon-separated)."""
    return ";".join(f"{VERB_ID}.{sc.subid}" for sc in subcommands)


# ----------------------------------------------------------------------
# Registry I/O (winreg; only usable on Windows)
# ----------------------------------------------------------------------

def _winreg():  # pragma: no cover - trivial passthrough
    """Lazy import so this module is importable on macOS/Linux for tests."""
    import winreg  # type: ignore
    return winreg


def _write_string_value(root, path: str, name: str | None, value: str) -> None:
    w = _winreg()
    with w.CreateKey(root, path) as key:
        w.SetValueEx(key, name or "", 0, w.REG_SZ, value)


def _delete_tree(root, path: str) -> bool:
    """Best-effort recursive key delete. Returns True if anything was removed."""
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
    """Install the cascading context menu for the given `exe_path`.

    Safe to call repeatedly - values are overwritten, not duplicated.
    """
    _require_windows()
    if not os.path.isfile(exe_path):
        raise FileNotFoundError(f"Executable not found: {exe_path}")

    w = _winreg()
    root = w.HKEY_CURRENT_USER

    # 1) Define each SubCommand's label + command line in CommandStore.
    for sc in subcommands:
        base = command_store_path(sc.subid)
        _write_string_value(root, base, None, sc.title)
        _write_string_value(root, base + r"\command", None,
                             build_command_line(exe_path, sc.exe_args))

    # 2) Attach the cascade verb to each file extension.
    sc_field = sub_commands_field(subcommands)
    icon_value = f'"{exe_path}",0'
    for ext in extensions:
        base = shell_verb_path(ext)
        with w.CreateKey(root, base) as key:
            w.SetValueEx(key, "MUIVerb",     0, w.REG_SZ, CASCADE_TITLE)
            w.SetValueEx(key, "Icon",        0, w.REG_SZ, icon_value)
            w.SetValueEx(key, "SubCommands", 0, w.REG_SZ, sc_field)


def unregister(
    *,
    extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
    subcommands: tuple[SubCommand, ...] = DEFAULT_SUBCOMMANDS,
) -> None:
    """Remove everything `register` wrote. Safe to call when not registered."""
    _require_windows()
    w = _winreg()
    root = w.HKEY_CURRENT_USER

    for ext in extensions:
        _delete_tree(root, shell_verb_path(ext))
    for sc in subcommands:
        _delete_tree(root, command_store_path(sc.subid))


def is_registered(extensions: tuple[str, ...] = DEFAULT_EXTENSIONS) -> bool:
    """Return True when at least one of the known extensions has our verb."""
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
