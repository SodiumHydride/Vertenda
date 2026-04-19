# -*- coding: utf-8 -*-
"""Subtitle timestamp formatting - pure, unit-testable helpers."""

from __future__ import annotations


def sec_to_srt(sec: float) -> str:
    """Format seconds as SRT timestamp 'HH:MM:SS,mmm'."""
    if sec < 0:
        sec = 0.0
    total_ms = round(sec * 1000)
    h, rem_ms = divmod(total_ms, 3_600_000)
    m, rem_ms = divmod(rem_ms, 60_000)
    s, ms = divmod(rem_ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def sec_to_vtt(sec: float) -> str:
    """Format seconds as VTT timestamp 'HH:MM:SS.mmm'."""
    return sec_to_srt(sec).replace(",", ".")


def sec_to_lrc(sec: float) -> str:
    """Format seconds as LRC timestamp '[MM:SS.xx]' (centiseconds)."""
    if sec < 0:
        sec = 0.0
    total_cs = round(sec * 100)
    m, rem_cs = divmod(total_cs, 6000)
    s, cs = divmod(rem_cs, 100)
    return f"[{m:02d}:{s:02d}.{cs:02d}]"
