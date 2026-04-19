# -*- coding: utf-8 -*-
"""Media inspection helpers."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Optional

from .. import constants


@dataclass
class ProbeInfo:
    """Rich metadata from ffprobe for a single file."""
    duration_s: float = 0.0
    video_codec: str = ""
    audio_codec: str = ""
    width: int = 0
    height: int = 0
    video_bitrate: int = 0
    audio_bitrate: int = 0
    audio_channels: int = 0
    audio_sample_rate: int = 0
    format_name: str = ""
    file_size: int = 0

    @property
    def resolution_label(self) -> str:
        if self.width and self.height:
            return f"{self.width}x{self.height}"
        return ""

    def summary_text(self) -> str:
        lines: list[str] = []
        if self.format_name:
            lines.append(f"格式: {self.format_name}")
        if self.duration_s > 0:
            m, s = divmod(int(self.duration_s), 60)
            h, m = divmod(m, 60)
            lines.append(f"时长: {h:02d}:{m:02d}:{s:02d}")
        if self.resolution_label:
            lines.append(f"分辨率: {self.resolution_label}")
        if self.video_codec:
            vbr = f" · {self.video_bitrate // 1000} kbps" if self.video_bitrate else ""
            lines.append(f"视频: {self.video_codec}{vbr}")
        if self.audio_codec:
            abr = f" · {self.audio_bitrate // 1000} kbps" if self.audio_bitrate else ""
            ch = f" · {self.audio_channels}ch" if self.audio_channels else ""
            sr = f" · {self.audio_sample_rate} Hz" if self.audio_sample_rate else ""
            lines.append(f"音频: {self.audio_codec}{abr}{ch}{sr}")
        if self.file_size > 0:
            if self.file_size < 1024 * 1024:
                lines.append(f"大小: {self.file_size / 1024:.1f} KB")
            elif self.file_size < 1024 * 1024 * 1024:
                lines.append(f"大小: {self.file_size / 1024 / 1024:.1f} MB")
            else:
                lines.append(f"大小: {self.file_size / 1024 / 1024 / 1024:.2f} GB")
        return "\n".join(lines) if lines else "(无信息)"


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


def probe_full(path: str) -> Optional[ProbeInfo]:
    """Run ffprobe JSON output and return structured ProbeInfo."""
    cmd = [
        constants.FFPROBE_PATH,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
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
        data = json.loads(cp.stdout)
    except (json.JSONDecodeError, ValueError):
        return None

    info = ProbeInfo()
    fmt = data.get("format", {})
    info.duration_s = float(fmt.get("duration", 0) or 0)
    info.format_name = fmt.get("format_long_name", "") or fmt.get("format_name", "")
    info.file_size = int(fmt.get("size", 0) or 0)

    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type", "")
        if codec_type == "video" and not info.video_codec:
            info.video_codec = stream.get("codec_name", "")
            info.width = int(stream.get("width", 0) or 0)
            info.height = int(stream.get("height", 0) or 0)
            info.video_bitrate = int(stream.get("bit_rate", 0) or 0)
        elif codec_type == "audio" and not info.audio_codec:
            info.audio_codec = stream.get("codec_name", "")
            info.audio_bitrate = int(stream.get("bit_rate", 0) or 0)
            info.audio_channels = int(stream.get("channels", 0) or 0)
            info.audio_sample_rate = int(stream.get("sample_rate", 0) or 0)

    return info


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
