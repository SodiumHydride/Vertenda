# -*- coding: utf-8 -*-
"""Tests for converter.estimator: size estimation and conflict detection."""

import os

import pytest

from converter.estimator import EstimateReport, _human_bytes, estimate_task
from converter.ffmpeg.quality import QualitySpec, spec_for, QualityPreset


class TestHumanBytes:
    def test_zero(self):
        assert _human_bytes(0) == "0 B"

    def test_bytes(self):
        assert _human_bytes(512) == "512 B"

    def test_kilobytes(self):
        assert "KB" in _human_bytes(2048)

    def test_megabytes(self):
        assert "MB" in _human_bytes(5 * 1024 * 1024)

    def test_gigabytes(self):
        assert "GB" in _human_bytes(3 * 1024 * 1024 * 1024)


class TestEstimateReport:
    def test_duration_display(self):
        r = EstimateReport(duration_total_s=3725.0)
        assert "1h" in r.duration_display
        assert "02m" in r.duration_display

    def test_size_display(self):
        r = EstimateReport(estimated_output_bytes=1024 * 1024 * 500)
        assert "MB" in r.size_display


class TestEstimateTask:
    def test_detects_conflicts(self, tmp_path):
        src = str(tmp_path / "input.mp4")
        target = str(tmp_path / "input.mp3")
        open(src, "w").close()
        open(target, "w").close()
        spec = spec_for(QualityPreset.BALANCED)
        report = estimate_task(
            files=[src],
            target_format="mp3",
            output_dir=str(tmp_path),
            spec=spec,
            use_hw=False,
            is_audio_only=True,
        )
        assert len(report.conflicts) == 1

    def test_no_conflicts_when_clean(self, tmp_path):
        src = str(tmp_path / "input.mp4")
        open(src, "w").close()
        spec = spec_for(QualityPreset.BALANCED)
        report = estimate_task(
            files=[src],
            target_format="mkv",
            output_dir=str(tmp_path),
            spec=spec,
            use_hw=False,
            is_audio_only=False,
        )
        assert len(report.conflicts) == 0

    def test_disk_free_populated(self, tmp_path):
        src = str(tmp_path / "input.mp4")
        open(src, "w").close()
        spec = spec_for(QualityPreset.BALANCED)
        report = estimate_task(
            files=[src],
            target_format="mp4",
            output_dir=str(tmp_path),
            spec=spec,
            use_hw=False,
            is_audio_only=False,
        )
        assert report.disk_free_bytes > 0
