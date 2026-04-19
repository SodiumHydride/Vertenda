# -*- coding: utf-8 -*-
"""Quality preset that modulates encoder parameters.

Single knob exposed to the user: fast / balanced / high. Each preset gets
translated into concrete ffmpeg flags at command-construction time, so the
rest of the code only has to pass a QualityPreset enum value around.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class QualityPreset(str, Enum):
    FAST = "fast"
    BALANCED = "balanced"
    HIGH = "high"

    @property
    def display(self) -> str:
        return {
            "fast": "快速 · 体积小",
            "balanced": "均衡 · 推荐",
            "high": "高质量 · 文件较大",
        }[self.value]


@dataclass(frozen=True)
class QualitySpec:
    """Per-codec quality tuning. Empty lists mean 'use codec default'."""
    x264_preset: str         # ultrafast / fast / medium / slow
    x264_crf: str            # lower = higher quality (18..28 typical)
    x265_preset: str
    x265_crf: str
    audio_bitrate: str       # applies to lossy audio codecs
    flac_level: str          # 0..12
    # VideoToolbox does not respect CRF; use bitrate instead.
    videotoolbox_bitrate: str


_PRESETS: dict[QualityPreset, QualitySpec] = {
    QualityPreset.FAST: QualitySpec(
        x264_preset="veryfast", x264_crf="26",
        x265_preset="veryfast", x265_crf="30",
        audio_bitrate="192k", flac_level="5",
        videotoolbox_bitrate="6M",
    ),
    QualityPreset.BALANCED: QualitySpec(
        x264_preset="medium", x264_crf="23",
        x265_preset="medium", x265_crf="28",
        audio_bitrate="256k", flac_level="8",
        videotoolbox_bitrate="10M",
    ),
    QualityPreset.HIGH: QualitySpec(
        x264_preset="slow", x264_crf="19",
        x265_preset="slow", x265_crf="24",
        audio_bitrate="320k", flac_level="12",
        videotoolbox_bitrate="16M",
    ),
}


def spec_for(preset: QualityPreset) -> QualitySpec:
    return _PRESETS[preset]


def parse(name: str | None) -> QualityPreset:
    """Parse stored setting strings tolerantly; fall back to BALANCED."""
    if not name:
        return QualityPreset.BALANCED
    key = name.strip().lower()
    for preset in QualityPreset:
        if preset.value == key:
            return preset
    return QualityPreset.BALANCED
