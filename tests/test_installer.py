# -*- coding: utf-8 -*-
"""Tests for the ffmpeg installer module.

We don't actually hit the network here - that would be flaky and slow in CI.
The tests focus on the deterministic bits: path resolution, archive extraction,
executable-bit handling, and cache cleanup.
"""

from __future__ import annotations

import os
import stat
import sys
import zipfile
from pathlib import Path

import pytest

from converter.ffmpeg import installer
from converter.ffmpeg.installer import (
    APP_FOLDER_NAME,
    _extract,
    _plan_for_platform,
    app_data_dir,
    cached_binary_paths,
    ffmpeg_cache_dir,
    has_cached_binaries,
    remove_cache,
)


class TestPaths:
    def test_app_data_dir_is_under_home(self):
        d = app_data_dir()
        assert APP_FOLDER_NAME in str(d)
        # Should be somewhere under the user's home on every platform we support.
        assert str(d).startswith(os.path.expanduser("~")) or \
               str(d).startswith(os.environ.get("LOCALAPPDATA", "__unreachable__"))

    def test_ffmpeg_cache_dir_suffix(self):
        d = ffmpeg_cache_dir()
        assert d.name == "ffmpeg"
        assert d.parent == app_data_dir()

    def test_cached_binary_paths_platform_extension(self):
        ff, fp = cached_binary_paths()
        if sys.platform == "win32":
            assert ff.suffix == ".exe"
            assert fp.suffix == ".exe"
        else:
            assert ff.suffix == ""
            assert fp.suffix == ""
        assert ff.name.startswith("ffmpeg")
        assert fp.name.startswith("ffprobe")


class TestPlan:
    def test_plan_is_non_empty(self):
        plan = _plan_for_platform()
        assert plan
        for asset in plan:
            assert asset.url.startswith("http")
            assert asset.archive_kind in ("zip", "tar.xz", "tar.gz")
            assert asset.wanted_basenames

    def test_plan_wants_the_right_names(self):
        plan = _plan_for_platform()
        all_wanted = {name for a in plan for name in a.wanted_basenames}
        if sys.platform == "win32":
            assert "ffmpeg.exe" in all_wanted
            assert "ffprobe.exe" in all_wanted
        else:
            assert "ffmpeg" in all_wanted
            assert "ffprobe" in all_wanted


class TestExtract:
    def test_extracts_only_wanted_basenames(self, tmp_path: Path):
        archive = tmp_path / "test.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("some/dir/ffmpeg", b"fake ffmpeg binary")
            zf.writestr("unrelated/readme.txt", b"ignore me")
            zf.writestr("bin/ffprobe", b"fake ffprobe binary")

        dest = tmp_path / "out"
        extracted = _extract(archive, "zip", ("ffmpeg", "ffprobe"), dest)

        names = sorted(p.name for p in extracted)
        assert names == ["ffmpeg", "ffprobe"]
        # Nothing else sneaks in.
        assert sorted(p.name for p in dest.iterdir()) == names

    def test_marks_files_executable_on_unix(self, tmp_path: Path):
        if sys.platform == "win32":
            pytest.skip("exec bit is not a concept on Windows")
        archive = tmp_path / "a.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("ffmpeg", b"binary")
        dest = tmp_path / "out"
        _extract(archive, "zip", ("ffmpeg",), dest)
        mode = (dest / "ffmpeg").stat().st_mode
        assert mode & stat.S_IXUSR

    def test_unsupported_archive_kind_raises(self, tmp_path: Path):
        with pytest.raises(ValueError):
            _extract(tmp_path / "x", "bogus", ("ffmpeg",), tmp_path / "out")


class TestCacheLifecycle:
    def test_has_cached_binaries_when_dir_empty(self, monkeypatch, tmp_path):
        monkeypatch.setattr(installer, "app_data_dir",
                             lambda: tmp_path / "app_data")
        assert not has_cached_binaries()

    def test_remove_cache_missing_ok(self, monkeypatch, tmp_path):
        fake_root = tmp_path / "app_data"
        monkeypatch.setattr(installer, "app_data_dir", lambda: fake_root)
        assert remove_cache() is False  # nothing there yet

    def test_remove_cache_wipes_contents(self, monkeypatch, tmp_path):
        fake_root = tmp_path / "app_data"
        monkeypatch.setattr(installer, "app_data_dir", lambda: fake_root)
        cache = ffmpeg_cache_dir()
        cache.mkdir(parents=True)
        (cache / "ffmpeg").write_bytes(b"x")
        assert remove_cache() is True
        assert not cache.exists()


class TestResolverHonoursCache:
    """Ensure the cache dir participates in the real resolver path."""

    def test_cached_binary_wins_over_path(self, monkeypatch, tmp_path):
        from converter import constants

        fake_root = tmp_path / "app_data"
        monkeypatch.setattr(installer, "app_data_dir", lambda: fake_root)

        # Create a fake "ffmpeg" that succeeds with -version.
        cache = ffmpeg_cache_dir()
        cache.mkdir(parents=True)
        ff, _fp = cached_binary_paths()
        if sys.platform == "win32":
            pytest.skip("Windows executable fabrication not portable")
        ff.write_text("#!/bin/sh\nexit 0\n")
        ff.chmod(0o755)

        # Force the bundled path to not exist, and pretend PATH has nothing.
        monkeypatch.setattr(constants, "_candidate_bundled_paths",
                             lambda _: [str(tmp_path / "does-not-exist")])
        monkeypatch.setattr("shutil.which", lambda _: None)
        monkeypatch.setattr(constants, "_common_install_dirs", lambda: [])

        resolved = constants._resolve_executable("resources/ffmpeg", "ffmpeg")
        assert resolved == str(ff)
