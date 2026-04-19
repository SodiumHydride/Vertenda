# -*- coding: utf-8 -*-
"""Single source of truth for ffmpeg encoder profiles.

Having two copies of the same encoder table caused silent drift in the
original codebase. Everything that needs an encoder profile must import it
from here.

Profiles are parameterized by a QualitySpec so the user's "quality preset"
choice flows through every encoder consistently (libx264 + libx265 +
videotoolbox + audio).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from .quality import QualityPreset, QualitySpec, spec_for


@dataclass(frozen=True)
class EncoderProfile:
    args: tuple[str, ...]

    def as_list(self) -> list[str]:
        return list(self.args)


def audio_profiles(spec: QualitySpec) -> dict[str, EncoderProfile]:
    br = spec.audio_bitrate
    return {
        ".mp3":  EncoderProfile(("-c:a", "libmp3lame", "-b:a", br)),
        ".flac": EncoderProfile(("-c:a", "flac", "-compression_level", spec.flac_level)),
        ".aac":  EncoderProfile(("-c:a", "aac", "-b:a", br)),
        ".m4a":  EncoderProfile(("-c:a", "aac", "-b:a", br)),
        ".opus": EncoderProfile(("-c:a", "libopus", "-b:a", br, "-vbr", "on")),
        ".wav":  EncoderProfile(("-c:a", "pcm_s16le",)),
        ".ogg":  EncoderProfile(("-c:a", "libvorbis", "-q:a", "6")),
    }


def video_profiles_sw(spec: QualitySpec) -> dict[str, EncoderProfile]:
    return {
        ".mp4":  EncoderProfile(("-c:v", "libx264", "-preset", spec.x264_preset, "-crf", spec.x264_crf)),
        ".mkv":  EncoderProfile(("-c:v", "libx265", "-preset", spec.x265_preset, "-crf", spec.x265_crf)),
        ".mov":  EncoderProfile(("-c:v", "prores_ks", "-profile:v", "3")),
        ".avi":  EncoderProfile(("-c:v", "mpeg4", "-qscale:v", "5")),
        ".flv":  EncoderProfile(("-c:v", "flv1",)),
        ".wmv":  EncoderProfile(("-c:v", "wmv2",)),
        ".webm": EncoderProfile(("-c:v", "libvpx-vp9", "-b:v", "2M")),
        ".ts":   EncoderProfile(("-c:v", "libx264", "-preset", spec.x264_preset, "-crf", spec.x264_crf, "-f", "mpegts")),
        ".rmvb": EncoderProfile(("-c:v", "librmvb", "-qscale:v", "5")),
    }


def video_profiles_hw_macos(spec: QualitySpec) -> dict[str, EncoderProfile]:
    vb = spec.videotoolbox_bitrate
    return {
        ".mp4":  EncoderProfile(("-c:v", "h264_videotoolbox", "-b:v", vb, "-allow_sw", "1")),
        ".mov":  EncoderProfile(("-c:v", "prores_videotoolbox", "-profile:v", "3")),
        ".mkv":  EncoderProfile(("-c:v", "hevc_videotoolbox", "-b:v", vb, "-allow_sw", "1")),
        ".avi":  EncoderProfile(("-c:v", "h264_videotoolbox", "-b:v", vb)),
        ".flv":  EncoderProfile(("-c:v", "h264_videotoolbox", "-b:v", vb)),
        ".webm": EncoderProfile(("-c:v", "libvpx-vp9",)),  # no HW encoder
        ".ts":   EncoderProfile(("-c:v", "h264_videotoolbox", "-b:v", vb, "-f", "mpegts")),
        ".rmvb": EncoderProfile(("-c:v", "librmvb",)),
    }


def choose_video_profiles(spec: QualitySpec, use_hw: bool) -> dict[str, EncoderProfile]:
    if use_hw and sys.platform == "darwin":
        return video_profiles_hw_macos(spec)
    return video_profiles_sw(spec)


def hw_accel_input_args(use_hw: bool) -> list[str]:
    if use_hw and sys.platform == "darwin":
        return ["-hwaccel", "videotoolbox"]
    return []


def burn_video_encoder(spec: QualitySpec, use_hw: bool) -> list[str]:
    if use_hw and sys.platform == "darwin":
        return ["-c:v", "h264_videotoolbox", "-b:v", spec.videotoolbox_bitrate]
    return ["-c:v", "libx264", "-preset", spec.x264_preset, "-crf", spec.x264_crf]


def burn_audio_encoder(spec: QualitySpec) -> list[str]:
    return ["-c:a", "aac", "-b:a", spec.audio_bitrate]


def merge_audio_encoder(spec: QualitySpec) -> list[str]:
    return ["-c:a", "aac", "-b:a", spec.audio_bitrate]


# Default preset used when a caller forgets to thread one through.
DEFAULT_SPEC: QualitySpec = spec_for(QualityPreset.BALANCED)


# Back-compat aliases: older tests imported these as tables.
AUDIO_PROFILES: dict[str, EncoderProfile] = audio_profiles(DEFAULT_SPEC)
VIDEO_PROFILES_SW: dict[str, EncoderProfile] = video_profiles_sw(DEFAULT_SPEC)
VIDEO_PROFILES_HW_MACOS: dict[str, EncoderProfile] = video_profiles_hw_macos(DEFAULT_SPEC)
BURN_AUDIO_ENCODER: list[str] = burn_audio_encoder(DEFAULT_SPEC)
MERGE_AUDIO_ENCODER: list[str] = merge_audio_encoder(DEFAULT_SPEC)
