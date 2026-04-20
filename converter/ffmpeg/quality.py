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

    # ---- Windows hardware encoders ----------------------------------------
    # NVIDIA NVENC: preset p1 (fastest) .. p7 (slowest).  -rc vbr -cq acts as
    # a CRF-like knob (0..51, lower = higher quality).  Matches libx264 CRF
    # numerics so the same preset feels similar across encoders.
    nvenc_preset: str        # p2 / p4 / p6
    nvenc_cq: str            # 26 / 23 / 19

    # Intel Quick Sync: preset veryfast..veryslow.  -global_quality uses ICQ
    # scale (1..51) which is also numerically close to libx264 CRF.
    qsv_preset: str
    qsv_global_quality: str  # 26 / 23 / 19

    # AMD AMF: quality speed / balanced / quality.  -rc cqp plus -qp_i/-qp_p
    # keyframe and P-frame quantizer; same 0..51 scale.
    amf_quality: str         # speed / balanced / quality
    amf_qp: str              # 26 / 23 / 19


_PRESETS: dict[QualityPreset, QualitySpec] = {
    QualityPreset.FAST: QualitySpec(
        x264_preset="veryfast", x264_crf="26",
        x265_preset="veryfast", x265_crf="30",
        audio_bitrate="192k", flac_level="5",
        videotoolbox_bitrate="6M",
        nvenc_preset="p2", nvenc_cq="26",
        qsv_preset="veryfast", qsv_global_quality="26",
        amf_quality="speed", amf_qp="26",
    ),
    QualityPreset.BALANCED: QualitySpec(
        x264_preset="medium", x264_crf="23",
        x265_preset="medium", x265_crf="28",
        audio_bitrate="256k", flac_level="8",
        videotoolbox_bitrate="10M",
        nvenc_preset="p4", nvenc_cq="23",
        qsv_preset="medium", qsv_global_quality="23",
        amf_quality="balanced", amf_qp="23",
    ),
    QualityPreset.HIGH: QualitySpec(
        x264_preset="slow", x264_crf="19",
        x265_preset="slow", x265_crf="24",
        audio_bitrate="320k", flac_level="12",
        videotoolbox_bitrate="16M",
        nvenc_preset="p6", nvenc_cq="19",
        qsv_preset="slow", qsv_global_quality="19",
        amf_quality="quality", amf_qp="19",
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
