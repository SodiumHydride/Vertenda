# -*- coding: utf-8 -*-
"""Tests for converter.fs: ConflictPolicy resolution and filename templates."""

import os
import tempfile
import threading

import pytest

from converter.fs import (
    ConflictPolicy,
    format_output_name,
    mirrored_output_path,
    reserve_output_path,
    resolve_output_path,
)


class TestResolveOutputPath:
    def test_no_conflict(self, tmp_path):
        target = str(tmp_path / "output.mp4")
        path, action = resolve_output_path(target, ConflictPolicy.OVERWRITE)
        assert path == target
        assert action == "go"

    def test_skip_existing(self, tmp_path):
        target = str(tmp_path / "output.mp4")
        open(target, "w").close()
        path, action = resolve_output_path(target, ConflictPolicy.SKIP)
        assert action == "skip"

    def test_overwrite_existing(self, tmp_path):
        target = str(tmp_path / "output.mp4")
        open(target, "w").close()
        path, action = resolve_output_path(target, ConflictPolicy.OVERWRITE)
        assert path == target
        assert action == "go"

    def test_rename_existing(self, tmp_path):
        target = str(tmp_path / "output.mp4")
        open(target, "w").close()
        path, action = resolve_output_path(target, ConflictPolicy.RENAME)
        assert action == "go"
        assert path != target
        assert "_1" in path

    def test_rename_multiple(self, tmp_path):
        target = str(tmp_path / "output.mp4")
        open(target, "w").close()
        open(str(tmp_path / "output_1.mp4"), "w").close()
        path, action = resolve_output_path(target, ConflictPolicy.RENAME)
        assert "_2" in path

    def test_ask_falls_back_to_rename(self, tmp_path):
        target = str(tmp_path / "output.mp4")
        open(target, "w").close()
        path, action = resolve_output_path(target, ConflictPolicy.ASK)
        assert action == "go"
        assert "_1" in path


class TestFormatOutputName:
    def test_default_base(self):
        result = format_output_name("{base}", "/path/to/video.mp4", "mkv")
        assert result == "video"

    def test_with_target(self):
        result = format_output_name("{base}_{target}", "/path/song.wav", "mp3")
        assert result == "song_mp3"

    def test_with_count(self):
        result = format_output_name("{base}_{count}", "/a/b.mp4", "mkv", index=5)
        assert result == "b_5"

    def test_with_quality(self):
        result = format_output_name(
            "{base}_{quality}", "/a/b.mp4", "mkv", quality_name="high"
        )
        assert result == "b_high"

    def test_invalid_template_fallback(self):
        result = format_output_name("{nonexistent}", "/a/b.mp4", "mkv")
        assert result == "b"

    def test_sanitize_unsafe_chars(self):
        result = format_output_name("{base}", "/a/file:name.mp4", "mkv")
        assert ":" not in result


class TestMirroredOutputPath:
    def test_flat_case(self):
        result = mirrored_output_path("/src/a.mp4", "/src", "/out")
        assert result == "/out"

    def test_nested_case(self):
        result = mirrored_output_path("/src/sub/deep/a.mp4", "/src", "/out")
        assert result == os.path.join("/out", "sub", "deep")


class TestReserveOutputPath:
    """Atomic concurrent-safe path reservation."""

    def test_first_caller_gets_target(self, tmp_path):
        target = str(tmp_path / "out.mp4")
        reserved: set[str] = set()
        path, action = reserve_output_path(target, ConflictPolicy.RENAME, reserved)
        assert path == target
        assert action == "go"
        assert target in reserved

    def test_second_caller_gets_suffix_when_first_reserved(self, tmp_path):
        target = str(tmp_path / "out.mp4")
        reserved: set[str] = set()
        first, _ = reserve_output_path(target, ConflictPolicy.RENAME, reserved)
        second, action = reserve_output_path(target, ConflictPolicy.RENAME, reserved)
        assert action == "go"
        assert first != second
        assert second.endswith("out_1.mp4")

    def test_third_caller_gets_next_suffix(self, tmp_path):
        target = str(tmp_path / "out.mp4")
        reserved: set[str] = set()
        reserve_output_path(target, ConflictPolicy.RENAME, reserved)
        reserve_output_path(target, ConflictPolicy.RENAME, reserved)
        third, action = reserve_output_path(target, ConflictPolicy.RENAME, reserved)
        assert action == "go"
        assert third.endswith("out_2.mp4")

    def test_suffix_skips_existing_file_on_disk(self, tmp_path):
        target = str(tmp_path / "out.mp4")
        open(target, "w").close()
        open(str(tmp_path / "out_1.mp4"), "w").close()
        reserved: set[str] = set()
        path, action = reserve_output_path(target, ConflictPolicy.RENAME, reserved)
        assert action == "go"
        assert path.endswith("out_2.mp4")

    def test_skip_returns_without_reserving(self, tmp_path):
        target = str(tmp_path / "out.mp4")
        open(target, "w").close()
        reserved: set[str] = set()
        path, action = reserve_output_path(target, ConflictPolicy.SKIP, reserved)
        assert action == "skip"
        assert path == target
        assert target not in reserved

    def test_overwrite_reserves_target(self, tmp_path):
        target = str(tmp_path / "out.mp4")
        open(target, "w").close()
        reserved: set[str] = set()
        path, action = reserve_output_path(target, ConflictPolicy.OVERWRITE, reserved)
        assert action == "go"
        assert path == target
        assert target in reserved

    def test_ask_degrades_to_rename_at_runtime(self, tmp_path):
        target = str(tmp_path / "out.mp4")
        open(target, "w").close()
        reserved: set[str] = set()
        path, action = reserve_output_path(target, ConflictPolicy.ASK, reserved)
        assert action == "go"
        assert path.endswith("out_1.mp4")

    def test_concurrent_reservation_all_unique(self, tmp_path):
        """Threads racing on the same target must each get a unique path."""
        import threading
        target = str(tmp_path / "race.mp4")
        reserved: set[str] = set()
        lock = threading.Lock()
        results: list[str] = []

        def worker():
            with lock:
                path, _ = reserve_output_path(target, ConflictPolicy.RENAME, reserved)
            results.append(path)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 8
        assert len(set(results)) == 8, f"Duplicate reservations: {results}"
