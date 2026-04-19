# -*- coding: utf-8 -*-
"""Pure functions that build ffmpeg command lists.

Contract
--------
Functions in this module are *pure* with respect to the filesystem: they do
not check whether the output exists, they do not touch temp files, they do
not apply any conflict resolution.  That responsibility belongs to the
coordinator/runnable layer.  The only thing these functions know is how to
translate a ``(source, target, QualitySpec, filter options)`` tuple into an
argv list for ``ffmpeg``.

Callers are expected to apply ``ConflictPolicy`` to the output path
*before* calling into here, which is why you will NOT see a ``-y`` flag
anywhere.  We rely on the upstream code to hand us either a path that
doesn't exist, or one the user explicitly agreed to overwrite.
"""

from __future__ import annotations

import os

from .. import constants
from ..constants import is_video_file
from .profiles import (
    DEFAULT_SPEC,
    audio_profiles,
    burn_audio_encoder,
    burn_video_encoder,
    choose_video_profiles,
    hw_accel_input_args,
    merge_audio_encoder,
)
from .quality import QualitySpec


def build_convert_cmd(
    input_path: str, output_path: str, use_hw: bool = False,
    spec: QualitySpec = DEFAULT_SPEC, *,
    trim_start: float | None = None,
    trim_end: float | None = None,
    scale_preset: str | None = None,
    volume_normalize: bool = False,
    two_pass: bool = False,
) -> list[str]:
    """Build the ffmpeg command for a single-file audio/video conversion."""
    out_ext = os.path.splitext(output_path)[1].lower()

    cmd: list[str] = [constants.FFMPEG_PATH]
    if trim_start is not None:
        cmd += ["-ss", str(trim_start)]
    cmd += [*hw_accel_input_args(use_hw), "-i", input_path]
    if trim_end is not None:
        cmd += ["-to", str(trim_end - (trim_start or 0))]

    vf_parts: list[str] = []
    af_parts: list[str] = []
    if scale_preset:
        vf_parts.append(_scale_filter(scale_preset))
    if volume_normalize:
        af_parts.append(_loudnorm_filter())

    if is_video_file(output_path):
        cmd += [
            "-c:a", "aac", "-b:a", spec.audio_bitrate,
            "-map_metadata", "-1",
            "-movflags", "+faststart",
            "-sn", "-dn",
        ]
        profiles = choose_video_profiles(spec, use_hw)
        profile = profiles.get(out_ext)
        cmd += profile.as_list() if profile is not None else ["-c:v", "copy"]
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]
        if af_parts:
            cmd += ["-af", ",".join(af_parts)]
    else:
        cmd += ["-vn", "-sn", "-dn", "-map_metadata", "-1"]
        profile = audio_profiles(spec).get(out_ext)
        cmd += profile.as_list() if profile is not None else ["-c:a", "copy"]
        if af_parts:
            cmd += ["-af", ",".join(af_parts)]

    cmd.append(output_path)
    return cmd


def build_extract_audio_cmd(
    input_path: str, output_path: str,
    spec: QualitySpec = DEFAULT_SPEC, *,
    trim_start: float | None = None,
    trim_end: float | None = None,
    volume_normalize: bool = False,
) -> list[str]:
    """Strip a video down to its audio track.

    Trim/loudnorm flow in the same way as the main converter so users who
    pick "video -> mp3" on the video tab don't silently lose those options.
    """
    out_ext = os.path.splitext(output_path)[1].lower()
    cmd: list[str] = [constants.FFMPEG_PATH]
    if trim_start is not None:
        cmd += ["-ss", str(trim_start)]
    cmd += ["-i", input_path]
    if trim_end is not None:
        cmd += ["-to", str(trim_end - (trim_start or 0))]

    cmd += ["-vn", "-sn", "-dn", "-map_metadata", "-1"]
    profile = audio_profiles(spec).get(out_ext)
    cmd += profile.as_list() if profile is not None else ["-c:a", "copy"]
    if volume_normalize:
        cmd += ["-af", _loudnorm_filter()]
    cmd.append(output_path)
    return cmd


