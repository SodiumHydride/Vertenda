# -*- coding: utf-8 -*-
"""Tests for filter chain parameters in ffmpeg command construction."""

import pytest

from converter.ffmpeg.commands import (
    _scale_filter,
    build_convert_cmd,
    build_extract_audio_cmd,
)
from converter.ffmpeg.quality import spec_for, QualityPreset


class TestScaleFilter:
    def test_1080p(self):
        assert _scale_filter("1080p") == "scale=-2:1080"

    def test_720p(self):
        assert _scale_filter("720p") == "scale=-2:720"

    def test_480p(self):
        assert _scale_filter("480p") == "scale=-2:480"

    def test_custom_wxh(self):
        assert _scale_filter("1920x1080") == "scale=1920:1080"

    def test_numeric_only(self):
        assert _scale_filter("360") == "scale=-2:360"


class TestBuildConvertCmdFilters:
    SPEC = spec_for(QualityPreset.BALANCED)

    def test_trim_start(self):
        cmd = build_convert_cmd("in.mp4", "out.mp4", spec=self.SPEC, trim_start=10.0)
        assert "-ss" in cmd
        idx = cmd.index("-ss")
        assert cmd[idx + 1] == "10.0"

    def test_trim_end(self):
        cmd = build_convert_cmd(
            "in.mp4", "out.mp4", spec=self.SPEC,
            trim_start=5.0, trim_end=15.0,
        )
        assert "-to" in cmd
        idx = cmd.index("-to")
        assert float(cmd[idx + 1]) == 10.0  # 15 - 5

    def test_scale_preset(self):
        cmd = build_convert_cmd("in.mp4", "out.mp4", spec=self.SPEC, scale_preset="720p")
        assert "-vf" in cmd
        idx = cmd.index("-vf")
        assert "scale=" in cmd[idx + 1]

    def test_volume_normalize(self):
        cmd = build_convert_cmd("in.mp4", "out.mp4", spec=self.SPEC, volume_normalize=True)
        assert "-af" in cmd
        idx = cmd.index("-af")
        assert "loudnorm" in cmd[idx + 1]

    def test_no_filters_by_default(self):
        cmd = build_convert_cmd("in.mp4", "out.mp4", spec=self.SPEC)
        assert "-vf" not in cmd
        assert "-af" not in cmd

    def test_audio_normalize_on_audio_output(self):
        cmd = build_convert_cmd("in.wav", "out.mp3", spec=self.SPEC, volume_normalize=True)
        assert "-af" in cmd
        idx = cmd.index("-af")
        assert "loudnorm" in cmd[idx + 1]


class TestSubtitleShift:
    def test_shift_positive(self):
        from converter.subtitle.converters import shift_cues
        from converter.subtitle.parsers import Cue
        cues = [Cue(start=1.0, end=2.0, text="hi")]
        shifted = shift_cues(cues, 0.5)
        assert shifted[0].start == pytest.approx(1.5)
        assert shifted[0].end == pytest.approx(2.5)

    def test_shift_negative_clamps(self):
        from converter.subtitle.converters import shift_cues
        from converter.subtitle.parsers import Cue
        cues = [Cue(start=0.5, end=1.5, text="hi")]
        shifted = shift_cues(cues, -1.0)
        assert shifted[0].start == 0.0
        assert shifted[0].end == pytest.approx(0.5)


class TestExtractAudioFilters:
    """The 'video -> mp3' shortcut must honour trim and loudnorm."""

    SPEC = spec_for(QualityPreset.BALANCED)

    def test_trim_start_propagates(self):
        cmd = build_extract_audio_cmd(
            "in.mp4", "out.mp3", spec=self.SPEC, trim_start=10.0,
        )
        assert "-ss" in cmd
        idx = cmd.index("-ss")
        assert cmd[idx + 1] == "10.0"

    def test_trim_end_relative_to_start(self):
        cmd = build_extract_audio_cmd(
            "in.mp4", "out.mp3", spec=self.SPEC,
            trim_start=5.0, trim_end=15.0,
        )
        assert "-to" in cmd
        idx = cmd.index("-to")
        assert float(cmd[idx + 1]) == 10.0

    def test_volume_normalize_emits_af(self):
        cmd = build_extract_audio_cmd(
            "in.mp4", "out.mp3", spec=self.SPEC, volume_normalize=True,
        )
        assert "-af" in cmd
        assert "loudnorm" in cmd[cmd.index("-af") + 1]

    def test_no_y_flag(self):
        """Command builders never carry -y; conflict policy is upstream."""
        cmd = build_extract_audio_cmd("in.mp4", "out.mp3", spec=self.SPEC)
        assert "-y" not in cmd
        assert "-n" not in cmd


class TestCommandPurity:
    """Commands must not touch the filesystem at build time."""

    SPEC = spec_for(QualityPreset.BALANCED)

    def test_build_convert_no_y(self):
        cmd = build_convert_cmd(
            "/nonexistent/in.mp4", "/nonexistent/out.mkv", spec=self.SPEC,
        )
        assert "-y" not in cmd
        assert "-n" not in cmd

    def test_builds_even_when_paths_missing(self):
        """No stat/exists checks — building is a pure transformation."""
        cmd = build_convert_cmd(
            "/does/not/exist.mp4", "/also/nowhere.mp4", spec=self.SPEC,
        )
        assert cmd[-1] == "/also/nowhere.mp4"
