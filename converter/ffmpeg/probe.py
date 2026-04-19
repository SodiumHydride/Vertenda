# -*- coding: utf-8 -*-
"""Media inspection helpers."""

from __future__ import annotations

import subprocess

from .. import constants


def get_media_duration(path: str) -> float | None:
    """Return duration in seconds, or None if ffprobe can't determine it."""
    cmd = [
        constants.FFPROBE_PATH,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    try:
        cp = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore",
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if cp.returncode != 0:
        return None
    try:
        return float(cp.stdout.strip())
    except ValueError:
        return None


def check_ffmpeg_available() -> bool:
    """Quick smoke test to verify the currently resolved ffmpeg is usable."""
    try:
        cp = subprocess.run(
            [constants.FFMPEG_PATH, "-version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return cp.returncode == 0
    except (FileNotFoundError, OSError):
        return False
