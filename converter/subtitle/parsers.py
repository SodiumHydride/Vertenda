# -*- coding: utf-8 -*-
"""Parsers for LRC / SRT / VTT into a common cue representation."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Cue:
    start: float  # seconds
    end: float    # seconds
    text: str


# --- LRC --------------------------------------------------------------------

# [mm:ss] or [mm:ss.xx] or [mm:ss.xxx]  (centiseconds OR milliseconds)
_LRC_TIME = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:\.(\d{1,3}))?\]")


def parse_lrc(path: str) -> list[Cue]:
    """Parse an LRC file. End times are inferred from the next cue; last cue lasts 2s."""
    raw: list[tuple[float, str]] = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            stamps = _LRC_TIME.findall(line)
            if not stamps:
                continue
            text = _LRC_TIME.sub("", line).strip()
            for mm, ss, frac in stamps:
                minutes = int(mm)
                seconds = int(ss)
                fraction = 0.0
                if frac:
                    # Normalize to seconds regardless of precision (cs vs ms).
                    divisor = 10 ** len(frac)
                    fraction = int(frac) / divisor
                raw.append((minutes * 60 + seconds + fraction, text))
    raw.sort(key=lambda x: x[0])
    cues: list[Cue] = []
    for i, (start, text) in enumerate(raw):
        end = raw[i + 1][0] if i + 1 < len(raw) else start + 2.0
        cues.append(Cue(start=start, end=end, text=text))
    return cues


# --- SRT --------------------------------------------------------------------

_SRT_TIME = re.compile(r"(\d{1,2}):(\d{1,2}):(\d{1,2}),(\d{1,3})")


def _hms_to_sec(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(path: str) -> list[Cue]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if len(lines) < 2:
            continue
        # Find the line containing the timing arrow.
        time_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if time_idx is None:
            continue
        stamps = _SRT_TIME.findall(lines[time_idx])
        if len(stamps) != 2:
            continue
        start = _hms_to_sec(*stamps[0])
        end = _hms_to_sec(*stamps[1])
        text = "\n".join(lines[time_idx + 1:]).strip()
        cues.append(Cue(start=start, end=end, text=text))
    return cues


# --- VTT --------------------------------------------------------------------

_VTT_TIME = re.compile(r"(\d{1,2}):(\d{1,2}):(\d{1,2})\.(\d{1,3})")


def parse_vtt(path: str) -> list[Cue]:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read().strip()
    if content.startswith("WEBVTT"):
        # Strip the signature line (plus optional header block).
        content = content.split("\n", 1)[1] if "\n" in content else ""
    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", content.strip()):
        lines = [ln for ln in block.splitlines() if ln.strip() != ""]
        if len(lines) < 2:
            continue
        time_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if time_idx is None:
            continue
        stamps = _VTT_TIME.findall(lines[time_idx])
        if len(stamps) != 2:
            continue
        start = _hms_to_sec(*stamps[0])
        end = _hms_to_sec(*stamps[1])
        text = "\n".join(lines[time_idx + 1:]).strip()
        cues.append(Cue(start=start, end=end, text=text))
    return cues
