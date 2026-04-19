# -*- coding: utf-8 -*-
"""Pre-flight estimation: total duration, output size guess, conflict detection, disk check."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .ffmpeg.probe import get_media_duration
from .ffmpeg.quality import QualitySpec
from .fs import ConflictPolicy, disk_free_bytes, format_output_name, mirrored_output_path


@dataclass
class EstimateReport:
    files_total: int = 0
    duration_total_s: float = 0.0
    estimated_output_bytes: int = 0
    conflicts: list[tuple[str, str]] = field(default_factory=list)
    disk_free_bytes: int = 0
    disk_warn: bool = False

    @property
    def duration_display(self) -> str:
        s = int(self.duration_total_s)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        if h > 0:
            return f"{h}h {m:02d}m {s:02d}s"
        return f"{m}m {s:02d}s"

    @property
    def size_display(self) -> str:
        return _human_bytes(self.estimated_output_bytes)

    @property
    def free_display(self) -> str:
        return _human_bytes(self.disk_free_bytes)


def _human_bytes(n: int) -> str:
    if n <= 0:
        return "0 B"
    val = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{val:.1f} TB"


# ---- CRF→bitrate heuristic (rough, ±30%) ------------------------------------

_CRF_TO_MBPS = {
    "19": 8.0,
    "20": 6.5,
    "21": 5.5,
    "22": 4.5,
    "23": 4.0,
    "24": 3.2,
    "25": 2.5,
    "26": 2.0,
    "27": 1.5,
    "28": 1.2,
    "29": 1.0,
    "30": 0.8,
}


def _estimate_video_bitrate(spec: QualitySpec, use_hw: bool) -> float:
    """Return estimated video bitrate in bytes/second."""
    if use_hw:
        try:
            mbps = float(spec.videotoolbox_bitrate.rstrip("Mm"))
        except (ValueError, AttributeError):
            mbps = 10.0
        return mbps * 1_000_000 / 8

    mbps = _CRF_TO_MBPS.get(spec.x264_crf, 4.0)
    return mbps * 1_000_000 / 8


def _estimate_audio_bitrate(spec: QualitySpec) -> float:
    """Return estimated audio bitrate in bytes/second."""
    try:
        kbps = int(spec.audio_bitrate.rstrip("kK"))
    except (ValueError, AttributeError):
        kbps = 256
    return kbps * 1000 / 8


def estimate_task(
    files: list[str],
    target_format: str,
    output_dir: str,
    spec: QualitySpec,
    use_hw: bool,
    is_audio_only: bool,
    filename_template: str = "{base}",
    mirror_subdirs: bool = False,
    source_root: str = "",
) -> EstimateReport:
    """Scan files and build an EstimateReport."""
    from .constants import AUDIO_EXTS

    report = EstimateReport(files_total=len(files))
    target_ext = "." + target_format.lower()
    is_extract = target_ext in AUDIO_EXTS and not is_audio_only

    video_bps = _estimate_video_bitrate(spec, use_hw)
    audio_bps = _estimate_audio_bitrate(spec)

    for i, src in enumerate(files, start=1):
        dur = get_media_duration(src)
        if dur and dur > 0:
            report.duration_total_s += dur

            if is_extract or is_audio_only:
                file_bytes = int(dur * audio_bps)
            else:
                file_bytes = int(dur * (video_bps + audio_bps))
            report.estimated_output_bytes += file_bytes

        out_name = format_output_name(
            filename_template, src, target_format, index=i,
        )
        if mirror_subdirs and source_root:
            out_d = mirrored_output_path(src, source_root, output_dir)
        else:
            out_d = output_dir
        target_path = os.path.join(out_d, f"{out_name}.{target_format}")
        if os.path.exists(target_path):
            report.conflicts.append((src, target_path))

    if output_dir:
        report.disk_free_bytes = disk_free_bytes(output_dir)
        if report.estimated_output_bytes > report.disk_free_bytes * 0.8:
            report.disk_warn = True

    return report
