# -*- coding: utf-8 -*-
"""Human-friendly metadata for each supported format.

Lets the UI show "mp3 · 有损 · 兼容性最佳" instead of a bare "mp3",
so users don't need to already know which format to pick.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MediaKind(str, Enum):
    AUDIO = "audio"
    VIDEO = "video"
    SUBTITLE = "subtitle"


@dataclass(frozen=True)
class FormatInfo:
    key: str           # lowercase extension without dot
    label: str         # short display name, uppercase
    kind: MediaKind
    summary: str       # one-line description used as subtitle / tooltip
    lossless: bool = False
    recommended: bool = False  # marked with a star in UI


AUDIO_FORMAT_INFO: tuple[FormatInfo, ...] = (
    FormatInfo("mp3",  "MP3",  MediaKind.AUDIO, "通用有损 · 320 kbps · 兼容性最佳",   recommended=True),
    FormatInfo("flac", "FLAC", MediaKind.AUDIO, "无损压缩 · 文件较大 · 最高压缩等级", lossless=True),
    FormatInfo("wav",  "WAV",  MediaKind.AUDIO, "无损未压缩 · PCM 16-bit · 适合剪辑", lossless=True),
    FormatInfo("aac",  "AAC",  MediaKind.AUDIO, "有损 · 256 kbps · 苹果生态优先"),
    FormatInfo("opus", "OPUS", MediaKind.AUDIO, "有损 · 新一代 VBR · 同码率音质更好"),
    FormatInfo("ogg",  "OGG",  MediaKind.AUDIO, "Vorbis 有损 · 开源生态常用"),
)

VIDEO_FORMAT_INFO: tuple[FormatInfo, ...] = (
    FormatInfo("mp4",  "MP4",  MediaKind.VIDEO, "H.264 + AAC · 通用兼容 · 推荐首选",  recommended=True),
    FormatInfo("mkv",  "MKV",  MediaKind.VIDEO, "H.265 HEVC · 体积更小 · 需较新播放器"),
    FormatInfo("mov",  "MOV",  MediaKind.VIDEO, "ProRes · 剪辑友好 · 文件极大",    lossless=True),
    FormatInfo("webm", "WEBM", MediaKind.VIDEO, "VP9 · 网页流媒体 · 开源友好"),
    FormatInfo("ts",   "TS",   MediaKind.VIDEO, "MPEG-TS 流 · 直播录制常用"),
    FormatInfo("avi",  "AVI",  MediaKind.VIDEO, "MPEG-4 · 老旧容器 · 不推荐新项目"),
    FormatInfo("flv",  "FLV",  MediaKind.VIDEO, "Flash Video · 已淘汰"),
    FormatInfo("wmv",  "WMV",  MediaKind.VIDEO, "Windows Media · 老旧格式"),
    FormatInfo("rmvb", "RMVB", MediaKind.VIDEO, "RealMedia · 需安装 librmvb"),
)

SUBTITLE_FORMAT_INFO: tuple[FormatInfo, ...] = (
    FormatInfo("srt", "SRT", MediaKind.SUBTITLE, "纯文本时间轴 · 最通用 · 推荐", recommended=True),
    FormatInfo("vtt", "VTT", MediaKind.SUBTITLE, "WebVTT · HTML5 原生支持"),
    FormatInfo("ass", "ASS", MediaKind.SUBTITLE, "高级特效字幕 · 支持样式和位置"),
    FormatInfo("ssa", "SSA", MediaKind.SUBTITLE, "ASS 的早期版本"),
    FormatInfo("lrc", "LRC", MediaKind.SUBTITLE, "歌词行级时间轴 · 无结束时间"),
)


def format_display_text(info: FormatInfo) -> str:
    """Format used as the ComboBox item text."""
    star = "★ " if info.recommended else "   "
    return f"{star}{info.label}  ·  {info.summary}"


def infos_by_kind(kind: MediaKind) -> tuple[FormatInfo, ...]:
    if kind == MediaKind.AUDIO:
        return AUDIO_FORMAT_INFO
    if kind == MediaKind.VIDEO:
        return VIDEO_FORMAT_INFO
    if kind == MediaKind.SUBTITLE:
        return SUBTITLE_FORMAT_INFO
    raise ValueError(f"unknown kind: {kind}")


def find(key: str, kind: MediaKind) -> FormatInfo | None:
    key = key.lower()
    for info in infos_by_kind(kind):
        if info.key == key:
            return info
    return None
