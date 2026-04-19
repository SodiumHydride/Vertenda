# -*- coding: utf-8 -*-
"""Tests for classifier helpers."""

from converter.constants import (
    ext_of,
    is_audio_file,
    is_lrc_file,
    is_subtitle_file,
    is_video_file,
)


def test_ext_of_lowercases():
    assert ext_of("/x/Y.MP3") == ".mp3"
    assert ext_of("no_ext") == ""


def test_audio_matrix():
    assert is_audio_file("a.mp3")
    assert is_audio_file("a.FLAC")
    assert not is_audio_file("a.mp4")


def test_video_matrix():
    assert is_video_file("a.mp4")
    assert is_video_file("a.MKV")
    assert not is_video_file("a.srt")


def test_subtitle_matrix():
    assert is_subtitle_file("a.srt")
    assert is_subtitle_file("a.LRC")
    assert not is_subtitle_file("a.mp3")


def test_lrc():
    assert is_lrc_file("a.lrc")
    assert not is_lrc_file("a.srt")
