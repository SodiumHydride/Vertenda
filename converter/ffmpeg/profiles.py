# -*- coding: utf-8 -*-
"""Single source of truth for ffmpeg encoder profiles.

Having two copies of the same encoder table caused silent drift in the
original codebase. Everything that needs an encoder profile must import it
from here.

Profiles are parameterized by a QualitySpec so the user's "quality preset"
choice flows through every encoder consistently (libx264 + libx265 + the
per-platform hardware encoder + audio).

Platform hardware encoder coverage
----------------------------------
- macOS: VideoToolbox (``h264_videotoolbox`` / ``hevc_videotoolbox`` /
  ``prores_videotoolbox``). Detected as always-available on Apple Silicon
  and modern Intel Macs; we just branch on ``sys.platform == "darwin"``.
- Windows: one of NVENC / Quick Sync / AMF, detected at runtime by grepping
  the output of ``ffmpeg -encoders``. Priority is
  ``nvenc > qsv > amf`` because NVENC has the best quality/speed tradeoff
  in practice. Result is cached per process; call
  :func:`reset_hw_detection_cache` to force re-detection (e.g. after the
  user swaps the bundled ffmpeg binary).
- Linux / BSD: software only for now. VAAPI/NVENC on Linux are possible but
  out of scope for this release.

IMPORTANT: this module only constructs ffmpeg argv lists. It does not
actually run ffmpeg to prove the resulting command works. A missing driver
or an unsupported GPU will still cause a runtime failure; that's caught at
the worker level, not here.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from typing import Literal

from .quality import QualityPreset, QualitySpec, spec_for


# Possible detection results for the Windows hardware encoder probe.
WindowsHwFamily = Literal["nvenc", "qsv", "amf", "none"]


@dataclass(frozen=True)
class EncoderProfile:
    args: tuple[str, ...]

    def as_list(self) -> list[str]:
        return list(self.args)


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Video — software
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Video — macOS VideoToolbox
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Video — Windows NVENC / QSV / AMF
# ---------------------------------------------------------------------------
# VP9/ProRes/RMVB don't have mainstream hardware paths, so even the hardware
# profile tables fall back to software encoders for those outputs. This
# keeps the UI promise "hardware-accelerated when possible" honest instead
# of pretending every format gets GPU speedup.

def _nvenc_args(spec: QualitySpec, codec: str) -> tuple[str, ...]:
    return (
        "-c:v", codec, "-preset", spec.nvenc_preset,
        "-rc", "vbr", "-cq", spec.nvenc_cq, "-b:v", "0",
    )


def video_profiles_hw_nvenc(spec: QualitySpec) -> dict[str, EncoderProfile]:
    h264 = _nvenc_args(spec, "h264_nvenc")
    hevc = _nvenc_args(spec, "hevc_nvenc")
    return {
        ".mp4":  EncoderProfile(h264),
        ".mkv":  EncoderProfile(hevc),
        ".mov":  EncoderProfile(("-c:v", "prores_ks", "-profile:v", "3")),
        ".avi":  EncoderProfile(h264),
        ".flv":  EncoderProfile(h264),
        ".webm": EncoderProfile(("-c:v", "libvpx-vp9",)),
        ".ts":   EncoderProfile((*h264, "-f", "mpegts")),
        ".wmv":  EncoderProfile(("-c:v", "wmv2",)),
        ".rmvb": EncoderProfile(("-c:v", "librmvb",)),
    }


def _qsv_args(spec: QualitySpec, codec: str) -> tuple[str, ...]:
    return (
        "-c:v", codec, "-preset", spec.qsv_preset,
        "-global_quality", spec.qsv_global_quality,
    )


def video_profiles_hw_qsv(spec: QualitySpec) -> dict[str, EncoderProfile]:
    h264 = _qsv_args(spec, "h264_qsv")
    hevc = _qsv_args(spec, "hevc_qsv")
    return {
        ".mp4":  EncoderProfile(h264),
        ".mkv":  EncoderProfile(hevc),
        ".mov":  EncoderProfile(("-c:v", "prores_ks", "-profile:v", "3")),
        ".avi":  EncoderProfile(h264),
        ".flv":  EncoderProfile(h264),
        ".webm": EncoderProfile(("-c:v", "libvpx-vp9",)),
        ".ts":   EncoderProfile((*h264, "-f", "mpegts")),
        ".wmv":  EncoderProfile(("-c:v", "wmv2",)),
        ".rmvb": EncoderProfile(("-c:v", "librmvb",)),
    }


def _amf_args(spec: QualitySpec, codec: str) -> tuple[str, ...]:
    return (
        "-c:v", codec, "-quality", spec.amf_quality,
        "-rc", "cqp", "-qp_i", spec.amf_qp, "-qp_p", spec.amf_qp,
    )


def video_profiles_hw_amf(spec: QualitySpec) -> dict[str, EncoderProfile]:
    h264 = _amf_args(spec, "h264_amf")
    hevc = _amf_args(spec, "hevc_amf")
    return {
        ".mp4":  EncoderProfile(h264),
        ".mkv":  EncoderProfile(hevc),
        ".mov":  EncoderProfile(("-c:v", "prores_ks", "-profile:v", "3")),
        ".avi":  EncoderProfile(h264),
        ".flv":  EncoderProfile(h264),
        ".webm": EncoderProfile(("-c:v", "libvpx-vp9",)),
        ".ts":   EncoderProfile((*h264, "-f", "mpegts")),
        ".wmv":  EncoderProfile(("-c:v", "wmv2",)),
        ".rmvb": EncoderProfile(("-c:v", "librmvb",)),
    }


# ---------------------------------------------------------------------------
# Windows hardware-encoder detection
# ---------------------------------------------------------------------------

# None means "not probed yet"; otherwise one of WindowsHwFamily.
_WINDOWS_HW_CACHE: WindowsHwFamily | None = None


def reset_hw_detection_cache() -> None:
    """Drop the cached ``ffmpeg -encoders`` result.

    Useful after :func:`converter.constants.resolve_ffmpeg_paths` re-resolves
    the ffmpeg binary (e.g. first-run installer finished), so subsequent
    profile lookups reflect the new binary's actual encoder support.
    Also used by tests to inject a controlled detection result.
    """
    global _WINDOWS_HW_CACHE
    _WINDOWS_HW_CACHE = None


def detect_windows_hw_encoder() -> WindowsHwFamily:
    """Return the best available Windows hardware encoder family.

    Priority: NVENC > Quick Sync > AMF > ``"none"``.

    The detection is a single ``ffmpeg -hide_banner -encoders`` probe,
    parsed by substring match on the encoder names. Result is memoised
    per process; call :func:`reset_hw_detection_cache` to force re-probe.

    Off-Windows platforms always return ``"none"`` without running ffmpeg,
    which keeps macOS and Linux unit tests fast and offline.

    Any subprocess or I/O error is treated as "no hardware encoder"; we
    never let a probe failure crash the caller.
    """
    global _WINDOWS_HW_CACHE
    if _WINDOWS_HW_CACHE is not None:
        return _WINDOWS_HW_CACHE
    if sys.platform != "win32":
        _WINDOWS_HW_CACHE = "none"
        return _WINDOWS_HW_CACHE

    # Deferred import to avoid a circular dependency at module load time:
    # constants.py imports from installer.py which can import profiles.py.
    from .. import constants

    try:
        cp = subprocess.run(
            [constants.FFMPEG_PATH, "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=5, text=True, check=False,
        )
        output = cp.stdout or ""
    except (OSError, subprocess.SubprocessError):
        _WINDOWS_HW_CACHE = "none"
        return _WINDOWS_HW_CACHE

    if "h264_nvenc" in output:
        _WINDOWS_HW_CACHE = "nvenc"
    elif "h264_qsv" in output:
        _WINDOWS_HW_CACHE = "qsv"
    elif "h264_amf" in output:
        _WINDOWS_HW_CACHE = "amf"
    else:
        _WINDOWS_HW_CACHE = "none"
    return _WINDOWS_HW_CACHE


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def choose_video_profiles(spec: QualitySpec, use_hw: bool) -> dict[str, EncoderProfile]:
    """Return the video encoder table for the current platform.

    ``use_hw=False`` or an unsupported platform always yields the software
    table so callers never need to second-guess the return value.
    """
    if not use_hw:
        return video_profiles_sw(spec)
    if sys.platform == "darwin":
        return video_profiles_hw_macos(spec)
    if sys.platform == "win32":
        family = detect_windows_hw_encoder()
        if family == "nvenc":
            return video_profiles_hw_nvenc(spec)
        if family == "qsv":
            return video_profiles_hw_qsv(spec)
        if family == "amf":
            return video_profiles_hw_amf(spec)
    return video_profiles_sw(spec)


def hw_accel_input_args(use_hw: bool) -> list[str]:
    """Return ``-hwaccel`` flags to place *before* ``-i`` on the ffmpeg cmd.

    macOS gets ``-hwaccel videotoolbox`` which is the decode-side half of
    VideoToolbox and plays nicely with all inputs.

    On Windows we deliberately skip ``-hwaccel``. Adding ``-hwaccel cuda``
    or ``-hwaccel qsv`` would fail hard if the user's ffmpeg lacks the
    corresponding decoder, even when the encoder half works fine. Using
    hardware only on the encode side still delivers most of the speedup
    and is strictly more robust across stock ffmpeg builds.
    """
    if not use_hw:
        return []
    if sys.platform == "darwin":
        return ["-hwaccel", "videotoolbox"]
    return []


def burn_video_encoder(spec: QualitySpec, use_hw: bool) -> list[str]:
    """Video encoder args for the subtitle-burn pipeline.

    Matches :func:`choose_video_profiles` for ``.mp4`` output so hardcoded
    subtitles run on the same GPU path as ordinary conversions.
    """
    if not use_hw:
        return ["-c:v", "libx264", "-preset", spec.x264_preset, "-crf", spec.x264_crf]
    if sys.platform == "darwin":
        return ["-c:v", "h264_videotoolbox", "-b:v", spec.videotoolbox_bitrate]
    if sys.platform == "win32":
        family = detect_windows_hw_encoder()
        if family == "nvenc":
            return list(_nvenc_args(spec, "h264_nvenc"))
        if family == "qsv":
            return list(_qsv_args(spec, "h264_qsv"))
        if family == "amf":
            return list(_amf_args(spec, "h264_amf"))
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
