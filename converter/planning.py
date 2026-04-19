# -*- coding: utf-8 -*-
"""Conflict resolution pre-pass.

Rationale
---------
The estimate dialog already walks every source file to measure duration and
detect conflicts. We piggyback on that walk to produce a deterministic
*plan table* that the concurrent runnables consume at runtime. Benefits:

  * No lock contention during batch execution (the plan is frozen).
  * RENAME suffixes are picked in source-file order, which is predictable
    for users watching a progress list.
  * ASK is resolved once (in the estimate dialog) and baked into the plan,
    so runnables never face a modal-dialog-in-a-background-thread situation.

Fallback: if the plan is missing for a file (e.g. retry that wasn't
re-estimated), the runnable falls back to :func:`converter.fs.reserve_output_path`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from .fs import (
    ConflictPolicy,
    _find_unique_name,
    _CombinedBusy,
    format_output_name,
    mirrored_output_path,
)


@dataclass(frozen=True)
class PlanEntry:
    """A single source -> output decision. Immutable once planned."""

    source: str
    output_path: str
    action: str  # "go" | "skip"

    @property
    def skipped(self) -> bool:
        return self.action == "skip"


@dataclass
class OutputPlan:
    """Frozen map source_path -> PlanEntry."""

    entries: dict[str, PlanEntry]

    def get(self, source: str) -> Optional[PlanEntry]:
        return self.entries.get(source)

    def __len__(self) -> int:
        return len(self.entries)


def plan_output_paths(
    files: list[str],
    *,
    target_format: str,
    output_dir: str,
    policy: ConflictPolicy,
    filename_template: str = "{base}",
    quality_name: str = "",
    preset_name: str = "",
    mirror_subdirs: bool = False,
    source_root: str = "",
) -> OutputPlan:
    """Build a complete output-path plan for *files* under *policy*.

    The plan accounts for both existing files on disk AND uniqueness across
    the batch itself: two sources that would otherwise produce the same
    output name get distinct ``_N`` suffixes even if neither output exists
    on disk yet. ``ASK`` degrades to ``RENAME`` at planning time so the
    runtime never needs user input.
    """
    reserved: set[str] = set()
    busy = _CombinedBusy(reserved)
    entries: dict[str, PlanEntry] = {}

    for idx, src in enumerate(files, start=1):
        if not src or src in entries:
            # Duplicate source paths in the input list — just reuse.
            continue

        out_name = format_output_name(
            filename_template, src, target_format,
            quality_name=quality_name, preset_name=preset_name, index=idx,
        )
        out_dir = (
            mirrored_output_path(src, source_root, output_dir)
            if mirror_subdirs and source_root
            else (output_dir or os.path.dirname(src))
        )
        candidate = os.path.join(out_dir, f"{out_name}.{target_format}")

        entry = _decide(candidate, policy, reserved, busy)
        entries[src] = PlanEntry(source=src, output_path=entry[0], action=entry[1])

    return OutputPlan(entries=entries)


def _decide(
    candidate: str,
    policy: ConflictPolicy,
    reserved: set[str],
    busy: _CombinedBusy,
) -> tuple[str, str]:
    """Core decision logic — mirrors ``fs.reserve_output_path`` semantics.

    Kept private here rather than re-using ``reserve_output_path`` because
    the planning pass needs the *same* busy set to persist across all files
    in the batch, whereas the runtime helper creates a fresh view each call.
    """
    if candidate not in busy:
        reserved.add(candidate)
        return candidate, "go"

    if policy == ConflictPolicy.OVERWRITE:
        reserved.add(candidate)
        return candidate, "go"

    if policy == ConflictPolicy.SKIP:
        return candidate, "skip"

    unique = _find_unique_name(candidate, busy)
    reserved.add(unique)
    return unique, "go"
