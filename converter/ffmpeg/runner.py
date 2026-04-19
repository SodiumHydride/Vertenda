# -*- coding: utf-8 -*-
"""FFmpeg subprocess runner with proper cancellation semantics.

Unlike the original implementation, `CancelToken.cancel()` actively terminates
the child process instead of merely setting a flag that the readline loop
happens to check.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Callable, Optional


_TIME_PATTERN = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def _time_hms_from_seconds(total_seconds: float) -> str:
    h = int(total_seconds // 3600)
    m = int((total_seconds % 3600) // 60)
    s = int(total_seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


@dataclass
class RunResult:
    ok: bool
    stderr_tail: str = ""
    cancelled: bool = False


class CancelToken:
    """Thread-safe cancel signal that can forcibly terminate an attached process."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None

    def attach(self, proc: subprocess.Popen) -> None:
        with self._lock:
            self._proc = proc

    def detach(self) -> None:
        with self._lock:
            self._proc = None

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            proc = self._proc
        if proc is None:
            return
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
        except OSError:
            return
        # Give ffmpeg ~2s to flush output and exit cleanly; escalate if it won't.
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass


def run_with_progress(
    cmd: list[str],
    total_duration: float,
    *,
    on_progress: Callable[[int], None],
    on_time: Callable[[str], None],
    on_log: Callable[[str], None],
    cancel: CancelToken,
    log_buffer_lines: int = 200,
) -> RunResult:
    """Execute ffmpeg and stream progress via callbacks.

    - `on_progress(int)` is called with a 0..100 percentage.
    - `on_time(str)` is called with a 'HH:MM:SS' current position.
    - `on_log(str)` is called with raw ffmpeg stderr lines.

    The callbacks are invoked from the reader thread; consumers are
    responsible for thread-safe UI marshalling (e.g. Qt signals).
    """
    if total_duration <= 0:
        total_duration = 1.0

    popen_kwargs = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    try:
        process = subprocess.Popen(cmd, **popen_kwargs)
    except (OSError, ValueError) as exc:
        on_log(f"[启动失败] {exc}\n")
        return RunResult(ok=False, stderr_tail=str(exc))

    cancel.attach(process)
    tail: list[str] = []

    try:
        assert process.stdout is not None
        last_progress = -1
        for line in process.stdout:
            tail.append(line)
            if len(tail) > log_buffer_lines:
                del tail[0]

            if cancel.cancelled:
                break

            match = _TIME_PATTERN.search(line)
            if match:
                current = (
                    int(match.group(1)) * 3600
                    + int(match.group(2)) * 60
                    + float(match.group(3))
                )
                progress = max(0, min(100, int(current / total_duration * 100)))
                if progress != last_progress:
                    on_progress(progress)
                    on_time(_time_hms_from_seconds(current))
                    last_progress = progress

            on_log(line.rstrip("\n"))
    finally:
        try:
            process.wait()
        except Exception:
            pass
        cancel.detach()

    if cancel.cancelled and process.returncode != 0:
        return RunResult(ok=False, cancelled=True, stderr_tail="".join(tail[-20:]))
    if process.returncode != 0:
        return RunResult(ok=False, stderr_tail="".join(tail[-20:]))
    return RunResult(ok=True)


def run_blocking(cmd: list[str]) -> RunResult:
    """Simple blocking ffmpeg run for operations without per-file progress."""
    popen_kwargs = dict(
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    try:
        cp = subprocess.run(cmd, **popen_kwargs)
    except (OSError, subprocess.SubprocessError) as exc:
        return RunResult(ok=False, stderr_tail=str(exc))
    if cp.returncode != 0:
        return RunResult(ok=False, stderr_tail=cp.stderr or "")
    return RunResult(ok=True)
