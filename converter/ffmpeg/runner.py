# -*- coding: utf-8 -*-
"""FFmpeg subprocess runner with proper cancellation semantics.

CancelToken state machine
-------------------------

Every ``SingleFileRunnable`` holds its own token.  The token coordinates four
independent concerns so the coordinator can reason about them without racing:

  * a subprocess.Popen handle (``_proc``) that may or may not be attached
  * a pause/resume latch used by the reader loop and the runnable gate
  * a cancel event that short-circuits the reader loop
  * an explicit state enum used for observability / debugging

Transition table::

    ┌──────────┐ pause()     ┌────────┐ resume()   ┌──────────┐
    │ RUNNING  ├────────────▶│ PAUSED ├───────────▶│ RUNNING  │
    └────┬─────┘             └────┬───┘             └─────┬────┘
         │ cancel()               │ cancel()              │ cancel()
         ▼                        ▼                       ▼
    ┌──────────┐ wait(timeout) ┌───────────┐
    │CANCELLING├──────────────▶│ CANCELLED │
    └──────────┘               └───────────┘
                (and independently, natural exit → FINISHED)

Observed guarantees:
  * ``cancel()`` unblocks any pause latch so the runnable doesn't deadlock.
  * A cancel arriving before ``attach`` is remembered; the next ``attach``
    immediately terminates the new process.
  * ``pause()`` while CANCELLING/CANCELLED/FINISHED is a no-op.
"""

from __future__ import annotations

import re
import subprocess
import sys
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

try:
    import psutil  # noqa: F401  -- used lazily in _suspend/_resume
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


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


class TokenState(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FINISHED = "finished"


_TERMINAL_STATES = frozenset({
    TokenState.CANCELLING, TokenState.CANCELLED, TokenState.FINISHED,
})


class CancelToken:
    """Thread-safe cancel/pause signal bound to (at most) one subprocess."""

    def __init__(self) -> None:
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # not paused initially
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._state: TokenState = TokenState.RUNNING

    # ---- lifecycle hooks called by run_with_progress -----------------

    def attach(self, proc: subprocess.Popen) -> None:
        """Bind a newly-started subprocess. If cancel arrived first, kill now."""
        with self._lock:
            self._proc = proc
            cancel_pending = self._cancel_event.is_set()
        if cancel_pending:
            self._terminate_proc(proc)
            with self._lock:
                self._state = TokenState.CANCELLED

    def detach(self) -> None:
        """Release the subprocess reference once it has exited."""
        with self._lock:
            self._proc = None
            if self._cancel_event.is_set():
                self._state = TokenState.CANCELLED
            elif self._state not in _TERMINAL_STATES:
                self._state = TokenState.FINISHED
            self._pause_event.set()

    # ---- observable properties ---------------------------------------

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def paused(self) -> bool:
        return not self._pause_event.is_set()

    @property
    def state(self) -> TokenState:
        with self._lock:
            return self._state

    # ---- control surface ---------------------------------------------

    def cancel(self) -> None:
        """Terminate the attached process (if any) and flip to CANCELLED.

        If no process is attached yet, we go straight to CANCELLED — there's
        nothing to tear down. A subsequent ``attach()`` will still kill the
        newly-started process because ``_cancel_event`` is set.
        """
        self._cancel_event.set()
        self._pause_event.set()  # unblock any pause latch
        with self._lock:
            if self._state == TokenState.FINISHED:
                return
            self._state = TokenState.CANCELLING
            proc = self._proc
        if proc is None:
            with self._lock:
                self._state = TokenState.CANCELLED
            return
        self._terminate_proc(proc)
        with self._lock:
            self._state = TokenState.CANCELLED

    def pause(self) -> None:
        """Suspend the attached ffmpeg (best-effort, needs psutil).

        No-op if the token is already cancelling/cancelled/finished —
        otherwise we'd accidentally wake a runnable that's mid-teardown.
        """
        with self._lock:
            if self._state in _TERMINAL_STATES:
                return
            if self._cancel_event.is_set():
                return
            self._state = TokenState.PAUSED
            proc = self._proc
        self._pause_event.clear()
        if proc is not None and proc.poll() is None:
            self._suspend_proc(proc)

    def resume(self) -> None:
        """Wake the runnable and resume the ffmpeg process."""
        with self._lock:
            if self._state in _TERMINAL_STATES:
                self._pause_event.set()
                return
            proc = self._proc
            if self._state == TokenState.PAUSED:
                self._state = TokenState.RUNNING
        if proc is not None and proc.poll() is None:
            self._resume_proc(proc)
        self._pause_event.set()

    def wait_if_paused(self) -> None:
        """Block until no longer paused (or cancelled)."""
        self._pause_event.wait()

    # ---- helpers -----------------------------------------------------

    @staticmethod
    def _terminate_proc(proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
        except OSError:
            return
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass

    @staticmethod
    def _suspend_proc(proc: subprocess.Popen) -> None:
        if not _HAS_PSUTIL:
            return
        try:
            import psutil
            psutil.Process(proc.pid).suspend()
        except Exception:
            # psutil failures are non-fatal; pause just degrades to no-op.
            pass

    @staticmethod
    def _resume_proc(proc: subprocess.Popen) -> None:
        if not _HAS_PSUTIL:
            return
        try:
            import psutil
            psutil.Process(proc.pid).resume()
        except Exception:
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

    - ``on_progress(int)`` is called with a 0..100 percentage.
    - ``on_time(str)`` is called with a 'HH:MM:SS' current position.
    - ``on_log(str)`` is called with raw ffmpeg stderr lines.

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