def build_merge_av_cmd(audio_path: str, video_path: str, output_path: str,
                        use_hw: bool = False, spec: QualitySpec = DEFAULT_SPEC) -> list[str]:
    """Build a mux command that pairs audio from one file and video from another."""
    cmd: list[str] = [constants.FFMPEG_PATH, *hw_accel_input_args(use_hw)]
    cmd += ["-i", video_path, "-i", audio_path]

    if use_hw:
        cmd += burn_video_encoder(spec, use_hw=True)
    else:
        cmd += ["-c:v", "copy"]

    cmd += merge_audio_encoder(spec)
    cmd += ["-map", "0:v:0", "-map", "1:a:0", "-shortest", output_path]
    return cmd


def _scale_filter(preset: str) -> str:
    """Translate a scale preset name into an ffmpeg ``scale=`` filter value."""
    presets = {
        "1080p": "scale=-2:1080",
        "720p": "scale=-2:720",
        "480p": "scale=-2:480",
    }
    if preset in presets:
        return presets[preset]
    if "x" in preset:
        parts = preset.split("x", 1)
        return f"scale={parts[0]}:{parts[1]}"
    return f"scale=-2:{preset}"


def _loudnorm_filter() -> str:
    """EBU R128 loudness normalisation suitable for music and speech."""
    return "loudnorm=I=-16:TP=-1.5:LRA=11"


def _escape_filter_value(value: str) -> str:
    r"""Escape a value for insertion inside a filtergraph description.

    Two layers of escaping are needed when we pass filters as argv (not via
    shell). First, any character special to the *option parser* (``:`` and
    ``\``) must be escaped. Second, characters special to the *filtergraph
    parser* (``,`` ``;`` ``[`` ``]``) must also be escaped, because we are
    NOT wrapping the value in quotes (quoting introduces its own issues when
    the path can also legitimately contain apostrophes).
    """
    out = value.replace("\\", r"\\")
    out = out.replace(":", r"\:")
    out = out.replace("'", r"\'")
    out = out.replace(",", r"\,")
    out = out.replace(";", r"\;")
    out = out.replace("[", r"\[")
    out = out.replace("]", r"\]")
    return out


def _escape_subtitles_filter_path(path: str) -> str:
    """Escape a filesystem path for the ffmpeg `subtitles=` filter."""
    return _escape_filter_value(path.replace("\\", "/"))


def build_burn_subtitle_cmd(video_path: str, styled_sub_path: str, output_path: str,
                             hardcode: bool, use_hw: bool, force_style: str,
                             spec: QualitySpec = DEFAULT_SPEC) -> list[str]:
    """Build a subtitle burn-in (hardcode) or mux (softcode) command."""
    if hardcode:
        safe_path = _escape_subtitles_filter_path(styled_sub_path)
        safe_style = _escape_filter_value(force_style)
        vf = f"subtitles={safe_path}:force_style={safe_style}"
        cmd: list[str] = [
            constants.FFMPEG_PATH,
            *hw_accel_input_args(use_hw),
            "-i", video_path,
            "-vf", vf,
            *burn_video_encoder(spec, use_hw),
            *burn_audio_encoder(spec),
            output_path,
        ]
    else:
        cmd = [
            constants.FFMPEG_PATH,
            "-i", video_path,
            "-i", styled_sub_path,
            "-map", "0", "-map", "1",
            "-c", "copy",
            "-c:s", "ass",
            "-metadata:s:s:0", "language=chi",
            output_path,
        ]
    return cmd


def build_subtitle_transcode_cmd(input_path: str, output_path: str) -> list[str]:
    """Simple ffmpeg subtitle transcode (srt/vtt/ass/ssa interchange)."""
    return [constants.FFMPEG_PATH, "-i", input_path, output_path]
