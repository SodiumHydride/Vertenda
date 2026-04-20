# -*- coding: utf-8 -*-
"""Tests for ffmpeg command string construction."""

import sys

import pytest

from converter.ffmpeg.commands import (
    _escape_subtitles_filter_path,
    build_burn_subtitle_cmd,
    build_convert_cmd,
    build_merge_av_cmd,
    build_subtitle_transcode_cmd,
)


class TestConvertCmd:
    def test_mp3_audio_encoder(self):
        cmd = build_convert_cmd("in.wav", "out.mp3")
        assert "libmp3lame" in cmd
        assert "-vn" in cmd  # audio output should disable video stream

    def test_flac_compression(self):
        cmd = build_convert_cmd("in.wav", "out.flac")
        assert "flac" in cmd
        assert "-compression_level" in cmd

    def test_video_output_has_faststart(self):
        cmd = build_convert_cmd("in.mov", "out.mp4")
        assert "-movflags" in cmd
        assert "+faststart" in cmd
        assert "libx264" in cmd  # software default

    def test_hw_accel_mac_video(self):
        # We can't truly test darwin on CI, but the function branches solely on
        # sys.platform; monkey-patch that.
        cmd = build_convert_cmd("in.mov", "out.mp4", use_hw=True)
        if sys.platform == "darwin":
            assert "h264_videotoolbox" in cmd
            assert "-hwaccel" in cmd
        else:
            assert "libx264" in cmd

    def test_unknown_format_falls_back_to_copy_audio(self):
        cmd = build_convert_cmd("in.wav", "out.weirdext")
        assert "copy" in cmd

    def test_input_path_is_after_i_flag(self):
        cmd = build_convert_cmd("/tmp/in put.mov", "/tmp/out.mp4")
        i_index = cmd.index("-i")
        assert cmd[i_index + 1] == "/tmp/in put.mov"


class TestMergeCmd:
    def test_orders_inputs(self):
        cmd = build_merge_av_cmd("audio.mp3", "video.mp4", "out.mp4")
        # video must be first input (0), audio second (1)
        i_indices = [i for i, tok in enumerate(cmd) if tok == "-i"]
        assert cmd[i_indices[0] + 1] == "video.mp4"
        assert cmd[i_indices[1] + 1] == "audio.mp3"
        assert "-shortest" in cmd
        # Software path copies video to save time.
        assert "copy" in cmd

    def test_hw_encode_when_requested_on_mac(self):
        cmd = build_merge_av_cmd("audio.mp3", "video.mp4", "out.mp4", use_hw=True)
        if sys.platform == "darwin":
            assert "h264_videotoolbox" in cmd


