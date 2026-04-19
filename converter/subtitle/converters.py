# -*- coding: utf-8 -*-
"""Cross-format subtitle converters. All operate on our Cue representation."""

from __future__ import annotations

from .parsers import Cue, parse_lrc, parse_srt, parse_vtt
from .timestamps import sec_to_lrc, sec_to_srt, sec_to_vtt


class SubtitleConversionError(RuntimeError):
    """Raised when a subtitle file cannot be parsed or produces no cues."""


def _require_cues(cues: list[Cue], source: str) -> None:
    if not cues:
        raise SubtitleConversionError(f"未解析到任何字幕数据: {source}")


def write_srt(cues: list[Cue], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for i, cue in enumerate(cues, start=1):
            f.write(f"{i}\n")
            f.write(f"{sec_to_srt(cue.start)} --> {sec_to_srt(cue.end)}\n")
            f.write(f"{cue.text}\n\n")


def write_vtt(cues: list[Cue], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write("WEBVTT\n\n")
        for cue in cues:
            f.write(f"{sec_to_vtt(cue.start)} --> {sec_to_vtt(cue.end)}\n")
            f.write(f"{cue.text}\n\n")


def write_lrc(cues: list[Cue], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for cue in cues:
            single = cue.text.replace("\n", " ")
            f.write(f"{sec_to_lrc(cue.start)}{single}\n")


def lrc_to_srt(src: str, dst: str) -> None:
    cues = parse_lrc(src)
    _require_cues(cues, src)
    write_srt(cues, dst)


def lrc_to_vtt(src: str, dst: str) -> None:
    cues = parse_lrc(src)
    _require_cues(cues, src)
    write_vtt(cues, dst)


def srt_to_lrc(src: str, dst: str) -> None:
    cues = parse_srt(src)
    _require_cues(cues, src)
    write_lrc(cues, dst)


def vtt_to_lrc(src: str, dst: str) -> None:
    cues = parse_vtt(src)
    _require_cues(cues, src)
    write_lrc(cues, dst)
