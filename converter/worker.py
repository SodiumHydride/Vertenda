# -*- coding: utf-8 -*-
"""Qt worker that dispatches conversion tasks without owning business logic."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from PyQt5.QtCore import QThread, pyqtSignal

from .constants import (
    AUDIO_EXTS,
    DEFAULT_BURN_STYLE,
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
from .ffmpeg.quality import QualityPreset, QualitySpec, spec_for
from .ffmpeg.runner import CancelToken, run_blocking, run_with_progress
from .fs import ConflictPolicy
from .subtitle.converters import (
    SubtitleConversionError,
    lrc_to_srt,
    lrc_to_vtt,
    srt_to_lrc,
    vtt_to_lrc,
)
from .subtitle.styling import inject_burn_style
from .subtitle.styling_config import BurnStyle


class TaskKind(str, Enum):
    AUDIO = "audio"
    VIDEO = "video"
    SUBTITLE = "subtitle"
    BURN = "burn"


@dataclass
class BurnOptions:
    video_path: str
    subtitle_path: str
    hardcode: bool = True
    output_format: str = "mp4"


@dataclass
class ConvertTask:
    kind: TaskKind
    files: list[str] = field(default_factory=list)
    target_format: str = ""
    output_dir: str = ""
    merge_av: bool = False
    use_hw_accel: bool = False
    quality: QualityPreset = QualityPreset.BALANCED
    burn: Optional[BurnOptions] = None
    # ---- Phase 0+ additions ----
    conflict_policy: ConflictPolicy = ConflictPolicy.ASK
    filename_template: str = "{base}"
    mirror_subdirs: bool = False
    continue_on_failure: bool = True
    source_root: str = ""
    preset_name: str = ""
    # How many concurrent runnables to use ("auto" or "1".."8").
    # Read by TaskCoordinator._dispatch_batch via getattr(), so older
    # callers that don't set it still work.
    _concurrency_mode: str = "auto"
    # Filters (Phase 2)
    trim_start: Optional[float] = None
    trim_end: Optional[float] = None
    scale_preset: Optional[str] = None
    volume_normalize: bool = False
    two_pass: bool = False
    burn_style: Optional[BurnStyle] = None
    subtitle_shift_s: float = 0.0


def _format_eta(seconds: float) -> str:
    """Human-friendly duration: '42s' / '3m12s' / '1h04m'."""
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


class ConvertWorker(QThread):
    """Non-blocking worker: all ffmpeg runs happen off the Qt main thread."""

    progress_signal = pyqtSignal(int)           # 0..100 overall
    file_progress_signal = pyqtSignal(int)      # 0..100 within current file
    current_file_signal = pyqtSignal(int, int, str)  # (index, total, filename)
    log_signal = pyqtSignal(str)
    time_signal = pyqtSignal(str)               # HH:MM:SS position in current file
    eta_signal = pyqtSignal(str)                # rough time remaining
    error_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)          # True on success

    _LOG_THROTTLE_INTERVAL = 0.15  # seconds

    def __init__(self, task: ConvertTask, parent=None) -> None:
        super().__init__(parent)
        self.task = task
        self._spec: QualitySpec = spec_for(task.quality)
        self._cancel = CancelToken()
        self._last_log_emit = 0.0
        self._log_buffer: list[str] = []
        self._start_time = 0.0

    # ---- public API ----------------------------------------------------
    def request_cancel(self) -> None:
        self._cancel.cancel()

    # ---- internal helpers ---------------------------------------------
    def _emit_log(self, msg: str, *, force: bool = False) -> None:
        self._log_buffer.append(msg.rstrip())
        now = time.monotonic()
        if force or (now - self._last_log_emit) >= self._LOG_THROTTLE_INTERVAL:
            self.log_signal.emit("\n".join(self._log_buffer))
            self._log_buffer.clear()
            self._last_log_emit = now

    def _flush_log(self) -> None:
        if self._log_buffer:
            self.log_signal.emit("\n".join(self._log_buffer))
            self._log_buffer.clear()

    def _ensure_output_dir(self, path: str) -> bool:
        try:
            os.makedirs(path, exist_ok=True)
            return True
        except OSError as exc:
            self._emit_log(f"[失败] 无法创建输出目录 {path}: {exc}", force=True)
            return False

    def _emit_overall(self, index: int, total: int, inner_percent: int) -> None:
        """Fold per-file percent into an overall progress across the batch."""
        if total <= 0:
            self.progress_signal.emit(inner_percent)
            return
        done_fraction = (index - 1 + inner_percent / 100.0) / total
        self.progress_signal.emit(int(done_fraction * 100))

    def _emit_eta(self, index: int, total: int, inner_percent: int) -> None:
        if total <= 0 or self._start_time <= 0:
            return
        elapsed = time.monotonic() - self._start_time
        if elapsed < 1.0:
            return
        fraction = (index - 1 + inner_percent / 100.0) / total
        if fraction <= 0:
            return
        total_estimate = elapsed / fraction
        remaining = total_estimate - elapsed
        self.eta_signal.emit(_format_eta(remaining))

    # ---- QThread entrypoint -------------------------------------------
    def run(self) -> None:
        self._start_time = time.monotonic()
        try:
            success = self._dispatch()
        except Exception as exc:  # Unexpected error -> surface loudly.
            self._flush_log()
            self.error_signal.emit(f"内部错误: {exc}")
            self.finished_signal.emit(False)
            return

        self._flush_log()
        self.finished_signal.emit(success)

    def _dispatch(self) -> bool:
        task = self.task
        if task.kind == TaskKind.BURN:
            return self._run_burn()
        if task.kind == TaskKind.SUBTITLE:
            return self._run_subtitle_batch()
        if task.merge_av:
            return self._run_merge()
        return self._run_media_batch()

    # ---- task implementations -----------------------------------------
    def _run_merge(self) -> bool:
        task = self.task
        audio = next((f for f in task.files if is_audio_file(f)), None)
        video = next((f for f in task.files if is_video_file(f)), None)
        if audio is None or video is None:
            self.error_signal.emit("合并失败: 需要至少一个音频文件和一个视频文件。")
            return False
        for p in (audio, video):
            if not os.path.exists(p):
                self.error_signal.emit(f"文件不存在: {p}")
                return False

        out_dir = task.output_dir or os.path.dirname(audio)
        if not self._ensure_output_dir(out_dir):
            return False
        out_path = os.path.join(out_dir, "merged_output.mp4")

        self.current_file_signal.emit(1, 1, os.path.basename(out_path))
        self._emit_log(
            f"开始合并:\n  视频: {video}\n  音频: {audio}\n  输出: {out_path}",
            force=True,
        )

        cmd = build_merge_av_cmd(audio, video, out_path, use_hw=task.use_hw_accel, spec=self._spec)
        duration = get_media_duration(video) or 1.0
        result = run_with_progress(
            cmd, duration,
            on_progress=lambda p: (self.file_progress_signal.emit(p),
                                    self._emit_overall(1, 1, p),
                                    self._emit_eta(1, 1, p)),
            on_time=self.time_signal.emit,
            on_log=lambda line: self._emit_log(line),
            cancel=self._cancel,
        )
        if result.cancelled:
            self._emit_log("[取消] 合并任务已取消。", force=True)
            return False
        if not result.ok:
            self.error_signal.emit(f"合并失败:\n{result.stderr_tail}")
            return False

        self._emit_log(f"[OK] 合并完成: {out_path}", force=True)
        self.progress_signal.emit(100)
        return True

    def _run_burn(self) -> bool:
        task = self.task
        burn = task.burn
        if burn is None:
            self.error_signal.emit("字幕烧录参数缺失。")
            return False
        if not os.path.exists(burn.video_path):
            self.error_signal.emit(f"视频文件不存在: {burn.video_path}")
            return False
        if not os.path.exists(burn.subtitle_path):
            self.error_signal.emit(f"字幕文件不存在: {burn.subtitle_path}")
            return False

        out_dir = task.output_dir or os.path.dirname(burn.video_path)
        if not self._ensure_output_dir(out_dir):
            return False
        base = os.path.splitext(os.path.basename(burn.video_path))[0]
        out_path = os.path.join(out_dir, f"{base}_burned.{burn.output_format}")

        self.current_file_signal.emit(1, 1, os.path.basename(out_path))
        self._emit_log(
            f"开始字幕烧录:\n  视频: {burn.video_path}\n  字幕: {burn.subtitle_path}\n"
            f"  模式: {'硬编码' if burn.hardcode else '软封装'}\n  输出: {out_path}",
            force=True,
        )

        try:
            with inject_burn_style(burn.subtitle_path) as styled:
                cmd = build_burn_subtitle_cmd(
                    video_path=burn.video_path,
                    styled_sub_path=styled.path,
                    output_path=out_path,
                    hardcode=burn.hardcode,
                    use_hw=task.use_hw_accel,
                    force_style=DEFAULT_BURN_STYLE,
                    spec=self._spec,
                )
                duration = get_media_duration(burn.video_path) or 1.0
                result = run_with_progress(
                    cmd, duration,
                    on_progress=lambda p: (self.file_progress_signal.emit(p),
                                            self._emit_overall(1, 1, p),
                                            self._emit_eta(1, 1, p)),
                    on_time=self.time_signal.emit,
                    on_log=lambda line: self._emit_log(line),
                    cancel=self._cancel,
                )
        except RuntimeError as exc:
            self.error_signal.emit(f"字幕样式处理失败: {exc}")
            return False

        if result.cancelled:
            self._emit_log("[取消] 烧录任务已取消。", force=True)
            return False
        if not result.ok:
            self.error_signal.emit(f"烧录失败:\n{result.stderr_tail}")
            return False

        self._emit_log(f"[OK] 烧录完成: {out_path}", force=True)
        self.progress_signal.emit(100)
        return True

    def _run_media_batch(self) -> bool:
        task = self.task
        total = len(task.files)
        if total == 0:
            self.error_signal.emit("没有文件可转换。")
            return False

        target_ext_dot = "." + task.target_format.lower()
        extract_audio = target_ext_dot in AUDIO_EXTS and task.kind == TaskKind.VIDEO

        label = "提取音频" if extract_audio else f"目标格式 {task.target_format}"
        self._emit_log(f"开始批量转换 · {label} · 共 {total} 个文件", force=True)

        any_failed = False
        for i, src in enumerate(task.files, start=1):
            if self._cancel.cancelled:
                self._emit_log("用户取消了任务。", force=True)
                return False

            self.current_file_signal.emit(i, total, os.path.basename(src))

            if not os.path.exists(src):
                self._emit_log(f"[跳过] 文件不存在: {src}")
                any_failed = True
                continue
            if is_lrc_file(src):
                self._emit_log(f"[跳过] LRC 不能转换为 {task.target_format}: {src}")
                continue
            if extract_audio and not is_video_file(src):
                self._emit_log(f"[跳过] 提取音频任务只接受视频文件: {src}")
                any_failed = True
                continue

            base = os.path.splitext(os.path.basename(src))[0]
            out_dir = task.output_dir or os.path.dirname(src)
            if not self._ensure_output_dir(out_dir):
                any_failed = True
                continue
            out_path = os.path.join(out_dir, f"{base}.{task.target_format}")

            if extract_audio:
                cmd = build_extract_audio_cmd(src, out_path, spec=self._spec)
            else:
                cmd = build_convert_cmd(src, out_path, use_hw=task.use_hw_accel, spec=self._spec)

            duration = get_media_duration(src) or 1.0
            result = run_with_progress(
                cmd, duration,
                on_progress=lambda p, idx=i: (self.file_progress_signal.emit(p),
                                                self._emit_overall(idx, total, p),
                                                self._emit_eta(idx, total, p)),
                on_time=self.time_signal.emit,
                on_log=lambda line: self._emit_log(line),
                cancel=self._cancel,
            )
            if result.cancelled:
                self._emit_log("[取消] 批量转换已取消。", force=True)
                return False
            if result.ok:
                self._emit_log(f"[OK] {src} -> {out_path}", force=True)
            else:
                self._emit_log(f"[失败] {src}\n  {result.stderr_tail.strip()}", force=True)
                any_failed = True

            self._emit_overall(i, total, 100)

        self._emit_log("全部处理完成。", force=True)
        self.progress_signal.emit(100)
        return not any_failed

    def _run_subtitle_batch(self) -> bool:
        task = self.task
        total = len(task.files)
        if total == 0:
            self.error_signal.emit("没有字幕文件可转换。")
            return False

        target = task.target_format.lower()
        self._emit_log(f"开始字幕转换 · 目标格式 {target.upper()} · 共 {total} 个文件", force=True)

        any_failed = False
        for i, src in enumerate(task.files, start=1):
            if self._cancel.cancelled:
                self._emit_log("用户取消了任务。", force=True)
                return False

            self.current_file_signal.emit(i, total, os.path.basename(src))
            if not os.path.exists(src):
                self._emit_log(f"[跳过] 文件不存在: {src}")
                any_failed = True
                continue
            if not is_subtitle_file(src):
                self._emit_log(f"[跳过] 非字幕文件: {src}")
                continue

            src_ext = ext_of(src)
            if src_ext == f".{target}":
                self._emit_log(f"[跳过] 源文件已是 {target}: {src}")
                continue

            base = os.path.splitext(os.path.basename(src))[0]
            out_dir = task.output_dir or os.path.dirname(src)
            if not self._ensure_output_dir(out_dir):
                any_failed = True
                continue
            out_path = os.path.join(out_dir, f"{base}.{target}")

            try:
                self._convert_subtitle(src, src_ext, target, out_path, out_dir, base)
                self._emit_log(f"[OK] {src} -> {out_path}")
            except (SubtitleConversionError, RuntimeError, OSError) as exc:
                self._emit_log(f"[失败] {src}: {exc}")
                any_failed = True

            self._emit_overall(i, total, 100)

        self._emit_log("全部字幕处理完成。", force=True)
        self.progress_signal.emit(100)
        return not any_failed

    def _convert_subtitle(self, src: str, src_ext: str, target: str, out_path: str,
                           out_dir: str, base: str) -> None:
        """Dispatch one subtitle conversion.

        Pure-Python paths for LRC conversions, ffmpeg for the rest.
        Raises on failure.
        """
        if target == "lrc":
            if src_ext == ".srt":
                srt_to_lrc(src, out_path)
            elif src_ext == ".vtt":
                vtt_to_lrc(src, out_path)
            elif src_ext in (".ass", ".ssa"):
                tmp_srt = os.path.join(out_dir, f"{base}.__tmp__.srt")
                cmd = build_subtitle_transcode_cmd(src, tmp_srt)
                result = run_blocking(cmd)
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

        if target == "srt":
            if src_ext == ".lrc":
                lrc_to_srt(src, out_path)
            elif src_ext in (".vtt", ".ass", ".ssa"):
                result = run_blocking(build_subtitle_transcode_cmd(src, out_path))
                if not result.ok:
                    raise RuntimeError(result.stderr_tail.strip())
            else:
                raise RuntimeError(f"不支持从 {src_ext} 转 SRT")
            return

        if target == "vtt":
            if src_ext == ".lrc":
                lrc_to_vtt(src, out_path)
            elif src_ext in (".srt", ".ass", ".ssa"):
                result = run_blocking(build_subtitle_transcode_cmd(src, out_path))
                if not result.ok:
                    raise RuntimeError(result.stderr_tail.strip())
            else:
                raise RuntimeError(f"不支持从 {src_ext} 转 VTT")
            return

        if target in ("ass", "ssa"):
            if src_ext == ".lrc":
                raise RuntimeError("LRC 无法直接转 ASS/SSA, 请先转成 SRT 或 VTT")
            if src_ext in (".srt", ".vtt", ".ass", ".ssa"):
                result = run_blocking(build_subtitle_transcode_cmd(src, out_path))
                if not result.ok:
                    raise RuntimeError(result.stderr_tail.strip())
                return
            raise RuntimeError(f"不支持从 {src_ext} 转 {target.upper()}")

        raise RuntimeError(f"未知的目标格式: {target}")
