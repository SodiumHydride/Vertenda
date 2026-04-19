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
    CUSTOM_DATA_DIR = "custom_data_dir"
    # Last-used selections per tab.
    LAST_AUDIO_FORMAT = "last_audio_format"
    LAST_VIDEO_FORMAT = "last_video_format"
    LAST_SUBTITLE_FORMAT = "last_subtitle_format"
    LAST_BURN_MODE = "last_burn_mode"
    LAST_BURN_OUTPUT_FORMAT = "last_burn_output_format"
    # ---- Phase 0+ additions ----
    DEFAULT_CONFLICT_POLICY = "default_conflict_policy"       # "skip"/"overwrite"/"rename"/"ask"
    DEFAULT_FILENAME_TEMPLATE = "default_filename_template"   # "{base}" etc.
    DEFAULT_MIRROR_SUBDIRS = "default_mirror_subdirs"
    DEFAULT_CONTINUE_ON_FAILURE = "default_continue_on_failure"
    CONCURRENCY_MODE = "concurrency_mode"                     # "auto" / "1" .. "8"
    NOTIFY_ON_COMPLETE = "notify_on_complete"
    SOUND_ON_COMPLETE = "sound_on_complete"
    OPEN_OUTPUT_ON_COMPLETE = "open_output_on_complete"
    TASK_HISTORY = "task_history"                              # JSON
    CUSTOM_BURN_STYLE = "custom_burn_style"                   # JSON
    LAST_AUDIO_PRESET = "last_audio_preset"
    LAST_VIDEO_PRESET = "last_video_preset"
    LAST_SUBTITLE_PRESET = "last_subtitle_preset"
    LAST_BURN_PRESET = "last_burn_preset"


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


def _common_install_dirs() -> list[str]:
    """Known package-manager install directories per platform.

    macOS .app bundles launched from Finder do NOT inherit the shell PATH,
    so ``shutil.which`` cannot see ``/opt/homebrew/bin/ffmpeg`` even when
    Homebrew has it. We probe the usual prefixes explicitly as a safety net.
    """
    if sys.platform == "darwin":
        return [
            "/opt/homebrew/bin",        # Apple Silicon Homebrew
            "/usr/local/bin",           # Intel Homebrew / manual installs
            "/opt/local/bin",           # MacPorts
            "/usr/bin", "/bin",
        ]
    if sys.platform == "win32":
        return [
            r"C:\Program Files\ffmpeg\bin",
            r"C:\Program Files (x86)\ffmpeg\bin",
            r"C:\ffmpeg\bin",
            r"C:\ProgramData\chocolatey\bin",
        ]
    # Linux / BSD
    return ["/usr/local/bin", "/usr/bin", "/bin", "/snap/bin"]


def _probe_executable(path: str) -> bool:
    """Return True iff `path` is a runnable binary. Swallows all process errors."""
    import subprocess
    try:
        cp = subprocess.run(
            [path, "-version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=3,
        )
        return cp.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _app_data_cached_path(fallback_name: str) -> str:
    """Path inside our app-data cache, if one is set up already."""
    # Lazy import to avoid a circular dependency with the installer module.
    from .ffmpeg.installer import ffmpeg_cache_dir

    exe = fallback_name + (".exe" if sys.platform == "win32" else "")
    return str(ffmpeg_cache_dir() / exe)


def _resolve_executable(base_rel: str, fallback_name: str) -> str:
    """Locate a usable ffmpeg/ffprobe binary.

    Search order (first runnable wins):
      1. The bundled binary under ``resources/`` (tested by actually running
         ``-version`` to confirm dylibs/DLLs resolve).
      2. The auto-installed copy in our per-user app-data cache.
      3. The system PATH via ``shutil.which``.
      4. Common per-platform install prefixes (so a Finder-launched .app can
         still see ``/opt/homebrew/bin/ffmpeg``).

    If nothing runs, we return the bundled candidate path so error messages
    name the expected location.
    """
    import shutil

    for bundled in _candidate_bundled_paths(base_rel):
        if os.path.exists(bundled) and _probe_executable(bundled):
            return bundled

    cached = _app_data_cached_path(fallback_name)
    if os.path.isfile(cached) and _probe_executable(cached):
        return cached

    on_path = shutil.which(fallback_name)
    if on_path:
        return on_path

    exe_name = fallback_name + (".exe" if sys.platform == "win32" else "")
    for directory in _common_install_dirs():
        candidate = os.path.join(directory, exe_name)
        if os.path.isfile(candidate) and _probe_executable(candidate):
            return candidate

    return _candidate_bundled_paths(base_rel)[0]


def resolve_ffmpeg_paths() -> tuple[str, str]:
    """Re-run the search for ffmpeg+ffprobe.

    Used after the first-run installer populates the cache dir so the running
    process can pick up the freshly-downloaded binaries without a restart.
    """
    return (
        _resolve_executable("resources/ffmpeg", "ffmpeg"),
        _resolve_executable("resources/ffprobe", "ffprobe"),
    )


FFMPEG_PATH: str
FFPROBE_PATH: str
FFMPEG_PATH, FFPROBE_PATH = resolve_ffmpeg_paths()


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
