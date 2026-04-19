# -*- coding: utf-8 -*-
"""End-to-end ffmpeg smoke tests.

Skipped automatically if ffmpeg is not available, so CI without binaries
still passes. On the dev machine, these prove the full pipeline actually
runs: command construction -> runner -> output file exists.
"""

import os
import subprocess
from pathlib import Path

import pytest

from converter.constants import FFMPEG_PATH
from converter.ffmpeg.commands import build_convert_cmd, build_subtitle_transcode_cmd
from converter.ffmpeg.probe import check_ffmpeg_available, get_media_duration
from converter.ffmpeg.runner import CancelToken, run_blocking, run_with_progress
from converter.subtitle.styling import inject_burn_style


pytestmark = pytest.mark.skipif(
    not check_ffmpeg_available(), reason="ffmpeg not available on this machine"
)


@pytest.fixture
def sample_wav(tmp_path: Path) -> Path:
    """Generate a 1-second 440 Hz sine WAV via ffmpeg itself."""
    out = tmp_path / "sine.wav"
    cmd = [
        FFMPEG_PATH, "-y",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
        "-ac", "1", "-ar", "16000",
        str(out),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert out.exists()
    return out


@pytest.fixture
def sample_mp4(tmp_path: Path) -> Path:
    """Generate a 2-second silent test video via ffmpeg."""
    out = tmp_path / "test.mp4"
    cmd = [
        FFMPEG_PATH, "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=2",
        "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
        "-t", "2",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac",
        "-pix_fmt", "yuv420p",
        str(out),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    assert out.exists()
    return out


class TestRealConversion:
    def test_wav_to_mp3(self, tmp_path, sample_wav):
        out = tmp_path / "out.mp3"
        cmd = build_convert_cmd(str(sample_wav), str(out))
        result = run_blocking(cmd)
        assert result.ok, result.stderr_tail
        assert out.exists() and out.stat().st_size > 0

    def test_wav_to_flac(self, tmp_path, sample_wav):
        out = tmp_path / "out.flac"
        result = run_blocking(build_convert_cmd(str(sample_wav), str(out)))
        assert result.ok, result.stderr_tail
        assert out.exists()

    def test_mp4_to_mkv_with_progress(self, tmp_path, sample_mp4):
        out = tmp_path / "out.mkv"
        cmd = build_convert_cmd(str(sample_mp4), str(out))
        progress_hits: list[int] = []
        time_hits: list[str] = []
        log_hits: list[str] = []

        duration = get_media_duration(str(sample_mp4)) or 2.0
        result = run_with_progress(
            cmd, duration,
            on_progress=progress_hits.append,
            on_time=time_hits.append,
            on_log=log_hits.append,
            cancel=CancelToken(),
        )
        assert result.ok, result.stderr_tail
        assert out.exists()
        assert len(progress_hits) > 0  # at least one progress update
        assert any("time=" in line for line in log_hits)


class TestProbe:
    def test_duration_of_known_sample(self, sample_wav):
        d = get_media_duration(str(sample_wav))
        assert d is not None
        assert 0.9 < d < 1.1

    def test_missing_file_returns_none(self, tmp_path):
        assert get_media_duration(str(tmp_path / "nope.mp4")) is None


class TestStylingTempFile:
    def test_ass_source_is_not_modified(self, tmp_path):
        """Critical invariant: the user's .ass file must never be touched."""
        src = tmp_path / "user.ass"
        original = "[Script Info]\nTitle: test\n"
        src.write_text(original, encoding="utf-8")
        original_mtime = src.stat().st_mtime_ns

        with inject_burn_style(str(src)) as styled:
            assert styled.path != str(src)
            assert os.path.exists(styled.path)

        # Source file still untouched.
        assert src.read_text(encoding="utf-8") == original
        assert src.stat().st_mtime_ns == original_mtime
        # Temp file cleaned up on exit.
        assert not os.path.exists(styled.path)

    def test_cleanup_survives_exception(self, tmp_path):
        src = tmp_path / "user.ass"
        src.write_text("[V4+ Styles]\nFormat: Name\n", encoding="utf-8")

        temp_path_saved = None
        try:
            with inject_burn_style(str(src)) as styled:
                temp_path_saved = styled.path
                assert os.path.exists(temp_path_saved)
                raise RuntimeError("simulated ffmpeg failure")
        except RuntimeError:
            pass

        assert temp_path_saved is not None
        assert not os.path.exists(temp_path_saved)


class TestCancellation:
    def test_cancel_terminates_live_process(self, tmp_path):
        """Running cancel() during a real ffmpeg run must actually kill it.

        We synthesize a long-running job directly (no dependency on samples)
        so the test has predictable runtime.
        """
        import threading
        import time

        out = tmp_path / "out_long.mp4"
        # Generate 60s of video at slow preset: guarantees >5s processing time.
        cmd = [
            FFMPEG_PATH, "-y",
            "-f", "lavfi", "-i", "testsrc=size=640x480:rate=30:duration=60",
            "-c:v", "libx264", "-preset", "veryslow", "-crf", "10",
            str(out),
        ]
        cancel = CancelToken()
        results: dict = {}

        def run():
            results["result"] = run_with_progress(
                cmd, 60.0,
                on_progress=lambda p: None,
                on_time=lambda t: None,
                on_log=lambda l: None,
                cancel=cancel,
            )

        t = threading.Thread(target=run)
        start = time.monotonic()
        t.start()
        time.sleep(1.5)  # Give ffmpeg clearly enough time to start encoding.
        cancel.cancel()
        t.join(timeout=10)
        elapsed = time.monotonic() - start

        assert not t.is_alive(), "ffmpeg did not terminate after cancel"
        # Must have returned fast (well under the 60s it would take naturally).
        assert elapsed < 10.0, f"cancel took {elapsed:.1f}s, ffmpeg was not killed promptly"
        # When the child exits non-zero, we report ok=False; that's the success case.
        assert results["result"].cancelled or not results["result"].ok