class TestWindowsHwAccel:
    """Windows hardware encoder paths.

    We can't run these on real Windows in CI on macOS, so the strategy is:
    fake ``sys.platform`` plus inject the detection cache directly. This
    proves the command builder picks the right encoder for each GPU family
    without ever shelling out to ffmpeg.
    """

    @staticmethod
    def _fake_windows(monkeypatch, family: str) -> None:
        from converter.ffmpeg import profiles
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(profiles, "_WINDOWS_HW_CACHE", family)

    def test_nvenc_mp4_uses_h264_nvenc(self, monkeypatch):
        self._fake_windows(monkeypatch, "nvenc")
        cmd = build_convert_cmd("in.mov", "out.mp4", use_hw=True)
        assert "h264_nvenc" in cmd
        assert "-cq" in cmd
        assert "libx264" not in cmd

    def test_nvenc_mkv_uses_hevc_nvenc(self, monkeypatch):
        self._fake_windows(monkeypatch, "nvenc")
        cmd = build_convert_cmd("in.mov", "out.mkv", use_hw=True)
        assert "hevc_nvenc" in cmd

    def test_qsv_mp4_uses_h264_qsv(self, monkeypatch):
        self._fake_windows(monkeypatch, "qsv")
        cmd = build_convert_cmd("in.mov", "out.mp4", use_hw=True)
        assert "h264_qsv" in cmd
        assert "-global_quality" in cmd

    def test_amf_mp4_uses_h264_amf(self, monkeypatch):
        self._fake_windows(monkeypatch, "amf")
        cmd = build_convert_cmd("in.mov", "out.mp4", use_hw=True)
        assert "h264_amf" in cmd
        assert "-quality" in cmd

    def test_falls_back_to_software_when_no_hw(self, monkeypatch):
        self._fake_windows(monkeypatch, "none")
        cmd = build_convert_cmd("in.mov", "out.mp4", use_hw=True)
        assert "libx264" in cmd
        assert "h264_nvenc" not in cmd

    def test_no_hwaccel_input_flag_on_windows(self, monkeypatch):
        """Deliberate: we never pass -hwaccel on Windows to avoid hard
        failures when the decoder counterpart isn't present."""
        self._fake_windows(monkeypatch, "nvenc")
        cmd = build_convert_cmd("in.mov", "out.mp4", use_hw=True)
        assert "-hwaccel" not in cmd

    def test_use_hw_false_stays_software_even_with_detected_gpu(self, monkeypatch):
        self._fake_windows(monkeypatch, "nvenc")
        cmd = build_convert_cmd("in.mov", "out.mp4", use_hw=False)
        assert "libx264" in cmd
        assert "nvenc" not in " ".join(cmd)

    def test_burn_nvenc(self, monkeypatch):
        self._fake_windows(monkeypatch, "nvenc")
        cmd = build_burn_subtitle_cmd(
            video_path="v.mp4", styled_sub_path="s.ass", output_path="o.mp4",
            hardcode=True, use_hw=True, force_style="FontName=Arial",
        )
        assert "h264_nvenc" in cmd

    def test_burn_qsv(self, monkeypatch):
        self._fake_windows(monkeypatch, "qsv")
        cmd = build_burn_subtitle_cmd(
            video_path="v.mp4", styled_sub_path="s.ass", output_path="o.mp4",
            hardcode=True, use_hw=True, force_style="FontName=Arial",
        )
        assert "h264_qsv" in cmd

    def test_burn_amf(self, monkeypatch):
        self._fake_windows(monkeypatch, "amf")
        cmd = build_burn_subtitle_cmd(
            video_path="v.mp4", styled_sub_path="s.ass", output_path="o.mp4",
            hardcode=True, use_hw=True, force_style="FontName=Arial",
        )
        assert "h264_amf" in cmd

    def test_merge_nvenc(self, monkeypatch):
        self._fake_windows(monkeypatch, "nvenc")
        cmd = build_merge_av_cmd("a.mp3", "v.mp4", "o.mp4", use_hw=True)
        assert "h264_nvenc" in cmd


class TestHwDetectionCache:
    def test_non_windows_returns_none_without_probing(self, monkeypatch):
        """On macOS/Linux we should never even call subprocess."""
        from converter.ffmpeg import profiles
        monkeypatch.setattr(sys, "platform", "darwin")
        profiles.reset_hw_detection_cache()
        # Blow up if anything tries to run subprocess.
        def _forbidden(*_args, **_kwargs):
            raise AssertionError("subprocess.run must not be called off-Windows")
        monkeypatch.setattr(profiles.subprocess, "run", _forbidden)
        assert profiles.detect_windows_hw_encoder() == "none"

    def test_cache_memoises_result(self, monkeypatch):
        from converter.ffmpeg import profiles
        monkeypatch.setattr(sys, "platform", "win32")
        profiles.reset_hw_detection_cache()
        call_count = {"n": 0}

        class _FakeCompleted:
            stdout = "Encoders:\n ... h264_nvenc\n ... h264_qsv\n"

        def _fake_run(*_args, **_kwargs):
            call_count["n"] += 1
            return _FakeCompleted()
        monkeypatch.setattr(profiles.subprocess, "run", _fake_run)

        assert profiles.detect_windows_hw_encoder() == "nvenc"
        assert profiles.detect_windows_hw_encoder() == "nvenc"
        assert call_count["n"] == 1

    def test_subprocess_error_is_swallowed(self, monkeypatch):
        from converter.ffmpeg import profiles
        monkeypatch.setattr(sys, "platform", "win32")
        profiles.reset_hw_detection_cache()

        def _broken(*_args, **_kwargs):
            raise OSError("ffmpeg not found")
        monkeypatch.setattr(profiles.subprocess, "run", _broken)

        assert profiles.detect_windows_hw_encoder() == "none"

    def test_priority_nvenc_over_qsv_over_amf(self, monkeypatch):
        from converter.ffmpeg import profiles
        monkeypatch.setattr(sys, "platform", "win32")

        def _result_with(encoders: str):
            class _Cp:
                stdout = encoders
            return lambda *_a, **_kw: _Cp()

        profiles.reset_hw_detection_cache()
        monkeypatch.setattr(
            profiles.subprocess, "run",
            _result_with("h264_nvenc h264_qsv h264_amf"),
        )
        assert profiles.detect_windows_hw_encoder() == "nvenc"

        profiles.reset_hw_detection_cache()
        monkeypatch.setattr(
            profiles.subprocess, "run",
            _result_with("h264_qsv h264_amf"),
        )
        assert profiles.detect_windows_hw_encoder() == "qsv"

        profiles.reset_hw_detection_cache()
        monkeypatch.setattr(
            profiles.subprocess, "run",
            _result_with("h264_amf only"),
        )
        assert profiles.detect_windows_hw_encoder() == "amf"

        profiles.reset_hw_detection_cache()
        monkeypatch.setattr(
            profiles.subprocess, "run",
            _result_with("just libx264 here"),
        )
        assert profiles.detect_windows_hw_encoder() == "none"


