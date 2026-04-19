# -*- coding: utf-8 -*-
"""ASS style injection for subtitle burn-in.

Crucial fix vs. v1: this module NEVER mutates the source subtitle file. The
original code would overwrite the user's `.ass` when it happened to already be
in ASS format.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass

from .. import constants


_STYLE_BLOCK: str = (
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, "
    "Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
    "Style: MyStyle,Arial,24,&HFF00FF,&H00000000,&H00000000,0,0,1,2,0,2,10,10,10\n\n"
)


@dataclass
class StyledSubtitle:
    """Result of style injection.

    Use this as a context manager so the temporary file is always cleaned up,
    even if ffmpeg crashes.
    """

    path: str
    _cleanup_path: str | None = None

    def __enter__(self) -> "StyledSubtitle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._cleanup_path and os.path.exists(self._cleanup_path):
            try:
                os.remove(self._cleanup_path)
            except OSError:
                pass  # Cleanup best-effort; don't mask the real error.


def _convert_to_ass(src: str, dst: str) -> None:
    """Run ffmpeg to transcode any subtitle format into ASS."""
    cmd = [constants.FFMPEG_PATH, "-i", src, dst]
    cp = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="ignore",
    )
    if cp.returncode != 0:
        raise RuntimeError(f"ffmpeg subtitle -> ASS failed:\n{cp.stderr}")


def inject_burn_style(source_subtitle: str) -> StyledSubtitle:
    """Produce a temporary ASS subtitle with our burn-in style block prepended.

    The returned StyledSubtitle owns the temp file; use it as a context
    manager or call `.__exit__()` when done.
    """
    ext = os.path.splitext(source_subtitle)[1].lower()

    # Always land in a temp file so we never touch the user's input.
    fd, tmp_path = tempfile.mkstemp(suffix=".ass", prefix="burn_")
    os.close(fd)

    try:
        if ext == ".ass":
            # Read user's ASS and copy, possibly prepending styles if missing.
            with open(source_subtitle, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            if "[V4+ Styles]" not in content:
                content = _STYLE_BLOCK + content
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            _convert_to_ass(source_subtitle, tmp_path)
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            if "[V4+ Styles]" not in content:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(_STYLE_BLOCK + content)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    return StyledSubtitle(path=tmp_path, _cleanup_path=tmp_path)
