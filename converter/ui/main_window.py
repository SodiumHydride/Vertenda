# -*- coding: utf-8 -*-
"""Main window: assembles tabs, routes actions to ConvertWorker."""

from __future__ import annotations

import os
import subprocess
import sys

from PyQt5.QtCore import QDir, QSettings, Qt
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..constants import (
    AUDIO_EXTS,
    SUBTITLE_EXTS,
    VIDEO_EXTS,
    SettingsKey,
    app_runtime_dir,
    is_audio_file,
    is_subtitle_file,
    is_video_file,
    resource_path,
)
from ..ffmpeg.quality import QualityPreset, parse as parse_preset
from ..worker import BurnOptions, ConvertTask, ConvertWorker, TaskKind
from .file_list import CustomAction
from .settings_dialog import SettingsDialog
from .tabs import (
    build_audio_tab,
    build_burn_tab,
    build_subtitle_tab,
    build_video_tab,
    format_combo_current_key,
    format_combo_set_key,
)
from .theme import build_stylesheet, overlay_color_for


def _tab_kind_label(index: int) -> str:
    return {0: "音频", 1: "视频", 2: "字幕", 3: "字幕烧录"}.get(index, "未知")


class ConverterMainWindow(QMainWindow):
    _DEFAULT_WIDTH = 1280
    _DEFAULT_HEIGHT = 840

    # Tab indices (kept here for a single place to swap them).
    TAB_AUDIO = 0
    TAB_VIDEO = 1
    TAB_SUBTITLE = 2
    TAB_BURN = 3

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("盐酸转换器 · Kurisu Edition")
        self.resize(self._DEFAULT_WIDTH, self._DEFAULT_HEIGHT)
        self.setMinimumSize(1000, 680)

        icon_path = resource_path("resources/favicon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._setup_settings()
        self._worker: ConvertWorker | None = None
        self._bg_pixmap: QPixmap | None = None
        self._overlay_color: tuple[int, int, int] = (0, 0, 0)
        self._overlay_alpha: int = 0  # 0..255

        self._build_ui()
        self._wire_signals()
        self._install_inter_tab_actions()
        self._apply_settings()
        self._restore_last_selections()

    # ---- Settings bootstrap -------------------------------------------
    def _setup_settings(self) -> None:
        runtime_dir = app_runtime_dir()
        self._config_path = os.path.join(runtime_dir, "converter_config.ini")
        self.settings = QSettings(self._config_path, QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False)

        if not os.path.exists(self._config_path):
            defaults = {
                SettingsKey.BG_PATH: resource_path("resources/default_bg.png"),
                SettingsKey.BG_ALPHA: 70,
                SettingsKey.OVERLAY_STRENGTH: 40,
                SettingsKey.THEME_MODE: "Dark",
                SettingsKey.FONT_SIZE: 11,
                SettingsKey.USE_HW_ACCEL: False,
                SettingsKey.QUALITY_PRESET: "balanced",
                SettingsKey.OUTPUT_PATH: os.path.join(runtime_dir, "output"),
            }
            for k, v in defaults.items():
                self.settings.setValue(k, v)

    # ---- UI construction ----------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(14, 12, 14, 10)
        root_layout.setSpacing(10)

        root_layout.addLayout(self._build_top_bar())

        self.tabs = QTabWidget(self)
        self.audio_handles = build_audio_tab()
        self.video_handles = build_video_tab()
        self.subtitle_handles = build_subtitle_tab()
        self.burn_handles = build_burn_tab()
        self.tabs.addTab(self.audio_handles.widget, "音频转换")
        self.tabs.addTab(self.video_handles.widget, "视频转换")
        self.tabs.addTab(self.subtitle_handles.widget, "字幕转换")
        self.tabs.addTab(self.burn_handles.widget, "字幕烧录")
        root_layout.addWidget(self.tabs, stretch=3)

        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setPlaceholderText("日志输出...")
        self.log_display.setMaximumBlockCount(2000)
        root_layout.addWidget(self.log_display, stretch=2)

        progress_block = QVBoxLayout()
        progress_block.setSpacing(4)

        status_row = QHBoxLayout()
        self.current_file_label = QLabel("就绪")
        self.current_file_label.setObjectName("HintLabel")
        self.current_file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.eta_label = QLabel("")
        self.eta_label.setObjectName("HintLabel")
        self.eta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_row.addWidget(self.current_file_label, 1)
        status_row.addWidget(self.eta_label)
        progress_block.addLayout(status_row)

        self.file_progress = QProgressBar()
        self.file_progress.setObjectName("FileProgress")
        self.file_progress.setRange(0, 100)
        self.file_progress.setValue(0)
        self.file_progress.setTextVisible(False)
        progress_block.addWidget(self.file_progress)

        main_progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.time_label = QLabel("00:00:00")
        self.time_label.setFixedWidth(72)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet("font-family: 'Menlo', monospace; font-size: 11px;")
        main_progress_row.addWidget(self.progress_bar)
        main_progress_row.addWidget(self.time_label)
        progress_block.addLayout(main_progress_row)

        root_layout.addLayout(progress_block)

        action_row = QHBoxLayout()
        self.btn_start = QPushButton("开始转换")
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("DangerButton")
        self.btn_cancel.setEnabled(False)
        self.btn_open_output = QPushButton("打开输出目录")
        self.btn_close = QPushButton("关闭")
        action_row.addWidget(self.btn_start)
        action_row.addWidget(self.btn_cancel)
        action_row.addStretch()
        action_row.addWidget(self.btn_open_output)
        action_row.addWidget(self.btn_close)
        root_layout.addLayout(action_row)

        self.status_bar = QStatusBar(self)
        self.status_bar.setSizeGripEnabled(False)
        self.status_bar.showMessage("就绪 · 拖拽文件到列表即可开始")
        signature = QLabel("染")
        signature.setStyleSheet("color: rgba(150, 150, 170, 180); font-size: 11px; padding-right: 8px;")
        self.status_bar.addPermanentWidget(signature)
        self.setStatusBar(self.status_bar)

    def _build_top_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(8)
        title = QLabel("盐酸转换器")
        title.setObjectName("TitleLabel")
        bar.addWidget(title)
        subtitle = QLabel("音视频 · 字幕 · 烧录")
        subtitle.setObjectName("SubtitleLabel")
        bar.addWidget(subtitle)
        bar.addStretch()

        self.quality_badge = QLabel("")
        self.quality_badge.setObjectName("HintLabel")
        bar.addWidget(self.quality_badge)

        self.btn_settings = QToolButton()
        self.btn_settings.setText("设置")
        bar.addWidget(self.btn_settings)
        return bar

    # ---- Signal wiring -------------------------------------------------
    def _wire_signals(self) -> None:
        self.btn_settings.clicked.connect(self._open_settings)

        # Audio tab
        self.audio_handles.btn_add.clicked.connect(
            lambda: self._add_files(self.audio_handles.file_list, "音频", AUDIO_EXTS)
        )
        self.audio_handles.btn_add_dir.clicked.connect(
            lambda: self._add_directory(self.audio_handles.file_list, AUDIO_EXTS)
        )
        self.audio_handles.btn_remove.clicked.connect(self.audio_handles.file_list.remove_selected)
        self.audio_handles.btn_clear.clicked.connect(self.audio_handles.file_list.clear_all)

        # Video tab
        self.video_handles.btn_add.clicked.connect(
            lambda: self._add_files(self.video_handles.file_list, "视频", VIDEO_EXTS)
        )
        self.video_handles.btn_add_dir.clicked.connect(
            lambda: self._add_directory(self.video_handles.file_list, VIDEO_EXTS)
        )
        self.video_handles.btn_remove.clicked.connect(self.video_handles.file_list.remove_selected)
        self.video_handles.btn_clear.clicked.connect(self.video_handles.file_list.clear_all)

        # Subtitle tab
        self.subtitle_handles.btn_add.clicked.connect(
            lambda: self._add_files(self.subtitle_handles.file_list, "字幕", SUBTITLE_EXTS)
        )
        self.subtitle_handles.btn_add_dir.clicked.connect(
            lambda: self._add_directory(self.subtitle_handles.file_list, SUBTITLE_EXTS)
        )
        self.subtitle_handles.btn_remove.clicked.connect(self.subtitle_handles.file_list.remove_selected)
        self.subtitle_handles.btn_clear.clicked.connect(self.subtitle_handles.file_list.clear_all)

        # Burn tab
        self.burn_handles.btn_add_video.clicked.connect(
            lambda: self._add_files(self.burn_handles.video_list, "视频", VIDEO_EXTS)
        )
        self.burn_handles.btn_add_subtitle.clicked.connect(
            lambda: self._add_files(self.burn_handles.subtitle_list, "字幕", SUBTITLE_EXTS)
        )
        self.burn_handles.btn_remove_video.clicked.connect(self.burn_handles.video_list.remove_selected)
        self.burn_handles.btn_remove_subtitle.clicked.connect(self.burn_handles.subtitle_list.remove_selected)
        self.burn_handles.mode_combo.currentTextChanged.connect(self._update_burn_hint)
        self._update_burn_hint(self.burn_handles.mode_combo.currentText())

        self.btn_start.clicked.connect(self._start_conversion)
        self.btn_cancel.clicked.connect(self._cancel_conversion)
        self.btn_open_output.clicked.connect(self._open_output_dir)
        self.btn_close.clicked.connect(self.close)

    def _install_inter_tab_actions(self) -> None:
        """Right-click a file -> 'send to another tab'. Keeps tabs coordinated."""
        self.video_handles.file_list.register_action(CustomAction(
            "发送到 字幕烧录 (视频)",
            handler=lambda paths: self._send_to(self.burn_handles.video_list, paths, "视频已加入烧录 Tab"),
            enabled=lambda paths: any(is_video_file(p) for p in paths),
        ))
        self.subtitle_handles.file_list.register_action(CustomAction(
            "发送到 字幕烧录 (字幕)",
            handler=lambda paths: self._send_to(self.burn_handles.subtitle_list, paths, "字幕已加入烧录 Tab"),
            enabled=lambda paths: any(is_subtitle_file(p) for p in paths),
        ))
        self.audio_handles.file_list.register_action(CustomAction(
            "发送到 视频转换 (合并音视频)",
            handler=lambda paths: self._send_to(self.video_handles.file_list, paths, "音频已加入视频 Tab"),
            enabled=lambda paths: any(is_audio_file(p) for p in paths),
        ))

    def _send_to(self, target_list, paths: list[str], message: str) -> None:
        added, dup = target_list.add_many(paths)
        if dup and not added:
            self.status_bar.showMessage("目标列表已存在所有选中文件。", 3000)
        elif dup:
            self.status_bar.showMessage(f"{message}（{added} 个新增，{dup} 个重复）", 4000)
        else:
            self.status_bar.showMessage(f"{message}（{added} 个）", 3000)

    # ---- Settings/application glue ------------------------------------
    def _apply_settings(self) -> None:
        s = self.settings
        self._bg_path = s.value(SettingsKey.BG_PATH, "", type=str)
        self._bg_alpha = s.value(SettingsKey.BG_ALPHA, 70, type=int)
        self._overlay_strength = s.value(SettingsKey.OVERLAY_STRENGTH, 40, type=int)
        self._theme_mode = s.value(SettingsKey.THEME_MODE, "Dark", type=str)
        self._font_size = s.value(SettingsKey.FONT_SIZE, 11, type=int)
        self._output_path = s.value(SettingsKey.OUTPUT_PATH, "", type=str) or os.path.join(app_runtime_dir(), "output")
        self._use_hw_accel = s.value(SettingsKey.USE_HW_ACCEL, False, type=bool)
        self._quality_preset = parse_preset(s.value(SettingsKey.QUALITY_PRESET, "balanced", type=str))

        font = QFont()
        font.setPointSize(self._font_size)
        QApplication.instance().setFont(font)
        self.setFont(font)

        QApplication.instance().setStyleSheet(build_stylesheet(self._theme_mode))
        self._overlay_color = overlay_color_for(self._theme_mode)
        self._overlay_alpha = int(self._overlay_strength / 100.0 * 255)
        self._load_background()
        self.quality_badge.setText(f"质量 · {self._quality_preset.display.split(' ·')[0]}")
        self.update()

    def _load_background(self) -> None:
        for candidate in (self._bg_path, resource_path("resources/default_bg.png")):
            if candidate and os.path.exists(candidate):
                pm = QPixmap(candidate)
                if not pm.isNull():
                    self._bg_pixmap = pm
                    return
        self._bg_pixmap = None

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        if self._bg_pixmap is not None:
            painter.setOpacity(max(0.0, min(1.0, self._bg_alpha / 100.0)))
            painter.drawPixmap(
                self.rect(),
                self._bg_pixmap.scaled(
                    self.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation,
                ),
            )
            painter.setOpacity(1.0)
        # Readability overlay: quiet the background just enough for panels to
        # read well, while still letting the image breathe.
        if self._overlay_alpha > 0:
            r, g, b = self._overlay_color
            painter.fillRect(self.rect(), QColor(r, g, b, self._overlay_alpha))
        painter.end()
        super().paintEvent(event)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self, self.settings)
        dlg.hw_accel_changed_signal.connect(self._on_hw_accel_changed)
        if dlg.exec_() == QDialog.Accepted:
            self._apply_settings()
            self.status_bar.showMessage("设置已更新", 3000)

    def _on_hw_accel_changed(self, use_hw: bool) -> None:
        self._use_hw_accel = use_hw

    # ---- File adding ---------------------------------------------------
    def _add_files(self, file_list, label: str, extensions: frozenset[str]) -> None:
        filter_str = "所有文件 (*);;" + label + " 文件 (" + " ".join(f"*{e}" for e in sorted(extensions)) + ")"
        files, _ = QFileDialog.getOpenFileNames(
            self, f"选择{label}文件", QDir.homePath(), filter_str
        )
        if not files:
            return
        added, dup = file_list.add_many(files)
        self._report_add_result(added, dup)

    def _add_directory(self, file_list, extensions: frozenset[str]) -> None:
        directory = QFileDialog.getExistingDirectory(self, "选择目录", QDir.homePath())
        if not directory:
            return
        added, dup = file_list.add_directory(directory, extensions=extensions, recursive=True)
        self._report_add_result(added, dup)

    def _report_add_result(self, added: int, dup: int) -> None:
        if added == 0 and dup == 0:
            self.status_bar.showMessage("未找到匹配的文件。", 4000)
            return
        if dup:
            self.status_bar.showMessage(
                f"已添加 {added} 个文件，跳过 {dup} 个重复项", 4000
            )
        else:
            self.status_bar.showMessage(f"已添加 {added} 个文件", 3000)

    # ---- Persistence: remember last selections ------------------------
    def _restore_last_selections(self) -> None:
        s = self.settings
        key = s.value(SettingsKey.LAST_AUDIO_FORMAT, "mp3", type=str)
        format_combo_set_key(self.audio_handles.format_combo, key)

        key = s.value(SettingsKey.LAST_VIDEO_FORMAT, "mp4", type=str)
        format_combo_set_key(self.video_handles.format_combo, key)

        key = s.value(SettingsKey.LAST_SUBTITLE_FORMAT, "srt", type=str)
        format_combo_set_key(self.subtitle_handles.format_combo, key)

        mode = s.value(SettingsKey.LAST_BURN_MODE, "硬编码", type=str)
        idx = self.burn_handles.mode_combo.findText(mode)
        if idx >= 0:
            self.burn_handles.mode_combo.setCurrentIndex(idx)

        out_fmt = s.value(SettingsKey.LAST_BURN_OUTPUT_FORMAT, "mkv", type=str)
        idx = self.burn_handles.output_format_combo.findText(out_fmt)
        if idx >= 0:
            self.burn_handles.output_format_combo.setCurrentIndex(idx)

    def _remember_selections(self) -> None:
        s = self.settings
        s.setValue(SettingsKey.LAST_AUDIO_FORMAT,
                    format_combo_current_key(self.audio_handles.format_combo))
        s.setValue(SettingsKey.LAST_VIDEO_FORMAT,
                    format_combo_current_key(self.video_handles.format_combo))
        s.setValue(SettingsKey.LAST_SUBTITLE_FORMAT,
                    format_combo_current_key(self.subtitle_handles.format_combo))
        s.setValue(SettingsKey.LAST_BURN_MODE,
                    self.burn_handles.mode_combo.currentText())
        s.setValue(SettingsKey.LAST_BURN_OUTPUT_FORMAT,
                    self.burn_handles.output_format_combo.currentText())

    # ---- Conversion dispatch ------------------------------------------
    def _start_conversion(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "提示", "当前有任务在进行，请先等待完成或取消。")
            return

        index = self.tabs.currentIndex()
        try:
            task = self._build_task(index)
        except ValueError as exc:
            QMessageBox.information(self, "提示", str(exc))
            return

        if not self._ensure_output_dir(task.output_dir):
            return

        if task.files:
            input_dirs = {os.path.dirname(f) for f in task.files}
            if os.path.abspath(task.output_dir) in {os.path.abspath(d) for d in input_dirs}:
                reply = QMessageBox.question(
                    self, "输出目录与源目录相同",
                    "输出目录与源文件所在目录相同，可能覆盖源文件。确认继续吗？\n"
                    "(建议在设置里挑一个独立的输出目录。)",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return

        self._remember_selections()

        self.log_display.clear()
        self.progress_bar.setValue(0)
        self.file_progress.setValue(0)
        self.time_label.setText("00:00:00")
        self.current_file_label.setText(f"准备中 · {_tab_kind_label(index)}")
        self.eta_label.setText("")

        self._worker = ConvertWorker(task, parent=self)
        self._worker.progress_signal.connect(self.progress_bar.setValue)
        self._worker.file_progress_signal.connect(self.file_progress.setValue)
        self._worker.current_file_signal.connect(self._on_current_file)
        self._worker.time_signal.connect(self.time_label.setText)
        self._worker.eta_signal.connect(self._on_eta)
        self._worker.log_signal.connect(self._append_log)
        self._worker.error_signal.connect(self._on_worker_error)
        self._worker.finished_signal.connect(self._on_worker_finished)
        self._worker.start()

        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_close.setEnabled(False)
        self.status_bar.showMessage("处理中…")

    def _build_task(self, index: int) -> ConvertTask:
        if index == self.TAB_AUDIO:
            files = self.audio_handles.file_list.all_paths()
            if not files:
                raise ValueError("请先添加音频文件。")
            return ConvertTask(
                kind=TaskKind.AUDIO,
                files=files,
                target_format=format_combo_current_key(self.audio_handles.format_combo) or "mp3",
                output_dir=self._output_path,
                use_hw_accel=False,
                quality=self._quality_preset,
            )
        if index == self.TAB_VIDEO:
            files = self.video_handles.file_list.all_paths()
            if not files:
                raise ValueError("请先添加视频文件。")
            target = format_combo_current_key(self.video_handles.format_combo) or "mp4"
            return ConvertTask(
                kind=TaskKind.VIDEO,
                files=files,
                target_format=target,
                output_dir=self._output_path,
                merge_av=self.video_handles.check_merge.isChecked(),
                use_hw_accel=self._use_hw_accel,
                quality=self._quality_preset,
            )
        if index == self.TAB_SUBTITLE:
            files = self.subtitle_handles.file_list.all_paths()
            if not files:
                raise ValueError("请先添加字幕文件。")
            return ConvertTask(
                kind=TaskKind.SUBTITLE,
                files=files,
                target_format=format_combo_current_key(self.subtitle_handles.format_combo) or "srt",
                output_dir=self._output_path,
                use_hw_accel=False,
                quality=self._quality_preset,
            )
        if index == self.TAB_BURN:
            videos = self.burn_handles.video_list.all_paths()
            subs = self.burn_handles.subtitle_list.all_paths()
            if not videos or not subs:
                raise ValueError("请分别添加视频文件和字幕文件。")
            mode = self.burn_handles.mode_combo.currentText()
            hardcode = mode == "硬编码"
            out_fmt = self.burn_handles.output_format_combo.currentText() if not hardcode else "mp4"
            if videos[0].lower().endswith(".ts") and not hardcode:
                QMessageBox.information(
                    self, "提示",
                    "TS 格式不支持软封装字幕，已自动切换为硬编码模式。",
                )
                hardcode = True
            return ConvertTask(
                kind=TaskKind.BURN,
                files=[],
                output_dir=self._output_path,
                use_hw_accel=self._use_hw_accel,
                quality=self._quality_preset,
                burn=BurnOptions(
                    video_path=videos[0],
                    subtitle_path=subs[0],
                    hardcode=hardcode,
                    output_format=out_fmt,
                ),
            )
        raise ValueError("未知的 Tab。")

    def _ensure_output_dir(self, path: str) -> bool:
        if not path:
            QMessageBox.critical(self, "错误", "未配置输出目录，请在设置中指定。")
            return False
        try:
            os.makedirs(path, exist_ok=True)
            return True
        except OSError as exc:
            QMessageBox.critical(self, "错误", f"无法创建输出目录 {path}:\n{exc}")
            return False

    def _cancel_conversion(self) -> None:
        if self._worker is None or not self._worker.isRunning():
            self.status_bar.showMessage("当前无任务。", 3000)
            return
        reply = QMessageBox.question(
            self, "确认",
            "要取消当前任务吗？正在处理的文件会立即中断。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._worker.request_cancel()
            self.status_bar.showMessage("已请求取消，正在等待子进程退出…")
            self._append_log("[系统] 已请求取消任务…")

    def _open_output_dir(self) -> None:
        path = self._output_path
        if not os.path.exists(path):
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as exc:
                QMessageBox.warning(self, "打开失败", f"无法创建目录: {exc}")
                return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as exc:
            QMessageBox.warning(self, "打开失败", str(exc))

    # ---- Worker signal handlers ---------------------------------------
    def _append_log(self, text: str) -> None:
        if not text:
            return
        self.log_display.appendPlainText(text)
        sb = self.log_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_worker_error(self, msg: str) -> None:
        self._append_log(f"[错误] {msg}")
        QMessageBox.critical(self, "错误", msg)

    def _on_worker_finished(self, success: bool) -> None:
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)
        self._worker = None
        self.eta_label.setText("")
        if success:
            self.status_bar.showMessage("任务完成", 5000)
            self.current_file_label.setText("已完成")
            self._append_log("[完成] 任务已结束。")
        else:
            self.status_bar.showMessage("任务未正常完成", 5000)
            self.current_file_label.setText("未完成")

    def _on_current_file(self, index: int, total: int, filename: str) -> None:
        if total > 1:
            self.current_file_label.setText(f"[{index}/{total}]  {filename}")
        else:
            self.current_file_label.setText(filename)

    def _on_eta(self, eta: str) -> None:
        if eta and eta != "--":
            self.eta_label.setText(f"剩余 ~ {eta}")
        else:
            self.eta_label.setText("")

    # ---- Burn tab hint ------------------------------------------------
    def _update_burn_hint(self, mode_text: str) -> None:
        if "硬编码" in mode_text:
            self.burn_handles.hint_label.setText(
                "硬编码: 字幕永久烧入画面，兼容所有播放器；耗时最长，需要重新编码视频。"
            )
            self.burn_handles.output_format_combo.setEnabled(False)
        else:
            self.burn_handles.hint_label.setText(
                "软封装: 字幕以独立轨道封装在容器里，体积小、可开关，仅支持 MP4 / MKV。"
            )
            self.burn_handles.output_format_combo.setEnabled(True)

    # ---- Close guard --------------------------------------------------
    def closeEvent(self, event):  # noqa: N802
        if self._worker is not None and self._worker.isRunning():
            reply = QMessageBox.question(
                self, "确认退出",
                "当前有任务进行中，是否先取消再退出？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._worker.request_cancel()
                self._worker.wait(5000)
                self._remember_selections()
                event.accept()
            else:
                event.ignore()
        else:
            self._remember_selections()
            event.accept()
