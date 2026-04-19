# -*- coding: utf-8 -*-
"""Task queue, coordinator, and per-file runnable for concurrent conversion.

Architecture
------------

::

    TaskQueue           ordered list of ConvertTask (FIFO + reorder)
    TaskCoordinator     owns QThreadPool, dispatches runnables, aggregates
                        results and emits ExecutionEvent to subscribers
    SignalHub (QObject) thread-safe bridge — QRunnable cannot emit signals
    SingleFileRunnable  processes exactly one file with its OWN CancelToken
    BurnRunnable        single-shot burn; never concurrent
    MergeRunnable       single-shot audio+video mux

Concurrency invariants
----------------------
* Each SingleFileRunnable has its OWN CancelToken. Pausing/cancelling a
  runnable never affects a sibling running on the pool.
* Conflict resolution runs in two steps: *plan* (at estimate time, no lock)
  and *runtime reservation* (locked fallback for files missing from the plan).
* ``continue_on_failure=False`` = *soft stop*: we stop dispatching new work
  and clear the pending queue, but in-flight runnables run to completion.
* ``cancel_all()`` aggressively kills running ffmpeg processes AND
  synthesises CANCELLED events for any runnable that never started.

Event bus
---------
All state changes flow through ``hub.execution_event`` as
:class:`ExecutionEvent`. History and notification plumbing subscribe to
that single signal rather than wiring multiple one-off connections.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, QTimer, pyqtSignal

from .constants import (
    AUDIO_EXTS,
    ext_of,
    is_audio_file,
    is_lrc_file,
    is_subtitle_file,
    is_video_file,
)
from .ffmpeg.commands import (
    build_burn_subtitle_cmd,
    build_convert_cmd,
    build_extract_audio_cmd,
    build_merge_av_cmd,
    build_subtitle_transcode_cmd,
)
from .ffmpeg.probe import get_media_duration
from .ffmpeg.quality import QualitySpec, spec_for
from .ffmpeg.runner import CancelToken, RunResult, run_blocking, run_with_progress
from .fs import (
    ConflictPolicy,
    format_output_name,
    mirrored_output_path,
    reserve_output_path,
)
from .planning import OutputPlan, PlanEntry
from .subtitle.converters import SubtitleConversionError, lrc_to_srt, lrc_to_vtt, srt_to_lrc, vtt_to_lrc
from .subtitle.styling import inject_burn_style
from .subtitle.styling_config import BurnStyle, DEFAULT_BURN_STYLE_OBJ
from .worker import BurnOptions, ConvertTask, TaskKind


# ---- Event / result types ---------------------------------------------------


class FileStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class FileResult:
    source: str
    output: str
    status: FileStatus
    reason: str = ""
    elapsed_s: float = 0.0


class EventType(str, Enum):
    QUEUED = "queued"
    STARTED = "started"
    PROGRESS = "progress"
    DONE = "done"
    ALL_DONE = "all_done"
    SOFT_STOP = "soft_stop"


@dataclass
class ExecutionEvent:
    """Unified event payload for UI / history / notifier subscribers."""

    type: str  # EventType.value
    source: str = ""
    status: str = ""
    message: str = ""
    output: str = ""
    index: int = 0
    total: int = 0
    progress: int = 0


# ---- Signal bridge ----------------------------------------------------------


class SignalHub(QObject):
    """Thread-safe bridge: runnables emit via these signals, UI listens."""

    file_started = pyqtSignal(int, int, str)
    file_progress = pyqtSignal(int)
    file_time = pyqtSignal(str)
    file_done = pyqtSignal(object)                  # FileResult
    execution_event = pyqtSignal(object)            # ExecutionEvent
    log = pyqtSignal(str)
    overall_progress = pyqtSignal(int)
    eta = pyqtSignal(str)
    task_done = pyqtSignal(bool)
    error = pyqtSignal(str)


# ---- TaskQueue --------------------------------------------------------------


class TaskQueue:
    """Ordered list of ConvertTask with FIFO semantics and reorder support."""

    def __init__(self) -> None:
        self._tasks: list[ConvertTask] = []
        self._current_index: int = 0

    def enqueue(self, task: ConvertTask) -> None:
        self._tasks.append(task)

    def dequeue(self) -> ConvertTask | None:
        if self._current_index >= len(self._tasks):
            return None
        task = self._tasks[self._current_index]
        self._current_index += 1
        return task

    def peek(self) -> ConvertTask | None:
        if self._current_index >= len(self._tasks):
            return None
        return self._tasks[self._current_index]

    @property
    def pending(self) -> list[ConvertTask]:
        return self._tasks[self._current_index:]

    @property
    def all_tasks(self) -> list[ConvertTask]:
        return list(self._tasks)

    @property
    def current_index(self) -> int:
        return self._current_index

    def is_empty(self) -> bool:
        return self._current_index >= len(self._tasks)

    def total(self) -> int:
        return len(self._tasks)

    def clear(self) -> None:
        self._tasks.clear()
        self._current_index = 0

    def clear_pending(self) -> int:
        """Drop tasks not yet dispatched. Returns count removed."""
        removed = len(self._tasks) - self._current_index
        if removed > 0:
            self._tasks = self._tasks[: self._current_index]
        return max(0, removed)

    def remove_pending(self, index: int) -> bool:
        actual = self._current_index + index
        if 0 <= actual < len(self._tasks) and actual >= self._current_index:
            self._tasks.pop(actual)
            return True
        return False

    def move_up(self, index: int) -> bool:
        actual = self._current_index + index
        if actual > self._current_index and actual < len(self._tasks):
            self._tasks[actual - 1], self._tasks[actual] = (
                self._tasks[actual], self._tasks[actual - 1],
            )
            return True
        return False

    def move_down(self, index: int) -> bool:
        actual = self._current_index + index
        if actual >= self._current_index and actual < len(self._tasks) - 1:
            self._tasks[actual], self._tasks[actual + 1] = (
                self._tasks[actual + 1], self._tasks[actual],
            )
            return True
        return False


# ---- Concurrency helpers ----------------------------------------------------


def _physical_core_count() -> int:
    """Best-effort physical core count (falls back to logical count)."""
    try:
        import psutil
        n = psutil.cpu_count(logical=False)
        if n and n > 0:
            return int(n)
    except Exception:
        pass
    try:
        return os.cpu_count() or 2
    except Exception:
        return 2


def auto_concurrency(use_hw: bool, is_burn: bool) -> int:
    """Safe worker count. HW / burn force single-track; software caps at 4.

    We use *physical* cores, not logical: transcoding is CPU-bound enough
    that hyperthreaded siblings rarely help, and the OS scheduler already
    owns the ffmpeg-internal thread parallelism.
    """
    if is_burn or use_hw:
        return 1
    return max(1, min(_physical_core_count(), 4))


def resolve_concurrency(mode: str, use_hw: bool, is_burn: bool) -> int:
    if mode == "auto" or not mode:
        return auto_concurrency(use_hw, is_burn)
    try:
        n = int(mode)
        return max(1, min(n, 8))
    except ValueError:
        return auto_concurrency(use_hw, is_burn)


# ---- Utility helpers --------------------------------------------------------


def _format_eta(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:  # guard NaN
        return "--"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m, s = divmod(s, 60)
        return f"{m}m{s:02d}s"
    h, rem = divmod(s, 3600)
    m = rem // 60
    return f"{h}h{m:02d}m"


# ---- Per-file runnable ------------------------------------------------------


class SingleFileRunnable(QRunnable):
    """Process one file from a ConvertTask. Owns its own CancelToken."""

    _LOG_THROTTLE = 0.15

    def __init__(
        self,
        source: str,
        task: ConvertTask,
        index: int,
        total: int,
        hub: SignalHub,
        token: CancelToken,
        global_start: float,
        resolve_path: Callable[[str, ConflictPolicy], tuple[str, str]],
        planned: Optional[PlanEntry] = None,
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.source = source
        self.task = task
        self.index = index
        self.total = total
        self.hub = hub
        self.cancel = token
        self._spec = spec_for(task.quality)
        self._global_start = global_start
        self._resolve_path = resolve_path
        self._planned = planned
        self._last_log_emit = 0.0
        self._log_buffer: list[str] = []

    def run(self) -> None:
        self.cancel.wait_if_paused()
        if self.cancel.cancelled:
            self.hub.file_done.emit(FileResult(
                self.source, "", FileStatus.CANCELLED,
            ))
            return

        t0 = time.monotonic()
        self.hub.file_started.emit(self.index, self.total, os.path.basename(self.source))
        self.hub.execution_event.emit(ExecutionEvent(
            type=EventType.STARTED.value, source=self.source,
            index=self.index, total=self.total,
        ))

        try:
            result = self._process()
        except Exception as exc:  # noqa: BLE001
            result = FileResult(self.source, "", FileStatus.FAILED, str(exc))

        result.elapsed_s = time.monotonic() - t0
        self.hub.file_done.emit(result)

    # ---- dispatch ------------------------------------------------

    def _process(self) -> FileResult:
        if not os.path.exists(self.source):
            return FileResult(self.source, "", FileStatus.SKIPPED, "文件不存在")
        if self.task.kind == TaskKind.SUBTITLE:
            return self._process_subtitle(self.source)
        return self._process_media(self.source)

    # ---- media ---------------------------------------------------

    def _process_media(self, src: str) -> FileResult:
        task = self.task
        target_ext_dot = "." + task.target_format.lower()
        extract_audio = target_ext_dot in AUDIO_EXTS and task.kind == TaskKind.VIDEO

        if is_lrc_file(src):
            return FileResult(src, "", FileStatus.SKIPPED, f"LRC 不能转换为 {task.target_format}")
        if extract_audio and not is_video_file(src):
            return FileResult(src, "", FileStatus.SKIPPED, "提取音频只接受视频文件")

        out_path, action = self._resolve_output(src, task, task.target_format)
        if action == "skip":
            return FileResult(src, out_path, FileStatus.SKIPPED, "文件已存在，按策略跳过")

        out_dir = os.path.dirname(out_path)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            return FileResult(src, out_path, FileStatus.FAILED, f"创建输出目录失败: {exc}")

        if extract_audio:
            cmd = build_extract_audio_cmd(
                src, out_path, spec=self._spec,
                trim_start=task.trim_start, trim_end=task.trim_end,
                volume_normalize=task.volume_normalize,
            )
        else:
            cmd = build_convert_cmd(
                src, out_path, use_hw=task.use_hw_accel, spec=self._spec,
                trim_start=task.trim_start, trim_end=task.trim_end,
                scale_preset=task.scale_preset,
                volume_normalize=task.volume_normalize,
                two_pass=task.two_pass,
            )

        duration = get_media_duration(src) or 1.0
        result = run_with_progress(
            cmd, duration,
            on_progress=lambda p: self.hub.file_progress.emit(p),
            on_time=self.hub.file_time.emit,
            on_log=lambda line: self._emit_log(line),
            cancel=self.cancel,
        )
        self._flush_log()

        if result.cancelled:
            return FileResult(src, out_path, FileStatus.CANCELLED)
        if not result.ok:
            return FileResult(src, out_path, FileStatus.FAILED, result.stderr_tail.strip())
        self._emit_log(f"[OK] {src} -> {out_path}", force=True)
        return FileResult(src, out_path, FileStatus.SUCCESS)

    # ---- subtitles -----------------------------------------------

    def _process_subtitle(self, src: str) -> FileResult:
        task = self.task
        if not is_subtitle_file(src):
            return FileResult(src, "", FileStatus.SKIPPED, "非字幕文件")

        target = task.target_format.lower()
        src_ext = ext_of(src)
        if src_ext == f".{target}":
            return FileResult(src, "", FileStatus.SKIPPED, f"源文件已是 {target}")

        out_path, action = self._resolve_output(src, task, target)
        if action == "skip":
            return FileResult(src, out_path, FileStatus.SKIPPED, "文件已存在，按策略跳过")

        out_dir = os.path.dirname(out_path)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            return FileResult(src, out_path, FileStatus.FAILED, f"创建输出目录失败: {exc}")

        base = os.path.splitext(os.path.basename(out_path))[0]
        try:
            self._convert_subtitle_inner(src, src_ext, target, out_path, out_dir, base)
            return FileResult(src, out_path, FileStatus.SUCCESS)
        except (SubtitleConversionError, RuntimeError, OSError) as exc:
            return FileResult(src, out_path, FileStatus.FAILED, str(exc))

    def _convert_subtitle_inner(
        self, src: str, src_ext: str, target: str, out_path: str,
        out_dir: str, base: str,
    ) -> None:
        if target == "lrc":
            if src_ext == ".srt":
                srt_to_lrc(src, out_path)
            elif src_ext == ".vtt":
                vtt_to_lrc(src, out_path)
            elif src_ext in (".ass", ".ssa"):
                tmp_srt = os.path.join(out_dir, f"{base}.__tmp__.srt")
                result = run_blocking(build_subtitle_transcode_cmd(src, tmp_srt))
                try:
                    if not result.ok:
                        raise RuntimeError(f"ffmpeg transcode failed: {result.stderr_tail.strip()}")
                    srt_to_lrc(tmp_srt, out_path)
                finally:
                    if os.path.exists(tmp_srt):
                        os.remove(tmp_srt)
            else:
                raise RuntimeError(f"不支持从 {src_ext} 转 LRC")
            return

        if target == "srt" and src_ext == ".lrc":
            lrc_to_srt(src, out_path)
            return
        if target == "vtt" and src_ext == ".lrc":
            lrc_to_vtt(src, out_path)
            return
        if target == "lrc" and src_ext == ".lrc":
            raise RuntimeError(f"不支持从 {src_ext} 转 LRC")

        res = run_blocking(build_subtitle_transcode_cmd(src, out_path))
        if not res.ok:
            raise RuntimeError(res.stderr_tail.strip())

    # ---- path resolution ----------------------------------------

    def _resolve_output(
        self, src: str, task: ConvertTask, target_format: str,
    ) -> tuple[str, str]:
        """Plan-table first, fall back to locked reservation."""
        if self._planned is not None and self._planned.source == src:
            return self._planned.output_path, self._planned.action

        out_name = format_output_name(
            task.filename_template, src, target_format,
            quality_name=task.quality.value, preset_name=task.preset_name,
            index=self.index,
        )
        if task.mirror_subdirs and task.source_root:
            out_dir = mirrored_output_path(src, task.source_root, task.output_dir)
        else:
            out_dir = task.output_dir or os.path.dirname(src)
        target = os.path.join(out_dir, f"{out_name}.{target_format}")
        return self._resolve_path(target, task.conflict_policy)

    # ---- logging helpers -----------------------------------------

    def _emit_log(self, msg: str, *, force: bool = False) -> None:
        self._log_buffer.append(msg.rstrip())
        now = time.monotonic()
        if force or (now - self._last_log_emit) >= self._LOG_THROTTLE:
            self.hub.log.emit("\n".join(self._log_buffer))
            self._log_buffer.clear()
            self._last_log_emit = now

    def _flush_log(self) -> None:
        if self._log_buffer:
            self.hub.log.emit("\n".join(self._log_buffer))
            self._log_buffer.clear()


# ---- Coordinator ------------------------------------------------------------


class TaskCoordinator(QObject):
    """Owns the pool; dispatches one task's worth of runnables at a time."""

    all_done = pyqtSignal(list)  # list[FileResult]

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.hub = SignalHub(self)
        self._queue = TaskQueue()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._results: list[FileResult] = []
        self._running = False
        self._cancelling = False

        # Per-task state (reset on each _dispatch_next_task)
        self._current_task: ConvertTask | None = None
        self._current_files: list[str] = []
        self._current_tokens: list[CancelToken] = []
        self._expected_files = 0
        self._done_count = 0
        self._in_flight = 0
        self._next_file_index = 0
        self._max_workers = 1
        self._start_time = 0.0
        self._stop_dispatch = False          # soft-stop flag
        self._plan: OutputPlan | None = None

        # Shared reservation set for the concurrent fallback path
        self._path_reserve_lock = threading.Lock()
        self._reserved_output_paths: set[str] = set()

        self.hub.file_done.connect(self._on_file_done)

    # ---- public API ---------------------------------------------

    @property
    def queue(self) -> TaskQueue:
        return self._queue

    @property
    def running(self) -> bool:
        return self._running

    @property
    def current_token(self) -> CancelToken | None:
        """The token of the oldest still-running runnable, for UX display."""
        for tok in self._current_tokens:
            if not tok.cancelled and tok.state.value in ("running", "paused"):
                return tok
        return None

    def set_concurrency(self, n: int) -> None:
        self._pool.setMaxThreadCount(max(1, n))

    def attach_plan(self, plan: OutputPlan | None) -> None:
        """Pre-computed output plan for the *next* dequeued task."""
        self._plan = plan

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._cancelling = False
        self._results.clear()
        self._done_count = 0
        self._in_flight = 0
        self._stop_dispatch = False
        self._reserved_output_paths.clear()
        self._current_tokens.clear()
        self._start_time = time.monotonic()
        self._dispatch_next_task()

    def cancel_all(self) -> None:
        """Stop everything: kill all in-flight ffmpeg + drop every pending task."""
        self._cancelling = True
        self._stop_dispatch = True
        for tok in list(self._current_tokens):
            tok.cancel()
        self._pool.clear()
        # Force in_flight to converge: clear() drops runnables that never
        # called run(), so their tokens never reached cancel() and never
        # emit file_done. We have to account for them manually.
        missing = self._in_flight - self._count_active_tokens()
        for _ in range(max(0, missing)):
            self.hub.file_done.emit(FileResult("", "", FileStatus.CANCELLED, "已取消"))
        self._queue.clear()

    def pause(self) -> None:
        """Suspend all in-flight runnables."""
        for tok in self._current_tokens:
            tok.pause()

    def resume(self) -> None:
        for tok in self._current_tokens:
            tok.resume()

    def skip_current(self) -> None:
        """Cancel every in-flight runnable; coordinator continues with remaining."""
        for tok in list(self._current_tokens):
            tok.cancel()

    # ---- internal: dispatch -------------------------------------

    def _dispatch_next_task(self) -> None:
        """Called from the main thread when the current task finishes."""
        if self._cancelling:
            self._finalise()
            return

        task = self._queue.dequeue()
        if task is None:
            self._finalise()
            return

        self._current_task = task
        if task.kind == TaskKind.BURN:
            self._dispatch_burn(task)
        elif task.merge_av:
            self._dispatch_merge(task)
        else:
            self._dispatch_batch(task)

    def _dispatch_batch(self, task: ConvertTask) -> None:
        files = task.files
        if not files:
            self.hub.error.emit("没有文件可转换。")
            QTimer.singleShot(0, self._dispatch_next_task)
            return

        self._expected_files = len(files)
        self._done_count = 0
        self._in_flight = 0
        self._current_files = list(files)
        self._current_tokens = []
        self._next_file_index = 0

        concurrency_mode = getattr(task, "_concurrency_mode", "auto")
        n = resolve_concurrency(
            concurrency_mode, task.use_hw_accel,
            task.kind == TaskKind.BURN,
        )
        self._pool.setMaxThreadCount(n)
        self._max_workers = n

        label = f"目标格式 {task.target_format}"
        self.hub.log.emit(f"开始批量转换 · {label} · 共 {len(files)} 个文件 · 并发 {n} 路")
        self.hub.execution_event.emit(ExecutionEvent(
            type=EventType.QUEUED.value, total=len(files), message=label,
        ))
        self._dispatch_more()

    def _dispatch_more(self) -> None:
        if self._current_task is None:
            return
        task = self._current_task
        while (
            self._in_flight < self._max_workers
            and self._next_file_index < self._expected_files
            and self._running
            and not self._stop_dispatch
        ):
            src = self._current_files[self._next_file_index]
            idx = self._next_file_index + 1
            self._next_file_index += 1
            self._in_flight += 1

            token = CancelToken()
            self._current_tokens.append(token)

            planned = self._plan.get(src) if self._plan is not None else None
            runnable = SingleFileRunnable(
                src, task, idx, self._expected_files,
                self.hub, token, self._start_time,
                self._reserve_output_atomic, planned=planned,
            )
            self._pool.start(runnable)

    def _dispatch_burn(self, task: ConvertTask) -> None:
        burn = task.burn
        if burn is None:
            self.hub.error.emit("字幕烧录参数缺失。")
            QTimer.singleShot(0, self._dispatch_next_task)
            return
        self._expected_files = 1
        self._done_count = 0
        self._in_flight = 1
        self._pool.setMaxThreadCount(1)

        token = CancelToken()
        self._current_tokens = [token]
        runnable = BurnRunnable(task, self.hub, token, self._reserve_output_atomic)
        self._pool.start(runnable)

    def _dispatch_merge(self, task: ConvertTask) -> None:
        self._expected_files = 1
        self._done_count = 0
        self._in_flight = 1
        self._pool.setMaxThreadCount(1)

        token = CancelToken()
        self._current_tokens = [token]
        runnable = MergeRunnable(task, self.hub, token, self._reserve_output_atomic)
        self._pool.start(runnable)

    # ---- completion handlers ------------------------------------

    def _on_file_done(self, result: FileResult) -> None:
        self._results.append(result)
        self._done_count += 1
        if self._in_flight > 0:
            self._in_flight -= 1

        done_pct = int(self._done_count / max(1, self._expected_files) * 100)
        self.hub.overall_progress.emit(min(done_pct, 100))
        self.hub.execution_event.emit(ExecutionEvent(
            type=EventType.DONE.value,
            source=result.source, status=result.status.value,
            output=result.output, message=result.reason,
            progress=min(done_pct, 100),
            index=self._done_count, total=self._expected_files,
        ))

        elapsed = time.monotonic() - self._start_time
        if elapsed > 1.0 and self._done_count > 0:
            frac = self._done_count / max(1, self._expected_files)
            if frac > 0:
                remaining = (elapsed / frac) - elapsed
                self.hub.eta.emit(_format_eta(remaining))

        # Soft-stop policy: fail-stop drops pending tasks and stops dispatch,
        # but we let in-flight runnables finish naturally.
        if self._should_soft_stop(result):
            self._trigger_soft_stop(result)

        if not self._stop_dispatch and not self._cancelling:
            self._dispatch_more()

        task_finished = (
            self._done_count >= self._expected_files
            or (self._stop_dispatch and self._in_flight == 0)
        )
        if task_finished:
            # Hop to the Qt event loop so we don't stack-recurse into
            # _dispatch_next_task from within _on_file_done.
            QTimer.singleShot(0, self._dispatch_next_task)

    def _should_soft_stop(self, result: FileResult) -> bool:
        if self._stop_dispatch or self._cancelling:
            return False
        if self._current_task is None:
            return False
        if self._current_task.continue_on_failure:
            return False
        return result.status == FileStatus.FAILED

    def _trigger_soft_stop(self, failing: FileResult) -> None:
        self._stop_dispatch = True
        dropped = self._queue.clear_pending()
        msg = (
            f"失败策略=停止: {os.path.basename(failing.source) or '任务'} 失败，"
            f"已停止派发（丢弃 {dropped} 个排队任务，{self._in_flight} 个仍在收尾）"
        )
        self.hub.log.emit(f"[系统] {msg}")
        self.hub.execution_event.emit(ExecutionEvent(
            type=EventType.SOFT_STOP.value,
            message=msg, source=failing.source,
        ))

    def _finalise(self) -> None:
        self._running = False
        self._cancelling = False
        self._current_task = None
        self._current_tokens = []
        self._plan = None
        self.hub.execution_event.emit(ExecutionEvent(
            type=EventType.ALL_DONE.value,
            total=len(self._results),
        ))
        self.all_done.emit(list(self._results))

    def _count_active_tokens(self) -> int:
        return sum(
            1 for t in self._current_tokens
            if t.state.value in ("running", "paused", "cancelling")
        )

    # ---- concurrent path reservation ----------------------------

    def _reserve_output_atomic(
        self, target: str, policy: ConflictPolicy,
    ) -> tuple[str, str]:
        """Fallback for files missing from the plan (e.g. retries).

        Goes through the shared reservation set so concurrent runnables
        don't race into the same ``_N`` suffix.
        """
        with self._path_reserve_lock:
            return reserve_output_path(target, policy, self._reserved_output_paths)


