# -*- coding: utf-8 -*-
"""Filesystem utilities: conflict resolution, filename templates, disk checks.

Concurrency notes
-----------------
The GUI dispatches multiple ``SingleFileRunnable`` instances that all want to
land their output in the same directory. If two of them independently call
``resolve_output_path`` on ``foo.mp4`` before either has started writing, they
would both pick ``foo_1.mp4`` and race to truncate each other. To prevent
that, the coordinator shares a *reserved set* with ``reserve_output_path``,
which atomically combines the on-disk "already exists" check with the
in-memory "already promised to another runnable" check.
"""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Container
from datetime import datetime
from enum import Enum
from typing import Literal


class ConflictPolicy(str, Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    RENAME = "rename"
    ASK = "ask"


ResolveAction = Literal["go", "skip"]


def resolve_output_path(
    target: str, policy: ConflictPolicy,
) -> tuple[str, ResolveAction]:
    """Apply *policy* to *target* and return (final_path, action).

    Single-threaded shortcut: no awareness of other reservations. Suitable
    for CLI or for the non-concurrent burn/merge single-shot runnables.
    Multi-file concurrent batches must go through ``reserve_output_path``.

    For ``ASK``, the caller is expected to have already resolved conflicts
    upstream (estimate dialog). At runtime we degrade gracefully to RENAME
    so a stale ASK never blocks a worker thread with a modal dialog.
    """
    if not os.path.exists(target):
        return target, "go"

    if policy == ConflictPolicy.OVERWRITE:
        return target, "go"

    if policy == ConflictPolicy.SKIP:
        return target, "skip"

    return _find_unique_name(target, _ExistsOnDisk()), "go"


def reserve_output_path(
    target: str,
    policy: ConflictPolicy,
    reserved: set[str],
) -> tuple[str, ResolveAction]:
    """Atomic version of :func:`resolve_output_path` for concurrent workers.

    The *reserved* set records every path another runnable has already
    promised to write. Callers MUST hold a lock around this function AND
    pass in the same shared set so reservations don't clobber each other.

    Semantics matrix:

    =========== ================================================
    policy      behaviour when target conflicts
    =========== ================================================
    SKIP        return (target, "skip"); no reservation made
    OVERWRITE   reserve target even if it exists on disk; "go"
    RENAME/ASK  find lowest ``_N`` suffix not in disk ∪ reserved
    =========== ================================================
    """
    already = _CombinedBusy(reserved)

    if target not in already:
        reserved.add(target)
        return target, "go"

    if policy == ConflictPolicy.OVERWRITE:
        reserved.add(target)
        return target, "go"

    if policy == ConflictPolicy.SKIP:
        return target, "skip"

    unique = _find_unique_name(target, already)
    reserved.add(unique)
    return unique, "go"


class _ExistsOnDisk:
    """Container-like adaptor: ``path in _ExistsOnDisk()`` <=> on-disk check."""

    def __contains__(self, path: object) -> bool:
        return isinstance(path, str) and os.path.exists(path)


class _CombinedBusy:
    """Union of 'already on disk' and 'already reserved in memory'.

    Used by ``_find_unique_name`` so concurrent workers and existing files
    are treated as the same kind of obstacle when picking a suffix.
    """

    __slots__ = ("_reserved",)

    def __init__(self, reserved: Container[str]) -> None:
        self._reserved = reserved

    def __contains__(self, path: object) -> bool:
        if not isinstance(path, str):
            return False
        return path in self._reserved or os.path.exists(path)


def _find_unique_name(path: str, busy: Container[str]) -> str:
    """Return a suffixed variant of *path* not present in *busy*."""
    base, ext = os.path.splitext(path)
    for i in range(1, 10000):
        candidate = f"{base}_{i}{ext}"
        if candidate not in busy:
            return candidate
    return f"{base}_{int(time.time())}{ext}"


# ---- Filename template engine ------------------------------------------------

_TEMPLATE_VARS_HELP = (
    "{base}     原文件名（不含扩展名）\n"
    "{ext}      原文件扩展名\n"
    "{target}   目标格式\n"
    "{quality}  质量预设名\n"
    "{preset}   任务预设名\n"
    "{date}     日期 YYYYMMDD\n"
    "{datetime} 日期时间 YYYYMMDD_HHMMSS\n"
    "{count}    批量序号（从 1 开始）\n"
    "{parent}   上级目录名"
)

TEMPLATE_VARS_HELP = _TEMPLATE_VARS_HELP


def format_output_name(
    template: str,
    source_path: str,
    target_format: str,
    *,
    quality_name: str = "",
    preset_name: str = "",
    index: int = 1,
) -> str:
    """Expand a filename template with the given variables.

    Returns a bare filename (no directory, no target extension).
    """
    base = os.path.splitext(os.path.basename(source_path))[0]
    ext = os.path.splitext(source_path)[1].lstrip(".")
    parent = os.path.basename(os.path.dirname(source_path))
    now = datetime.now()

    mapping = {
        "base": base,
        "ext": ext,
        "target": target_format,
        "quality": quality_name,
        "preset": preset_name,
        "date": now.strftime("%Y%m%d"),
        "datetime": now.strftime("%Y%m%d_%H%M%S"),
        "count": str(index),
        "parent": parent,
    }
    try:
        result = template.format_map(mapping)
    except (KeyError, ValueError):
        result = base
    return _sanitize_filename(result) or base


def _sanitize_filename(name: str) -> str:
    """Strip characters illegal on Windows / macOS."""
    for ch in r'<>:"/\|?*':
        name = name.replace(ch, "_")
    return name.strip(". ")


# ---- Disk space helpers ------------------------------------------------------

def disk_free_bytes(path: str) -> int:
    """Return free bytes on the volume containing *path*."""
    try:
        usage = shutil.disk_usage(os.path.dirname(os.path.abspath(path)) or "/")
        return usage.free
    except OSError:
        return 0


# ---- Subdirectory mirroring --------------------------------------------------

def mirrored_output_path(
    source_path: str,
    source_root: str,
    output_dir: str,
) -> str:
    """Compute the output *directory* that mirrors the relative structure."""
    try:
        rel = os.path.relpath(os.path.dirname(source_path), source_root)
    except ValueError:
        rel = ""
    if rel == ".":
        rel = ""
    return os.path.join(output_dir, rel) if rel else output_dir
