# -*- coding: utf-8 -*-
"""Tests for the quality preset system and its flow into ffmpeg commands."""

import pytest

from converter.ffmpeg.commands import (
    build_burn_subtitle_cmd,
    build_convert_cmd,
    build_extract_audio_cmd,
)
from converter.ffmpeg.profiles import DEFAULT_SPEC, audio_profiles, video_profiles_sw
from converter.ffmpeg.quality import QualityPreset, parse, spec_for


class TestPresetParsing:
    def test_known_presets_round_trip(self):
        for preset in QualityPreset:
            assert parse(preset.value) is preset

    @pytest.mark.parametrize("raw", [None, "", "unknown", "FaStEr"])
    def test_unknown_falls_back_to_balanced(self, raw):
        assert parse(raw) is QualityPreset.BALANCED

    def test_whitespace_tolerant(self):
        assert parse("  high ") is QualityPreset.HIGH

    def test_has_display_label(self):
        for preset in QualityPreset:
            assert preset.display  # non-empty


class TestSpecValues:
    def test_fast_is_faster_than_high(self):
        fast = spec_for(QualityPreset.FAST)
        high = spec_for(QualityPreset.HIGH)
        # Higher CRF -> less quality / faster.
        assert int(fast.x264_crf) > int(high.x264_crf)
        assert int(fast.x265_crf) > int(high.x265_crf)

    def test_high_has_highest_audio_bitrate(self):
        bitrates = {p: int(spec_for(p).audio_bitrate.rstrip("k")) for p in QualityPreset}
        assert bitrates[QualityPreset.HIGH] > bitrates[QualityPreset.BALANCED]
        assert bitrates[QualityPreset.BALANCED] >= bitrates[QualityPreset.FAST]

    def test_videotoolbox_bitrate_scales_monotonically(self):
        def mbps(spec):
            return int(spec.videotoolbox_bitrate.rstrip("M"))
        assert mbps(spec_for(QualityPreset.HIGH)) > mbps(spec_for(QualityPreset.BALANCED))


class TestSpecFlowsIntoCommands:
    def test_convert_cmd_respects_quality(self):
        fast_spec = spec_for(QualityPreset.FAST)
        high_spec = spec_for(QualityPreset.HIGH)
        fast_cmd = build_convert_cmd("in.mov", "out.mp4", spec=fast_spec)
        high_cmd = build_convert_cmd("in.mov", "out.mp4", spec=high_spec)
        assert fast_spec.x264_preset in fast_cmd
        assert fast_spec.x264_crf in fast_cmd
        assert high_spec.x264_preset in high_cmd
        assert high_spec.x264_crf in high_cmd

    def test_audio_profile_bitrate_matches_spec(self):
        spec = spec_for(QualityPreset.HIGH)
        profiles = audio_profiles(spec)
        mp3 = profiles[".mp3"].as_list()
        assert "-b:a" in mp3
        assert spec.audio_bitrate in mp3

    def test_extract_audio_uses_audio_encoder(self):
        spec = spec_for(QualityPreset.FAST)
        cmd = build_extract_audio_cmd("in.mp4", "out.mp3", spec=spec)
        assert "-vn" in cmd
        assert "libmp3lame" in cmd
        assert spec.audio_bitrate in cmd
        assert cmd[-1] == "out.mp3"

    def test_burn_cmd_threads_spec(self):
        spec = spec_for(QualityPreset.HIGH)
        cmd = build_burn_subtitle_cmd(
            video_path="v.mp4", styled_sub_path="s.ass", output_path="o.mp4",
            hardcode=True, use_hw=False,
            force_style="FontName=Arial",
            spec=spec,
        )
        # Hardcode uses libx264 -> preset/crf from spec.
        assert spec.x264_preset in cmd
        assert spec.x264_crf in cmd


class TestBackCompatTables:
    """The module-level constants still work for callers that imported them."""

    def test_audio_profiles_constant_non_empty(self):
        from converter.ffmpeg.profiles import AUDIO_PROFILES, VIDEO_PROFILES_SW
        assert AUDIO_PROFILES[".mp3"].as_list()
        assert VIDEO_PROFILES_SW[".mp4"].as_list()

    def test_default_spec_is_balanced(self):
        assert DEFAULT_SPEC is spec_for(QualityPreset.BALANCED)
