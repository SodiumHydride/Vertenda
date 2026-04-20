# -*- coding: utf-8 -*-
"""Main window: assembles tabs, routes actions to TaskCoordinator.

Integrates: queue panel, result panel, estimate dialog, presets, history,
global drag-and-drop, keyboard shortcuts, notifications.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time

from PyQt5.QtCore import QDir, QSettings, Qt
from PyQt5.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap
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
    QShortcut,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
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
from ..estimator import estimate_task
from ..ffmpeg.commands import build_convert_cmd, build_extract_audio_cmd
from ..ffmpeg.probe import probe_full
from ..ffmpeg.quality import QualityPreset, parse as parse_preset, spec_for
from ..fs import ConflictPolicy
from ..history import HistoryRecord, TaskHistory
from ..notify import send_notification
from ..planning import plan_output_paths
from ..presets import PresetStore, TaskPreset
from ..queue import (
    EventType,
    ExecutionEvent,
    FileResult,
    FileStatus,
    TaskCoordinator,
    resolve_concurrency,
)
from ..subtitle.styling_config import BurnStyle
from ..worker import BurnOptions, ConvertTask, TaskKind
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


def _tab_kind_key(index: int) -> str:
    return {0: "audio", 1: "video", 2: "subtitle", 3: "burn"}.get(index, "")


class ConverterMainWindow(QMainWindow):
    _DEFAULT_WIDTH = 1400
    _DEFAULT_HEIGHT = 880

    TAB_AUDIO = 0
    TAB_VIDEO = 1
    TAB_SUBTITLE = 2
    TAB_BURN = 3

    def __init__(self, initial_files: list[str] | None = None) -> None:
        super().__init__()
        self.setWindowTitle("盐酸转换器 · Vertenda")
        self.resize(self._DEFAULT_WIDTH, self._DEFAULT_HEIGHT)
        self.setMinimumSize(1060, 700)
        self.setAcceptDrops(True)

        icon_path = resource_path("resources/favicon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self._setup_settings()
        self._coordinator = TaskCoordinator(self)
        self._file_results: list[FileResult] = []
        self._conversion_start_time = 0.0
        self._bg_pixmap: QPixmap | None = None
        self._overlay_color: tuple[int, int, int] = (0, 0, 0)
        self._overlay_alpha: int = 0
        # Track the ConvertTask currently being consumed by the coordinator
        # so history can reference it after the queue drains or is cancelled.
        self._active_task: ConvertTask | None = None

        self._history = TaskHistory(self.settings)
        self._preset_store = PresetStore(self.settings)
        self._preset_store.ensure_builtins()

        self._build_ui()
        self._wire_signals()
        self._install_inter_tab_actions()
        self._install_shortcuts()
        self._apply_settings()
        self._restore_last_selections()

        if initial_files:
            self._preload_files(initial_files)

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
                SettingsKey.DEFAULT_CONFLICT_POLICY: "ask",
                SettingsKey.DEFAULT_FILENAME_TEMPLATE: "{base}",
                SettingsKey.DEFAULT_MIRROR_SUBDIRS: False,
                SettingsKey.DEFAULT_CONTINUE_ON_FAILURE: True,
                SettingsKey.CONCURRENCY_MODE: "auto",
                SettingsKey.NOTIFY_ON_COMPLETE: True,
                SettingsKey.SOUND_ON_COMPLETE: False,
                SettingsKey.OPEN_OUTPUT_ON_COMPLETE: False,
            }
            for k, v in defaults.items():
                self.settings.setValue(k, v)

    # ---- UI construction ----------------------------------------------
    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 12, 14, 10)
        left_layout.setSpacing(10)

        left_layout.addLayout(self._build_top_bar())

        self.tabs = QTabWidget(self)
        self.audio_handles = build_audio_tab()
        self.video_handles = build_video_tab()
        self.subtitle_handles = build_subtitle_tab()
        self.burn_handles = build_burn_tab()
        self.tabs.addTab(self.audio_handles.widget, "音频转换")
        self.tabs.addTab(self.video_handles.widget, "视频转换")
        self.tabs.addTab(self.subtitle_handles.widget, "字幕转换")
        self.tabs.addTab(self.burn_handles.widget, "字幕烧录")
        left_layout.addWidget(self.tabs, stretch=3)

        mid_splitter = QSplitter(Qt.Horizontal)
        self.log_display = QPlainTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setPlaceholderText("日志输出...")
        self.log_display.setMaximumBlockCount(2000)
        mid_splitter.addWidget(self.log_display)

        self.info_panel = QTextEdit()
        self.info_panel.setReadOnly(True)
        self.info_panel.setPlaceholderText("选中文件查看元信息")
        self.info_panel.setMaximumWidth(320)
        self.info_panel.setMinimumWidth(160)
        mid_splitter.addWidget(self.info_panel)
        mid_splitter.setSizes([600, 280])
        left_layout.addWidget(mid_splitter, stretch=2)

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
        left_layout.addLayout(progress_block)

        action_row = QHBoxLayout()
        self.btn_start = QPushButton("开始转换")
        self.btn_start.setObjectName("PrimaryButton")
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setObjectName("DangerButton")
        self.btn_cancel.setEnabled(False)
        self.btn_export_log = QPushButton("导出日志")
        self.btn_open_output = QPushButton("打开输出目录")
        self.btn_close = QPushButton("关闭")
        action_row.addWidget(self.btn_start)
        action_row.addWidget(self.btn_cancel)
        action_row.addStretch()
        action_row.addWidget(self.btn_export_log)
        action_row.addWidget(self.btn_open_output)
        action_row.addWidget(self.btn_close)
        left_layout.addLayout(action_row)

        self._splitter.addWidget(left)

        from .queue_panel import QueuePanel
        self.queue_panel = QueuePanel()
        self.queue_panel.set_coordinator(self._coordinator)
        self.queue_panel.setMinimumWidth(200)
        self.queue_panel.setMaximumWidth(360)
        self._splitter.addWidget(self.queue_panel)
        self._splitter.setSizes([1100, 260])

        root_layout.addWidget(self._splitter)

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

        self.btn_history = QToolButton()
        self.btn_history.setText("历史")
        self.btn_history.clicked.connect(self._open_history)
        bar.addWidget(self.btn_history)

        self.btn_settings = QToolButton()
        self.btn_settings.setText("设置")
        bar.addWidget(self.btn_settings)
        return bar

    # ---- Keyboard shortcuts -------------------------------------------
    def _install_shortcuts(self) -> None:
        QShortcut(QKeySequence("Ctrl+O"), self, self._shortcut_add_files)
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, self._shortcut_add_dir)
        QShortcut(QKeySequence("Delete"), self, self._shortcut_remove)
        QShortcut(QKeySequence("Ctrl+,"), self, self._open_settings)

    def _shortcut_add_files(self) -> None:
        idx = self.tabs.currentIndex()
        handlers = {
            self.TAB_AUDIO: (self.audio_handles.file_list, "音频", AUDIO_EXTS),
            self.TAB_VIDEO: (self.video_handles.file_list, "视频", VIDEO_EXTS),
            self.TAB_SUBTITLE: (self.subtitle_handles.file_list, "字幕", SUBTITLE_EXTS),
        }
        if idx in handlers:
            fl, lbl, exts = handlers[idx]
            self._add_files(fl, lbl, exts)

    def _shortcut_add_dir(self) -> None:
        idx = self.tabs.currentIndex()
        handlers = {
            self.TAB_AUDIO: (self.audio_handles.file_list, AUDIO_EXTS),
            self.TAB_VIDEO: (self.video_handles.file_list, VIDEO_EXTS),
            self.TAB_SUBTITLE: (self.subtitle_handles.file_list, SUBTITLE_EXTS),
        }
        if idx in handlers:
            fl, exts = handlers[idx]
            self._add_directory(fl, exts)

    def _shortcut_remove(self) -> None:
        idx = self.tabs.currentIndex()
        lists = {
            self.TAB_AUDIO: self.audio_handles.file_list,
            self.TAB_VIDEO: self.video_handles.file_list,
            self.TAB_SUBTITLE: self.subtitle_handles.file_list,
        }
        fl = lists.get(idx)
        if fl:
            fl.remove_selected()

    # ---- Signal wiring -------------------------------------------------
    def _wire_signals(self) -> None:
        self.btn_settings.clicked.connect(self._open_settings)

        self.audio_handles.btn_add.clicked.connect(
            lambda: self._add_files(self.audio_handles.file_list, "音频", AUDIO_EXTS)
        )
        self.audio_handles.btn_add_dir.clicked.connect(
            lambda: self._add_directory(self.audio_handles.file_list, AUDIO_EXTS)
        )
        self.audio_handles.btn_remove.clicked.connect(self.audio_handles.file_list.remove_selected)
        self.audio_handles.btn_clear.clicked.connect(self.audio_handles.file_list.clear_all)

        self.video_handles.btn_add.clicked.connect(
            lambda: self._add_files(self.video_handles.file_list, "视频", VIDEO_EXTS)
        )
        self.video_handles.btn_add_dir.clicked.connect(
            lambda: self._add_directory(self.video_handles.file_list, VIDEO_EXTS)
        )
        self.video_handles.btn_remove.clicked.connect(self.video_handles.file_list.remove_selected)
        self.video_handles.btn_clear.clicked.connect(self.video_handles.file_list.clear_all)

        self.subtitle_handles.btn_add.clicked.connect(
            lambda: self._add_files(self.subtitle_handles.file_list, "字幕", SUBTITLE_EXTS)
        )
        self.subtitle_handles.btn_add_dir.clicked.connect(
            lambda: self._add_directory(self.subtitle_handles.file_list, SUBTITLE_EXTS)
        )
        self.subtitle_handles.btn_remove.clicked.connect(self.subtitle_handles.file_list.remove_selected)
        self.subtitle_handles.btn_clear.clicked.connect(self.subtitle_handles.file_list.clear_all)

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
        self.btn_export_log.clicked.connect(self._export_log)
        self.btn_open_output.clicked.connect(self._open_output_dir)
        self.btn_close.clicked.connect(self.close)

        hub = self._coordinator.hub
        hub.file_started.connect(self._on_current_file)
        hub.file_progress.connect(self.file_progress.setValue)
        hub.file_time.connect(self.time_label.setText)
        hub.overall_progress.connect(self.progress_bar.setValue)
        hub.eta.connect(self._on_eta)
        hub.log.connect(self._append_log)
        hub.error.connect(self._on_coordinator_error)
        hub.file_done.connect(self._on_file_done)
        hub.execution_event.connect(self._on_execution_event)
        self._coordinator.all_done.connect(self._on_all_done)

        self.queue_panel.pause_requested.connect(self._coordinator.pause)
        self.queue_panel.resume_requested.connect(self._coordinator.resume)
        self.queue_panel.skip_requested.connect(self._coordinator.skip_current)
        self.queue_panel.cancel_all_requested.connect(self._cancel_conversion)

        # File info preview on selection change
        for fl in (self.audio_handles.file_list, self.video_handles.file_list,
                    self.subtitle_handles.file_list):
            fl.currentItemChanged.connect(self._on_file_selection_changed)

    def _install_inter_tab_actions(self) -> None:
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
        # Copy ffmpeg command (all media tabs)
        for fl, kind in ((self.audio_handles.file_list, TaskKind.AUDIO),
                         (self.video_handles.file_list, TaskKind.VIDEO)):
            fl.register_action(CustomAction(
                "复制 ffmpeg 命令",
                handler=lambda paths, k=kind: self._copy_ffmpeg_cmd(paths, k),
                enabled=lambda paths: len(paths) == 1,
            ))

    def _send_to(self, target_list, paths: list[str], message: str) -> None:
        added, dup = target_list.add_many(paths)
        if dup and not added:
            self.status_bar.showMessage("目标列表已存在所有选中文件。", 3000)
        elif dup:
            self.status_bar.showMessage(f"{message}（{added} 个新增，{dup} 个重复）", 4000)
        else:
            self.status_bar.showMessage(f"{message}（{added} 个）", 3000)

    def _copy_ffmpeg_cmd(self, paths: list[str], kind: TaskKind) -> None:
        if not paths:
            return
        src = paths[0]
        target = format_combo_current_key(
            self.video_handles.format_combo if kind == TaskKind.VIDEO
            else self.audio_handles.format_combo
        ) or "mp4"
        out = os.path.join(self._output_path, f"OUTPUT.{target}")
        spec = spec_for(self._quality_preset)
        target_ext = "." + target.lower()
        if target_ext in AUDIO_EXTS and kind == TaskKind.VIDEO:
            cmd = build_extract_audio_cmd(src, out, spec=spec)
        else:
            cmd = build_convert_cmd(src, out, use_hw=self._use_hw_accel, spec=spec)
        text = shlex.join(cmd)
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)
            self.status_bar.showMessage("ffmpeg 命令已复制到剪贴板", 3000)

    # ---- File info preview -------------------------------------------
    def _on_file_selection_changed(self, current, _previous) -> None:
        if current is None:
            self.info_panel.clear()
            return
        path = current.data(Qt.UserRole)
        if not path or not os.path.isfile(path):
            self.info_panel.setPlainText("(文件不存在)")
            return
        info = probe_full(path)
        if info:
            self.info_panel.setPlainText(info.summary_text())
        else:
            self.info_panel.setPlainText("(无法读取元信息)")

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
        self._conflict_policy = ConflictPolicy(s.value(SettingsKey.DEFAULT_CONFLICT_POLICY, "ask", type=str))
        self._filename_template = s.value(SettingsKey.DEFAULT_FILENAME_TEMPLATE, "{base}", type=str)
        self._mirror_subdirs = s.value(SettingsKey.DEFAULT_MIRROR_SUBDIRS, False, type=bool)
        self._continue_on_failure = s.value(SettingsKey.DEFAULT_CONTINUE_ON_FAILURE, True, type=bool)
        self._concurrency_mode = s.value(SettingsKey.CONCURRENCY_MODE, "auto", type=str)
        self._notify_on_complete = s.value(SettingsKey.NOTIFY_ON_COMPLETE, True, type=bool)
        self._open_output_on_complete = s.value(SettingsKey.OPEN_OUTPUT_ON_COMPLETE, False, type=bool)

        font = QFont()
        font.setPointSize(self._font_size)
        QApplication.instance().setFont(font)
        self.setFont(font)

        QApplication.instance().setStyleSheet(build_stylesheet(self._theme_mode))
        self._overlay_color = overlay_color_for(self._theme_mode)
        self._overlay_alpha = int(self._overlay_strength / 100.0 * 255)
        self._load_background()
        self.quality_badge.setText(f"质量 · {self._quality_preset.display.split(' ·')[0]}")

        burn_json = s.value(SettingsKey.CUSTOM_BURN_STYLE, "", type=str)
        if burn_json:
            self._burn_style = BurnStyle.from_json(burn_json)
        else:
            self._burn_style = BurnStyle()

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

    def _open_history(self) -> None:
        from .history_dialog import HistoryDialog
        dlg = HistoryDialog(self._history, self)
        dlg.exec_()

    # ---- Global drag-and-drop (auto-route by extension) ---------------
    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802
        if not event.mimeData().hasUrls():
            event.ignore()
            return
        event.setDropAction(Qt.CopyAction)
        event.acceptProposedAction()

        audio_count, video_count, sub_count = 0, 0, 0
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if not path:
                continue
            if os.path.isdir(path):
                a, _ = self.audio_handles.file_list.add_directory(path, extensions=AUDIO_EXTS)
                audio_count += a
                v, _ = self.video_handles.file_list.add_directory(path, extensions=VIDEO_EXTS)
                video_count += v
                s, _ = self.subtitle_handles.file_list.add_directory(path, extensions=SUBTITLE_EXTS)
                sub_count += s
            elif is_audio_file(path):
                if self.audio_handles.file_list.add_path(path):
                    audio_count += 1
            elif is_video_file(path):
                if self.video_handles.file_list.add_path(path):
                    video_count += 1
            elif is_subtitle_file(path):
                if self.subtitle_handles.file_list.add_path(path):
                    sub_count += 1

        total = audio_count + video_count + sub_count
        if total == 0:
            self.status_bar.showMessage("未找到支持的文件。", 3000)
            return

        parts = []
        if audio_count:
            parts.append(f"音频 {audio_count}")
        if video_count:
            parts.append(f"视频 {video_count}")
        if sub_count:
            parts.append(f"字幕 {sub_count}")
        msg = f"已自动分流: {' · '.join(parts)}"
        self.status_bar.showMessage(msg, 4000)

        if video_count and not audio_count and not sub_count:
            self.tabs.setCurrentIndex(self.TAB_VIDEO)
        elif audio_count and not video_count and not sub_count:
            self.tabs.setCurrentIndex(self.TAB_AUDIO)
        elif sub_count and not audio_count and not video_count:
            self.tabs.setCurrentIndex(self.TAB_SUBTITLE)

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
            self.status_bar.showMessage(f"已添加 {added} 个文件，跳过 {dup} 个重复项", 4000)
        else:
            self.status_bar.showMessage(f"已添加 {added} 个文件", 3000)

    # ---- Persistence ---------------------------------------------------
    def _restore_last_selections(self) -> None:
        s = self.settings
        format_combo_set_key(self.audio_handles.format_combo,
                              s.value(SettingsKey.LAST_AUDIO_FORMAT, "mp3", type=str))
        format_combo_set_key(self.video_handles.format_combo,
                              s.value(SettingsKey.LAST_VIDEO_FORMAT, "mp4", type=str))
        format_combo_set_key(self.subtitle_handles.format_combo,
                              s.value(SettingsKey.LAST_SUBTITLE_FORMAT, "srt", type=str))
        mode = s.value(SettingsKey.LAST_BURN_MODE, "硬编码", type=str)
        idx = self.burn_handles.mode_combo.findText(mode)
        if idx >= 0:
            self.burn_handles.mode_combo.setCurrentIndex(idx)
        out_fmt = s.value(SettingsKey.LAST_BURN_OUTPUT_FORMAT, "mkv", type=str)
        idx = self.burn_handles.output_format_combo.findText(out_fmt)
        if idx >= 0:
            self.burn_handles.output_format_combo.setCurrentIndex(idx)

    def _preload_files(self, paths: list[str]) -> None:
        """Dispatch files (from CLI/context-menu invocation) to matching tabs.

        Each file goes to exactly one tab based on its extension. The tab
        containing the last successfully dispatched file becomes active so
        the user sees the loaded file immediately.
        """
        target_tab: int | None = None
        for path in paths:
            if is_audio_file(path):
                added = self.audio_handles.file_list.add_path(path)
                if added:
                    target_tab = self.TAB_AUDIO
            elif is_video_file(path):
                added = self.video_handles.file_list.add_path(path)
                if added:
                    target_tab = self.TAB_VIDEO
            elif is_subtitle_file(path):
                added = self.subtitle_handles.file_list.add_path(path)
                if added:
                    target_tab = self.TAB_SUBTITLE
        if target_tab is not None:
            self.tabs.setCurrentIndex(target_tab)

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
        if self._coordinator.running:
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

        # Pre-flight estimate (batch tasks only; burn is single-shot)
        if task.files and task.kind != TaskKind.BURN:
            from .estimate_dialog import EstimateDialog
            spec = spec_for(task.quality)
            report = estimate_task(
                task.files, task.target_format, task.output_dir, spec,
                task.use_hw_accel,
                is_audio_only=(task.kind == TaskKind.AUDIO),
                filename_template=task.filename_template,
                mirror_subdirs=task.mirror_subdirs,
                source_root=task.source_root,
            )
            dlg = EstimateDialog(report, self)
            if dlg.exec_() != QDialog.Accepted:
                return
            if dlg.chosen_conflict is not None:
                task.conflict_policy = dlg.chosen_conflict

        # Pre-compute the output plan so concurrent runnables don't race
        # on conflict resolution. ASK is resolved inside plan_output_paths
        # by degrading to RENAME, which matches the estimate-dialog choice
        # the user already confirmed.
        plan = None
        if task.files and task.kind != TaskKind.BURN:
            plan = plan_output_paths(
                task.files,
                target_format=task.target_format,
                output_dir=task.output_dir,
                policy=task.conflict_policy,
                filename_template=task.filename_template,
                quality_name=task.quality.value,
                preset_name=task.preset_name,
                mirror_subdirs=task.mirror_subdirs,
                source_root=task.source_root,
            )
        self._coordinator.attach_plan(plan)

        self._remember_selections()
        self._file_results.clear()
        self._conversion_start_time = time.monotonic()
        self._active_task = task

        self.log_display.clear()
        self.progress_bar.setValue(0)
        self.file_progress.setValue(0)
        self.time_label.setText("00:00:00")
        self.current_file_label.setText(f"准备中 · {_tab_kind_label(index)}")
        self.eta_label.setText("")

        n = resolve_concurrency(
            self._concurrency_mode, task.use_hw_accel,
            task.kind == TaskKind.BURN,
        )
        self._coordinator.set_concurrency(n)
        task._concurrency_mode = self._concurrency_mode
        self._coordinator.queue.enqueue(task)
        self._coordinator.start()
        self.queue_panel.refresh()

        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_close.setEnabled(False)
        self.queue_panel.set_running(True)
        self.status_bar.showMessage(f"处理中… · 并发 {n} 路")

    def _build_task(self, index: int) -> ConvertTask:
        common = dict(
            conflict_policy=self._conflict_policy,
            filename_template=self._filename_template,
            mirror_subdirs=self._mirror_subdirs,
            continue_on_failure=self._continue_on_failure,
            burn_style=self._burn_style,
        )
        if index == self.TAB_AUDIO:
            files = self.audio_handles.file_list.all_paths()
            if not files:
                raise ValueError("请先添加音频文件。")
            return ConvertTask(
                kind=TaskKind.AUDIO, files=files,
                target_format=format_combo_current_key(self.audio_handles.format_combo) or "mp3",
                output_dir=self._output_path, use_hw_accel=False,
                quality=self._quality_preset, **common,
            )
        if index == self.TAB_VIDEO:
            files = self.video_handles.file_list.all_paths()
            if not files:
                raise ValueError("请先添加视频文件。")
            return ConvertTask(
                kind=TaskKind.VIDEO, files=files,
                target_format=format_combo_current_key(self.video_handles.format_combo) or "mp4",
                output_dir=self._output_path,
                merge_av=self.video_handles.check_merge.isChecked(),
                use_hw_accel=self._use_hw_accel,
                quality=self._quality_preset, **common,
            )
        if index == self.TAB_SUBTITLE:
            files = self.subtitle_handles.file_list.all_paths()
            if not files:
                raise ValueError("请先添加字幕文件。")
            return ConvertTask(
                kind=TaskKind.SUBTITLE, files=files,
                target_format=format_combo_current_key(self.subtitle_handles.format_combo) or "srt",
                output_dir=self._output_path, use_hw_accel=False,
                quality=self._quality_preset, **common,
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
                QMessageBox.information(self, "提示", "TS 格式不支持软封装字幕，已自动切换为硬编码模式。")
                hardcode = True
            return ConvertTask(
                kind=TaskKind.BURN, files=[],
                output_dir=self._output_path, use_hw_accel=self._use_hw_accel,
                quality=self._quality_preset,
                burn=BurnOptions(
                    video_path=videos[0], subtitle_path=subs[0],
                    hardcode=hardcode, output_format=out_fmt,
                ), **common,
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
        if not self._coordinator.running:
            self.status_bar.showMessage("当前无任务。", 3000)
            return
        reply = QMessageBox.question(
            self, "确认",
            "要取消当前任务吗？正在处理的文件会立即中断。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._coordinator.cancel_all()
            self.status_bar.showMessage("已请求取消…")
            self._append_log("[系统] 已请求取消任务…")
            self._reset_ui_state()

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

    def _export_log(self) -> None:
        text = self.log_display.toPlainText()
        if not text.strip():
            self.status_bar.showMessage("日志为空，无需导出。", 3000)
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", "convert_log.txt",
            "文本文件 (*.txt);;所有文件 (*)",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text)
                self.status_bar.showMessage(f"日志已导出到 {path}", 4000)
            except OSError as exc:
                QMessageBox.warning(self, "导出失败", str(exc))

    # ---- Coordinator signal handlers ----------------------------------
    def _append_log(self, text: str) -> None:
        if not text:
            return
        self.log_display.appendPlainText(text)
        sb = self.log_display.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_coordinator_error(self, msg: str) -> None:
        self._append_log(f"[错误] {msg}")

    def _on_file_done(self, result: FileResult) -> None:
        self._file_results.append(result)

    def _on_execution_event(self, event: ExecutionEvent) -> None:
        """Single entry point for cross-cutting concerns (history / notify).

        This keeps ``_on_all_done`` focused on UI, and gives future
        subscribers (telemetry, sound, etc.) a stable place to hook into.
        """
        if event.type == EventType.SOFT_STOP.value:
            # Don't let a soft-stop banner get lost in the log scroll.
            self.status_bar.showMessage(event.message or "已停止派发", 5000)

    def _on_all_done(self, results: list[FileResult]) -> None:
        self._reset_ui_state()
        elapsed = time.monotonic() - self._conversion_start_time

        success = [r for r in results if r.status == FileStatus.SUCCESS]
        failed = [r for r in results if r.status == FileStatus.FAILED]
        skipped = [r for r in results if r.status in (FileStatus.SKIPPED, FileStatus.CANCELLED)]

        if success and not failed:
            self.status_bar.showMessage("任务完成", 5000)
            self.current_file_label.setText("已完成")
            self._append_log(f"[完成] 全部 {len(success)} 个文件处理成功。")
        elif failed:
            self.status_bar.showMessage(f"任务完成，{len(failed)} 个失败", 5000)
            self.current_file_label.setText(f"完成 · {len(failed)} 个失败")
        else:
            self.status_bar.showMessage("任务结束", 5000)
            self.current_file_label.setText("已结束")

        # History uses the cached reference — cancel_all() clears the queue,
        # so ``coordinator.queue.all_tasks[-1]`` may be gone by now.
        task = self._active_task
        if results or task is not None:
            self._history.add(HistoryRecord(
                task_kind=task.kind.value if task else "",
                file_count=len(results),
                duration_s=elapsed,
                success_count=len(success),
                fail_count=len(failed),
                skip_count=len(skipped),
                target_format=task.target_format if task else "",
                preset_name=task.preset_name if task else "",
                output_dir=task.output_dir if task else "",
            ))
        self._active_task = None

        if self._notify_on_complete and results:
            body = f"成功 {len(success)} · 失败 {len(failed)} · 跳过 {len(skipped)}"
            send_notification("盐酸转换器 · 完成", body)

        if self._open_output_on_complete and success:
            self._open_output_dir()

        if results:
            from .result_panel import ResultPanel
            panel = ResultPanel(results, self)
            panel.retry_requested = self._retry_failed_files
            panel.exec_()

        self.queue_panel.refresh()

    def _retry_failed_files(self, paths: list[str]) -> None:
        if not paths:
            return
        # Prefer the most-recent *active* task (survives cancellation) and
        # fall back to the queue history only as a last resort.
        source_task = self._active_task or (
            self._coordinator.queue.all_tasks[-1]
            if self._coordinator.queue.all_tasks else None
        )
        if source_task is None:
            self.status_bar.showMessage("没有可用的原始任务参数用于重试。", 4000)
            return

        retry = ConvertTask(
            kind=source_task.kind,
            files=paths,
            target_format=source_task.target_format,
            output_dir=source_task.output_dir,
            merge_av=False,
            use_hw_accel=source_task.use_hw_accel,
            quality=source_task.quality,
            conflict_policy=ConflictPolicy.OVERWRITE,
            filename_template=source_task.filename_template,
            mirror_subdirs=source_task.mirror_subdirs,
            continue_on_failure=source_task.continue_on_failure,
            burn_style=source_task.burn_style,
            preset_name=source_task.preset_name,
        )
        self._active_task = retry
        self._conversion_start_time = time.monotonic()
        self._file_results.clear()
        self._coordinator.attach_plan(None)  # retry rebuilds via runtime reservation
        self._coordinator.queue.enqueue(retry)
        self._coordinator.start()
        self.queue_panel.refresh()
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.queue_panel.set_running(True)
        self.status_bar.showMessage("重试失败项中…")

    def _reset_ui_state(self) -> None:
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_close.setEnabled(True)
        self.queue_panel.set_running(False)
        self.eta_label.setText("")

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
        if self._coordinator.running:
            reply = QMessageBox.question(
                self, "确认退出",
                "当前有任务进行中，是否先取消再退出？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                self._coordinator.cancel_all()
                self._remember_selections()
                event.accept()
            else:
                event.ignore()
        else:
            self._remember_selections()
            event.accept()
