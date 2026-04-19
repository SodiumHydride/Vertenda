# -*- coding: utf-8 -*-
"""Tests for format metadata and combo-box helpers."""

import pytest

from converter.format_meta import (
    AUDIO_FORMAT_INFO,
    SUBTITLE_FORMAT_INFO,
    VIDEO_FORMAT_INFO,
    MediaKind,
    find,
    format_display_text,
    infos_by_kind,
)


def test_every_info_has_key_label_summary():
    for info in AUDIO_FORMAT_INFO + VIDEO_FORMAT_INFO + SUBTITLE_FORMAT_INFO:
        assert info.key and info.key == info.key.lower()
        assert info.label
        assert info.summary


def test_exactly_one_recommended_per_kind():
    for kind in MediaKind:
        rec = [i for i in infos_by_kind(kind) if i.recommended]
        assert len(rec) == 1, f"{kind} should have exactly one recommended entry"


def test_display_text_contains_label_and_summary():
    info = find("mp3", MediaKind.AUDIO)
    assert info is not None
    text = format_display_text(info)
    assert "MP3" in text
    assert info.summary in text
    # The recommended marker shows up.
    assert "★" in text


def test_find_is_case_insensitive():
    assert find("MP4", MediaKind.VIDEO).key == "mp4"
    assert find("mp4", MediaKind.VIDEO).key == "mp4"


def test_find_missing_returns_none():
    assert find("nope", MediaKind.AUDIO) is None


def test_invalid_kind_raises():
    with pytest.raises(ValueError):
        infos_by_kind("not-a-kind")  # type: ignore[arg-type]


def test_keys_match_known_sets():
    """Format keys must be real extensions we actually support."""
    from converter.constants import AUDIO_FORMATS, SUBTITLE_FORMATS, VIDEO_FORMATS
    audio_keys = {i.key for i in AUDIO_FORMAT_INFO}
    video_keys = {i.key for i in VIDEO_FORMAT_INFO}
    sub_keys = {i.key for i in SUBTITLE_FORMAT_INFO}
    assert set(AUDIO_FORMATS) == audio_keys
    assert set(VIDEO_FORMATS) == video_keys
    assert set(SUBTITLE_FORMATS) == sub_keys