class TestBurnCmd:
    def test_hardcode_uses_vf_subtitles(self):
        cmd = build_burn_subtitle_cmd(
            video_path="v.mp4", styled_sub_path="s.ass", output_path="o.mp4",
            hardcode=True, use_hw=False, force_style="FontName=Arial",
        )
        vf_idx = cmd.index("-vf")
        vf_arg = cmd[vf_idx + 1]
        assert vf_arg.startswith("subtitles=")
        assert "force_style" in vf_arg
        # No trailing comma left over from the old buggy implementation.
        assert not vf_arg.endswith(",")
        assert "libx264" in cmd

    def test_softcode_copies_streams(self):
        cmd = build_burn_subtitle_cmd(
            video_path="v.mp4", styled_sub_path="s.ass", output_path="o.mkv",
            hardcode=False, use_hw=False, force_style="",
        )
        assert "-vf" not in cmd  # no video filter in softmux
        assert "copy" in cmd
        # Subtitle codec must be set for style preservation.
        c_s_idx = cmd.index("-c:s")
        assert cmd[c_s_idx + 1] == "ass"

    def test_hw_accel_hardcode_on_mac(self):
        cmd = build_burn_subtitle_cmd(
            video_path="v.mp4", styled_sub_path="s.ass", output_path="o.mp4",
            hardcode=True, use_hw=True, force_style="FontName=Arial",
        )
        if sys.platform == "darwin":
            assert "h264_videotoolbox" in cmd


class TestEscape:
    def test_escapes_colon(self):
        # Windows-ish path with colon.
        result = _escape_subtitles_filter_path("C:/tmp/x.ass")
        assert ":" not in result.replace(r"\:", "")  # all colons escaped

    def test_escapes_apostrophe(self):
        result = _escape_subtitles_filter_path("/tmp/it's.ass")
        assert "\\'" in result  # apostrophe escaped

    def test_escapes_comma(self):
        from converter.ffmpeg.commands import _escape_filter_value
        # Style strings contain commas; they must be escaped or ffmpeg
        # treats them as filter-chain separators.
        result = _escape_filter_value("FontName=Arial,Bold=1")
        assert r"\," in result
        assert "," not in result.replace(r"\,", "")

    def test_force_style_in_vf_is_comma_escaped(self):
        """Regression: the original `-vf subtitles=...:force_style=X,Y` broke
        ffmpeg because the commas were filter-chain separators.
        """
        cmd = build_burn_subtitle_cmd(
            video_path="v.mp4", styled_sub_path="/tmp/s.ass", output_path="o.mp4",
            hardcode=True, use_hw=False,
            force_style="FontName=Arial,PrimaryColour=&HFF00FF",
        )
        vf_arg = cmd[cmd.index("-vf") + 1]
        # Style commas must appear escaped so they stay part of force_style.
        assert r"PrimaryColour" in vf_arg
        assert r"\," in vf_arg


class TestSubtitleTranscodeCmd:
    def test_simple(self):
        cmd = build_subtitle_transcode_cmd("a.srt", "b.vtt")
        assert "-i" in cmd
        assert cmd[-1] == "b.vtt"
