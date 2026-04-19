# -*- coding: utf-8 -*-
"""Tests for converter.planning: deterministic conflict-aware planning."""

import os

import pytest

from converter.fs import ConflictPolicy
from converter.planning import PlanEntry, plan_output_paths


class TestPlanOutputPaths:
    def test_no_conflicts_clean_plan(self, tmp_path):
        files = [str(tmp_path / f"src_{i}.wav") for i in range(3)]
        for f in files:
            open(f, "w").close()
        plan = plan_output_paths(
            files, target_format="mp3",
            output_dir=str(tmp_path), policy=ConflictPolicy.RENAME,
        )
        outputs = [plan.get(f).output_path for f in files]
        assert len(set(outputs)) == 3
        for entry in plan.entries.values():
            assert entry.action == "go"
            assert entry.output_path.endswith(".mp3")

    def test_same_base_name_gets_unique_suffixes(self, tmp_path):
        """Two sources with the same basename must land on different outputs."""
        d1 = tmp_path / "a"
        d2 = tmp_path / "b"
        d1.mkdir()
        d2.mkdir()
        s1 = str(d1 / "song.wav")
        s2 = str(d2 / "song.wav")
        open(s1, "w").close()
        open(s2, "w").close()
        plan = plan_output_paths(
            [s1, s2], target_format="mp3",
            output_dir=str(tmp_path), policy=ConflictPolicy.RENAME,
        )
        outs = {plan.get(s1).output_path, plan.get(s2).output_path}
        assert len(outs) == 2

    def test_existing_file_triggers_rename(self, tmp_path):
        src = str(tmp_path / "x.wav")
        open(src, "w").close()
        existing = str(tmp_path / "x.mp3")
        open(existing, "w").close()
        plan = plan_output_paths(
            [src], target_format="mp3",
            output_dir=str(tmp_path), policy=ConflictPolicy.RENAME,
        )
        entry = plan.get(src)
        assert entry is not None
        assert entry.action == "go"
        assert entry.output_path != existing
        assert entry.output_path.endswith("x_1.mp3")

    def test_skip_policy_marks_skip(self, tmp_path):
        src = str(tmp_path / "x.wav")
        open(src, "w").close()
        existing = str(tmp_path / "x.mp3")
        open(existing, "w").close()
        plan = plan_output_paths(
            [src], target_format="mp3",
            output_dir=str(tmp_path), policy=ConflictPolicy.SKIP,
        )
        entry = plan.get(src)
        assert entry.skipped
        assert entry.action == "skip"

    def test_overwrite_uses_target_path(self, tmp_path):
        src = str(tmp_path / "x.wav")
        open(src, "w").close()
        existing = str(tmp_path / "x.mp3")
        open(existing, "w").close()
        plan = plan_output_paths(
            [src], target_format="mp3",
            output_dir=str(tmp_path), policy=ConflictPolicy.OVERWRITE,
        )
        entry = plan.get(src)
        assert entry.action == "go"
        assert entry.output_path == existing

    def test_ask_degrades_to_rename(self, tmp_path):
        src = str(tmp_path / "x.wav")
        open(src, "w").close()
        existing = str(tmp_path / "x.mp3")
        open(existing, "w").close()
        plan = plan_output_paths(
            [src], target_format="mp3",
            output_dir=str(tmp_path), policy=ConflictPolicy.ASK,
        )
        entry = plan.get(src)
        assert entry.action == "go"
        assert entry.output_path.endswith("x_1.mp3")

    def test_duplicate_source_in_input_deduplicated(self, tmp_path):
        """Feeding the same source twice doesn't create two plan entries."""
        src = str(tmp_path / "x.wav")
        open(src, "w").close()
        plan = plan_output_paths(
            [src, src], target_format="mp3",
            output_dir=str(tmp_path), policy=ConflictPolicy.RENAME,
        )
        assert len(plan) == 1

    def test_plan_entry_immutable(self, tmp_path):
        src = str(tmp_path / "x.wav")
        open(src, "w").close()
        plan = plan_output_paths(
            [src], target_format="mp3",
            output_dir=str(tmp_path), policy=ConflictPolicy.RENAME,
        )
        entry = plan.get(src)
        with pytest.raises((AttributeError, Exception)):
            entry.output_path = "/other.mp3"