# ---- Burn / merge single-shot runnables -------------------------------------


class BurnRunnable(QRunnable):
    """Subtitle burn-in. Never concurrent (coordinator forces n=1)."""

    def __init__(
        self, task: ConvertTask, hub: SignalHub, token: CancelToken,
        reserve: Callable[[str, ConflictPolicy], tuple[str, str]],
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.task = task
        self.hub = hub
        self.cancel = token
        self._spec = spec_for(task.quality)
        self._reserve = reserve

    def run(self) -> None:
        t0 = time.monotonic()
        task = self.task
        burn = task.burn
        if burn is None:
            self.hub.file_done.emit(FileResult("", "", FileStatus.FAILED, "参数缺失", time.monotonic() - t0))
            return

        self.hub.file_started.emit(1, 1, os.path.basename(burn.video_path))

        if not os.path.exists(burn.video_path):
            self.hub.file_done.emit(FileResult(
                burn.video_path, "", FileStatus.FAILED,
                f"视频文件不存在: {burn.video_path}",
                time.monotonic() - t0,
            ))
            return
        if not os.path.exists(burn.subtitle_path):
            self.hub.file_done.emit(FileResult(
                burn.subtitle_path, "", FileStatus.FAILED,
                f"字幕文件不存在: {burn.subtitle_path}",
                time.monotonic() - t0,
            ))
            return

        out_dir = task.output_dir or os.path.dirname(burn.video_path)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            self.hub.file_done.emit(FileResult(
                burn.video_path, "", FileStatus.FAILED,
                f"创建输出目录失败: {exc}", time.monotonic() - t0,
            ))
            return
        base = os.path.splitext(os.path.basename(burn.video_path))[0]
        candidate = os.path.join(out_dir, f"{base}_burned.{burn.output_format}")

        out_path, action = self._reserve(candidate, task.conflict_policy)
        if action == "skip":
            self.hub.file_done.emit(FileResult(
                burn.video_path, out_path, FileStatus.SKIPPED,
                "输出已存在，按策略跳过", time.monotonic() - t0,
            ))
            return

        burn_style = task.burn_style or DEFAULT_BURN_STYLE_OBJ
        force_style = burn_style.to_force_style()

        try:
            with inject_burn_style(burn.subtitle_path) as styled:
                cmd = build_burn_subtitle_cmd(
                    video_path=burn.video_path,
                    styled_sub_path=styled.path,
                    output_path=out_path,
                    hardcode=burn.hardcode,
                    use_hw=task.use_hw_accel,
                    force_style=force_style,
                    spec=self._spec,
                )
                duration = get_media_duration(burn.video_path) or 1.0
                result = run_with_progress(
                    cmd, duration,
                    on_progress=lambda p: self.hub.file_progress.emit(p),
                    on_time=self.hub.file_time.emit,
                    on_log=lambda line: self.hub.log.emit(line.rstrip()),
                    cancel=self.cancel,
                )
        except RuntimeError as exc:
            self.hub.file_done.emit(FileResult(
                burn.video_path, out_path, FileStatus.FAILED,
                f"字幕样式处理失败: {exc}", time.monotonic() - t0,
            ))
            return

        elapsed = time.monotonic() - t0
        if result.cancelled:
            self.hub.file_done.emit(FileResult(
                burn.video_path, out_path, FileStatus.CANCELLED, elapsed_s=elapsed,
            ))
        elif not result.ok:
            self.hub.file_done.emit(FileResult(
                burn.video_path, out_path, FileStatus.FAILED,
                result.stderr_tail.strip(), elapsed,
            ))
        else:
            self.hub.file_done.emit(FileResult(
                burn.video_path, out_path, FileStatus.SUCCESS, elapsed_s=elapsed,
            ))

        self.hub.overall_progress.emit(100)


class MergeRunnable(QRunnable):
    """Audio+video mux. Never concurrent."""

    def __init__(
        self, task: ConvertTask, hub: SignalHub, token: CancelToken,
        reserve: Callable[[str, ConflictPolicy], tuple[str, str]],
    ) -> None:
        super().__init__()
        self.setAutoDelete(True)
        self.task = task
        self.hub = hub
        self.cancel = token
        self._spec = spec_for(task.quality)
        self._reserve = reserve

    def run(self) -> None:
        task = self.task
        t0 = time.monotonic()

        audio = next((f for f in task.files if is_audio_file(f)), None)
        video = next((f for f in task.files if is_video_file(f)), None)
        if audio is None or video is None:
            self.hub.file_done.emit(FileResult(
                "", "", FileStatus.FAILED, "需要至少一个音频和一个视频文件",
                time.monotonic() - t0,
            ))
            return

        self.hub.file_started.emit(1, 1, "merged_output.mp4")

        out_dir = task.output_dir or os.path.dirname(audio)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            self.hub.file_done.emit(FileResult(
                video, "", FileStatus.FAILED,
                f"创建输出目录失败: {exc}", time.monotonic() - t0,
            ))
            return
        candidate = os.path.join(out_dir, "merged_output.mp4")

        out_path, action = self._reserve(candidate, task.conflict_policy)
        if action == "skip":
            self.hub.file_done.emit(FileResult(
                video, out_path, FileStatus.SKIPPED,
                "输出已存在，按策略跳过", time.monotonic() - t0,
            ))
            return

        cmd = build_merge_av_cmd(audio, video, out_path, use_hw=task.use_hw_accel, spec=self._spec)
        duration = get_media_duration(video) or 1.0
        result = run_with_progress(
            cmd, duration,
            on_progress=lambda p: self.hub.file_progress.emit(p),
            on_time=self.hub.file_time.emit,
            on_log=lambda line: self.hub.log.emit(line.rstrip()),
            cancel=self.cancel,
        )

        elapsed = time.monotonic() - t0
        if result.cancelled:
            self.hub.file_done.emit(FileResult(
                video, out_path, FileStatus.CANCELLED, elapsed_s=elapsed,
            ))
        elif not result.ok:
            self.hub.file_done.emit(FileResult(
                video, out_path, FileStatus.FAILED,
                result.stderr_tail.strip(), elapsed,
            ))
        else:
            self.hub.file_done.emit(FileResult(
                video, out_path, FileStatus.SUCCESS, elapsed_s=elapsed,
            ))

        self.hub.overall_progress.emit(100)
