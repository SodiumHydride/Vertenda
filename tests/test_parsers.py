# -*- coding: utf-8 -*-
"""Subtitle parser round-trip tests."""

import os

import pytest

from converter.subtitle.converters import (
    SubtitleConversionError,
    lrc_to_srt,
    lrc_to_vtt,
    srt_to_lrc,
    vtt_to_lrc,
)
from converter.subtitle.parsers import parse_lrc, parse_srt, parse_vtt


SAMPLE_LRC = """[00:00.00]Hello world
[00:02.50]Second line
[00:05.00]Third line
"""

SAMPLE_SRT = """1
00:00:00,000 --> 00:00:02,000
Hello world

2
00:00:02,500 --> 00:00:05,000
Second line

3
00:00:05,000 --> 00:00:07,000
Third line
"""

SAMPLE_VTT = """WEBVTT

00:00:00.000 --> 00:00:02.000
Hello world

00:00:02.500 --> 00:00:05.000
Second line
"""


class TestLrcParser:
    def test_basic(self, tmp_path):
        p = tmp_path / "a.lrc"
        p.write_text(SAMPLE_LRC, encoding="utf-8")
        cues = parse_lrc(str(p))
        assert [c.text for c in cues] == ["Hello world", "Second line", "Third line"]
        assert cues[0].start == 0.0
        assert cues[1].start == 2.5
        assert cues[2].start == 5.0

    def test_end_inferred_from_next(self, tmp_path):
        p = tmp_path / "a.lrc"
        p.write_text(SAMPLE_LRC, encoding="utf-8")
        cues = parse_lrc(str(p))
        assert cues[0].end == pytest.approx(2.5)
        assert cues[1].end == pytest.approx(5.0)
        # Last cue gets +2s default.
        assert cues[-1].end == pytest.approx(7.0)

    def test_millisecond_precision(self, tmp_path):
        p = tmp_path / "a.lrc"
        p.write_text("[00:00.123]Line\n", encoding="utf-8")
        cues = parse_lrc(str(p))
        assert cues[0].start == pytest.approx(0.123)

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.lrc"
        p.write_text("", encoding="utf-8")
        assert parse_lrc(str(p)) == []


class TestSrtParser:
    def test_basic(self, tmp_path):
        p = tmp_path / "a.srt"
        p.write_text(SAMPLE_SRT, encoding="utf-8")
        cues = parse_srt(str(p))
        assert len(cues) == 3
        assert cues[0].start == 0.0
        assert cues[0].end == 2.0
        assert cues[0].text == "Hello world"

    def test_crlf_line_endings(self, tmp_path):
        p = tmp_path / "a.srt"
        p.write_text(SAMPLE_SRT.replace("\n", "\r\n"), encoding="utf-8")
        cues = parse_srt(str(p))
        assert len(cues) == 3


class TestVttParser:
    def test_basic(self, tmp_path):
        p = tmp_path / "a.vtt"
        p.write_text(SAMPLE_VTT, encoding="utf-8")
        cues = parse_vtt(str(p))
        assert len(cues) == 2
        assert cues[0].text == "Hello world"
        assert cues[1].start == pytest.approx(2.5)


class TestConverters:
    def test_srt_to_lrc_round_trip(self, tmp_path):
        srt_path = tmp_path / "a.srt"
        srt_path.write_text(SAMPLE_SRT, encoding="utf-8")
        lrc_path = tmp_path / "a.lrc"
        srt_to_lrc(str(srt_path), str(lrc_path))
        content = lrc_path.read_text(encoding="utf-8")
        assert "[00:00.00]Hello world" in content
        assert "[00:02.50]Second line" in content

    def test_lrc_to_srt(self, tmp_path):
        src = tmp_path / "a.lrc"
        src.write_text(SAMPLE_LRC, encoding="utf-8")
        dst = tmp_path / "a.srt"
        lrc_to_srt(str(src), str(dst))
        text = dst.read_text(encoding="utf-8")
        assert "00:00:00,000 --> 00:00:02,500" in text
        assert "Hello world" in text

    def test_vtt_to_lrc(self, tmp_path):
        src = tmp_path / "a.vtt"
        src.write_text(SAMPLE_VTT, encoding="utf-8")
        dst = tmp_path / "a.lrc"
        vtt_to_lrc(str(src), str(dst))
        content = dst.read_text(encoding="utf-8")
        assert "Hello world" in content

    def test_lrc_to_vtt(self, tmp_path):
        src = tmp_path / "a.lrc"
        src.write_text(SAMPLE_LRC, encoding="utf-8")
        dst = tmp_path / "a.vtt"
        lrc_to_vtt(str(src), str(dst))
        content = dst.read_text(encoding="utf-8")
        assert content.startswith("WEBVTT")
        assert "00:00:00.000 --> 00:00:02.500" in content

    def test_empty_input_raises(self, tmp_path):
        src = tmp_path / "empty.lrc"
        src.write_text("", encoding="utf-8")
        with pytest.raises(SubtitleConversionError):
            lrc_to_srt(str(src), str(tmp_path / "out.srt"))
