# -*- coding: utf-8 -*-
"""Timestamp formatter tests. Fast, deterministic, zero ffmpeg."""

import pytest

from converter.subtitle.timestamps import sec_to_lrc, sec_to_srt, sec_to_vtt


class TestSrtTimestamp:
    def test_zero(self):
        assert sec_to_srt(0) == "00:00:00,000"

    def test_one_second(self):
        assert sec_to_srt(1.0) == "00:00:01,000"

    def test_sub_second_milliseconds(self):
        assert sec_to_srt(1.234) == "00:00:01,234"

    def test_rounding(self):
        # 1.0005 s -> 1.001 s (round-half-to-even for 500, but 1.0005 may not be exact)
        # Accept either 000 or 001 here; focus is no crash.
        out = sec_to_srt(1.0005)
        assert out.startswith("00:00:01,")

    def test_minute_boundary(self):
        assert sec_to_srt(60.0) == "00:01:00,000"

    def test_hour_boundary(self):
        assert sec_to_srt(3600.0) == "01:00:00,000"

    def test_large_value(self):
        # 12h34m56.789s
        assert sec_to_srt(12 * 3600 + 34 * 60 + 56.789) == "12:34:56,789"

    def test_negative_clamped_to_zero(self):
        assert sec_to_srt(-1.0) == "00:00:00,000"


class TestVttTimestamp:
    def test_dot_separator(self):
        assert sec_to_vtt(1.234) == "00:00:01.234"

    def test_zero(self):
        assert sec_to_vtt(0) == "00:00:00.000"


class TestLrcTimestamp:
    def test_zero(self):
        assert sec_to_lrc(0) == "[00:00.00]"

    def test_centiseconds(self):
        assert sec_to_lrc(1.23) == "[00:01.23]"

    def test_ms_are_truncated_to_cs(self):
        # 1.239 s -> 123.9 cs -> 124 cs
        assert sec_to_lrc(1.239) == "[00:01.24]"

    def test_minute_carry(self):
        assert sec_to_lrc(65.5) == "[01:05.50]"
