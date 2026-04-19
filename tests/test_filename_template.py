# -*- coding: utf-8 -*-
"""Tests for converter.fs.format_output_name template engine."""

import pytest

from converter.fs import format_output_name


class TestFormatOutputName:
    def test_base_only(self):
        assert format_output_name("{base}", "/a/b/song.wav", "mp3") == "song"

    def test_base_target(self):
        assert format_output_name("{base}_{target}", "/a/video.mov", "mp4") == "video_mp4"

    def test_count(self):
        assert format_output_name("{base}_{count}", "/a/x.mp4", "mkv", index=7) == "x_7"

    def test_quality(self):
        result = format_output_name("{base}_{quality}", "/a/x.mp4", "mkv", quality_name="high")
        assert result == "x_high"

    def test_preset(self):
        result = format_output_name("{base}_{preset}", "/a/x.mp4", "mkv", preset_name="YouTube")
        assert result == "x_YouTube"

    def test_parent(self):
        result = format_output_name("{parent}_{base}", "/media/movies/clip.mp4", "mkv")
        assert result == "movies_clip"

    def test_ext(self):
        result = format_output_name("{base}_{ext}", "/a/song.flac", "mp3")
        assert result == "song_flac"

    def test_date_format(self):
        result = format_output_name("{base}_{date}", "/a/x.mp4", "mkv")
        assert len(result.split("_")[-1]) == 8  # YYYYMMDD

    def test_datetime_format(self):
        result = format_output_name("{base}_{datetime}", "/a/x.mp4", "mkv")
        assert "_" in result.split("_", 1)[1]

    def test_invalid_var_fallback(self):
        result = format_output_name("{novar}", "/a/x.mp4", "mkv")
        assert result == "x"

    def test_empty_template_fallback(self):
        result = format_output_name("", "/a/x.mp4", "mkv")
        assert result == "x"

    def test_sanitize_colon(self):
        result = format_output_name("{base}", "/a/file:name.mp4", "mkv")
        assert ":" not in result

    def test_sanitize_slash(self):
        result = format_output_name("{base}", "/a/file_name.mp4", "mkv")
        assert "/" not in result
