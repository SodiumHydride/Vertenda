# -*- coding: utf-8 -*-
"""Shared constants, extensions, and resource path helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path

AUDIO_EXTS: frozenset[str] = frozenset({
    ".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".wma", ".opus",
})

VIDEO_EXTS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv", ".webm", ".ts", ".rmvb",
})

SUBTITLE_EXTS: frozenset[str] = frozenset({
    ".srt", ".ass", ".ssa", ".vtt", ".lrc",
})

LRC_EXT = ".lrc"

AUDIO_FORMATS: tuple[str, ...] = ("mp3", "wav", "flac", "aac", "ogg", "opus")
VIDEO_FORMATS: tuple[str, ...] = (
    "mp4", "mkv", "mov", "avi", "flv", "wmv", "webm", "ts", "rmvb",
)
SUBTITLE_FORMATS: tuple[str, ...] = ("lrc", "srt", "vtt", "ass", "ssa")
BURN_OUTPUT_FORMATS: tuple[str, ...] = ("mp4", "mkv")


# Hard-coded style for subtitle burning: pink text, black outline, Arial.
DEFAULT_BURN_STYLE: str = (
    "FontName=Arial,"
    "PrimaryColour=&H00FFC0CB,"
    "OutlineColour=&H00000000,"
    "BorderStyle=1,"
    "Outline=2,"
    "Shadow=0"
)


# Settings keys - centralized so a typo fails at import rather than silently at runtime.
class SettingsKey:
    BG_PATH = "bg_path"
    BG_ALPHA = "bg_alpha"
    THEME_MODE = "theme_mode"
    FONT_SIZE = "font_size"
    OUTPUT_PATH = "output_path"
    USE_HW_ACCEL = "use_hw_accel"
    QUALITY_PRESET = "quality_preset"   # "fast" / "balanced" / "high"
    OVERLAY_STRENGTH = "overlay_strength"  # 0..100: readability overlay opacity
    # Last-used selections per tab, so reopening the app feels familiar.
    LAST_AUDIO_FORMAT = "last_audio_format"
    LAST_VIDEO_FORMAT = "last_video_format"
    LAST_SUBTITLE_FORMAT = "last_subtitle_format"
    LAST_BURN_MODE = "last_burn_mode"
    LAST_BURN_OUTPUT_FORMAT = "last_burn_output_format"


# Video-to-audio extraction pseudo-format, selectable on the video tab so
# users don't have to switch tabs just to strip a track.
VIDEO_EXTRACT_AUDIO_SENTINEL = "audio-only"


def resource_path(relative: str) -> str:
    """Resolve a resource path whether running from source or a PyInstaller bundle."""
    if hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    return str(base / relative)


def app_runtime_dir() -> str:
    """Return the directory where per-user runtime files (config, output) live."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return str(Path(__file__).resolve().parent.parent)


def _candidate_bundled_paths(base_rel: str) -> list[str]:
    """Candidate bundled binary paths, accounting for Windows '.exe' suffix."""
    candidates = [resource_path(base_rel)]
    if sys.platform == "win32":
        candidates.insert(0, resource_path(base_rel + ".exe"))
    return candidates


def _resolve_executable(base_rel: str, fallback_name: str) -> str:
    """Prefer the bundled binary; fall back to PATH if it is missing or unusable.

    The bundled ffmpeg can silently fail to run when it was built against
    Homebrew dylibs that are not present on the user's machine. Rather than
    force the user to diagnose a dyld error, degrade gracefully to whatever
    ffmpeg is on PATH.
    """
    import shutil
    import subprocess

    for bundled in _candidate_bundled_paths(base_rel):
        if not os.path.exists(bundled):
            continue
        try:
            result = subprocess.run(
                [bundled, "-version"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=3,
            )
            if result.returncode == 0:
                return bundled
        except (OSError, subprocess.SubprocessError):
            continue

    on_path = shutil.which(fallback_name)
    if on_path:
        return on_path
    # Return the first candidate so error messages name the expected location.
    return _candidate_bundled_paths(base_rel)[0]


FFMPEG_PATH: str = _resolve_executable("resources/ffmpeg", "ffmpeg")
FFPROBE_PATH: str = _resolve_executable("resources/ffprobe", "ffprobe")


def ext_of(path: str) -> str:
    """Return lower-cased extension including the leading dot."""
    return os.path.splitext(path)[1].lower()


def is_audio_file(path: str) -> bool:
    return ext_of(path) in AUDIO_EXTS


def is_video_file(path: str) -> bool:
    return ext_of(path) in VIDEO_EXTS


def is_subtitle_file(path: str) -> bool:
    return ext_of(path) in SUBTITLE_EXTS


def is_lrc_file(path: str) -> bool:
    return ext_of(path) == LRC_EXT
