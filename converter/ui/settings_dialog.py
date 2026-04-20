# -*- coding: utf-8 -*-
"""Settings dialog with a tabbed layout:

  * Appearance  - theme / font / background
  * Conversion  - output dir / hardware accel / quality preset
  * Data        - custom data dir, ffmpeg cache info, cleanup, uninstall hint
"""

from __future__ import annotations

import os
import subprocess
import sys

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..constants import SettingsKey
from ..ffmpeg.installer import (
    app_data_dir,
    cache_size_bytes,
    ffmpeg_cache_dir,
    installed_by_us,
    read_marker,
    remove_cache,
    set_data_dir_override,
)
from ..ffmpeg.quality import QualityPreset, parse as parse_preset

if sys.platform == "win32":
    from ..shell import win_registry  # type: ignore
else:
    win_registry = None  # type: ignore[assignment]


def _human_bytes(n: int) -> str:
    if n <= 0:
        return "0 B"
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024.0
    return f"{value:.1f} TB"


class SettingsDialog(QDialog):
    """Tabbed preferences dialog."""

    hw_accel_changed_signal = pyqtSignal(bool)
    data_dir_changed_signal = pyqtSignal()

    def __init__(self, parent, settings) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("偏好设置")
        self.resize(640, 560)

        self._build_ui()
        self._load_values()
        self._refresh_data_info()

    # ---- top-level layout --------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_appearance_tab(), "外观")
        self.tabs.addTab(self._build_conversion_tab(), "转换")
        self.tabs.addTab(self._build_data_tab(), "数据与存储")
        layout.addWidget(self.tabs, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_save = QPushButton("保存")
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_cancel = QPushButton("取消")
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_cancel)
        layout.addLayout(btn_row)

        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.reject)

    # ---- Appearance tab ----------------------------------------------
    def _build_appearance_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)

        self.bg_path_edit = QLineEdit()
        btn_browse_bg = QPushButton("浏览…")
        btn_browse_bg.clicked.connect(self._browse_bg)
        row_bg = QHBoxLayout()
        row_bg.addWidget(self.bg_path_edit)
        row_bg.addWidget(btn_browse_bg)
        form.addRow("背景图路径:", row_bg)

        self.bg_alpha_slider = QSlider(Qt.Horizontal)
        self.bg_alpha_slider.setRange(0, 100)
        self.label_alpha = QLabel("70 %")
        self.label_alpha.setFixedWidth(52)
        self.bg_alpha_slider.valueChanged.connect(
            lambda v: self.label_alpha.setText(f"{v} %")
        )
        row_alpha = QHBoxLayout()
        row_alpha.addWidget(self.bg_alpha_slider)
        row_alpha.addWidget(self.label_alpha)
        form.addRow("背景透明度:", row_alpha)

        self.overlay_slider = QSlider(Qt.Horizontal)
        self.overlay_slider.setRange(0, 100)
        self.overlay_slider.setToolTip(
            "在背景图之上叠加的主题色遮罩强度。背景太花时调高，完全看不到背景时调低。"
        )
        self.label_overlay = QLabel("40 %")
        self.label_overlay.setFixedWidth(52)
        self.overlay_slider.valueChanged.connect(
            lambda v: self.label_overlay.setText(f"{v} %")
        )
        row_overlay = QHBoxLayout()
        row_overlay.addWidget(self.overlay_slider)
        row_overlay.addWidget(self.label_overlay)
        form.addRow("可读性遮罩:", row_overlay)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light"])
        form.addRow("主题模式:", self.theme_combo)

        self.spin_font_size = QSpinBox()
        self.spin_font_size.setRange(8, 24)
        form.addRow("字体大小:", self.spin_font_size)

        return page

    # ---- Conversion tab ----------------------------------------------
    def _build_conversion_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)

        self.output_edit = QLineEdit()
        btn_browse_out = QPushButton("选择…")
        btn_browse_out.clicked.connect(self._browse_output)
        row_out = QHBoxLayout()
        row_out.addWidget(self.output_edit)
        row_out.addWidget(btn_browse_out)
        form.addRow("输出目录:", row_out)

        self.check_hw = QCheckBox("启用 GPU 硬件加速 (macOS VideoToolbox)")
        form.addRow("硬件加速:", self.check_hw)

        self.quality_combo = QComboBox()
        for preset in (QualityPreset.FAST, QualityPreset.BALANCED, QualityPreset.HIGH):
            self.quality_combo.addItem(preset.display, userData=preset.value)
        form.addRow("转换质量:", self.quality_combo)

        self.conflict_combo = QComboBox()
        self.conflict_combo.addItems(["ask", "skip", "overwrite", "rename"])
        self.conflict_combo.setToolTip("ask=开始前弹窗 skip=跳过 overwrite=覆盖 rename=加后缀")
        form.addRow("冲突策略:", self.conflict_combo)

        self.filename_edit = QLineEdit()
        self.filename_edit.setPlaceholderText("{base}")
        self.filename_edit.setToolTip("{base} {ext} {target} {quality} {preset} {date} {datetime} {count} {parent}")
        form.addRow("文件名模板:", self.filename_edit)

        self.check_mirror = QCheckBox("保留源目录结构")
        form.addRow("子目录镜像:", self.check_mirror)

        self.check_continue = QCheckBox("批量中某文件失败时继续处理剩余文件")
        form.addRow("失败策略:", self.check_continue)

        self.concurrency_combo = QComboBox()
        self.concurrency_combo.addItems(["auto", "1", "2", "3", "4", "5", "6", "7", "8"])
        self.concurrency_combo.setToolTip("auto=自动检测, 1-8=手动指定并发路数")
        form.addRow("并发路数:", self.concurrency_combo)

        self.check_notify = QCheckBox("任务完成后系统通知")
        form.addRow("桌面通知:", self.check_notify)

        self.check_open_output = QCheckBox("任务完成后自动打开输出目录")
        form.addRow("完成动作:", self.check_open_output)

        if win_registry is not None:
            self.check_ctx_menu = QCheckBox("右键文件 → “转换 (Kurisu)” 子菜单")
            self.check_ctx_menu.setToolTip(
                "在 Windows 资源管理器里给常见音视频/字幕文件的右键菜单加一个子菜单。\n"
                "只写 HKCU 用户注册表，不需要管理员权限，卸载时一键清理。"
            )
            form.addRow("右键集成:", self.check_ctx_menu)
            self._original_ctx_enabled = False  # filled in _load_values
        else:
            self.check_ctx_menu = None  # type: ignore[assignment]

        return page

    # ---- Data tab ----------------------------------------------------
    def _build_data_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        intro = QLabel(
            "这个页面管理程序的运行时数据。我们不会写入系统 PATH 或其它位置，\n"
            "所有文件都在下方显示的目录里，拖走应用 = 卸载（配合这里的清理按钮）。"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #888;")
        layout.addWidget(intro)

        # ---- Data directory row ---------------------------------------
        dir_label = QLabel("数据目录:")
        dir_label.setStyleSheet("font-weight: 600; padding-top: 4px;")
        layout.addWidget(dir_label)

        self.data_dir_edit = QLineEdit()
        self.data_dir_edit.setPlaceholderText("(默认) " + str(app_data_dir().parent))
        btn_pick_dir = QPushButton("更改…")
        btn_pick_dir.clicked.connect(self._pick_data_dir)
        btn_reset_dir = QPushButton("恢复默认")
        btn_reset_dir.clicked.connect(self._reset_data_dir)
        row_dir = QHBoxLayout()
        row_dir.addWidget(self.data_dir_edit)
        row_dir.addWidget(btn_pick_dir)
        row_dir.addWidget(btn_reset_dir)
        layout.addLayout(row_dir)

        hint = QLabel(
            "Windows 用户如果不想占 C 盘，可以指定 D 盘或其它位置。"
            "更改后，旧位置的 FFmpeg 缓存不会自动迁移，下次启动会重新下载。"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        # ---- FFmpeg status block --------------------------------------
        layout.addSpacing(8)
        ffmpeg_header = QLabel("FFmpeg 状态:")
        ffmpeg_header.setStyleSheet("font-weight: 600; padding-top: 4px;")
        layout.addWidget(ffmpeg_header)

        self.ffmpeg_status_label = QLabel()
        self.ffmpeg_status_label.setWordWrap(True)
        self.ffmpeg_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.ffmpeg_status_label)

        row_actions = QHBoxLayout()
        self.btn_open_data = QPushButton("打开数据目录")
        self.btn_open_data.clicked.connect(self._open_data_dir)
        self.btn_clear_ffmpeg = QPushButton("清除 FFmpeg 缓存")
        self.btn_clear_ffmpeg.setObjectName("DangerButton")
        self.btn_clear_ffmpeg.clicked.connect(self._clear_ffmpeg_cache)
        row_actions.addWidget(self.btn_open_data)
        row_actions.addWidget(self.btn_clear_ffmpeg)
        row_actions.addStretch()
        layout.addLayout(row_actions)

        # ---- Uninstall hint -------------------------------------------
        layout.addStretch()

        if sys.platform == "darwin":
            uninstall_text = (
                "卸载方式：点击上方 “清除 FFmpeg 缓存”，然后把 Vertenda.app 拖入废纸篓即可。\n"
                "本程序从未修改系统 PATH、注册表或其他位置。"
            )
        elif sys.platform == "win32":
            uninstall_text = (
                "卸载方式：点击上方 “清除 FFmpeg 缓存”，然后删除 Vertenda.exe 所在目录即可。\n"
                "本程序从未写入注册表（除可选的右键菜单项，已在上方管理）或其他系统位置。"
            )
        else:
            uninstall_text = (
                "卸载方式：清除数据后删除应用可执行文件。本程序只写入你的用户数据目录。"
            )
        note = QLabel(uninstall_text)
        note.setWordWrap(True)
        note.setStyleSheet(
            "color: #888; background: rgba(128, 128, 128, 30); "
            "border-radius: 6px; padding: 10px;"
        )
        layout.addWidget(note)

        return page

    # ---- Load / refresh ----------------------------------------------
    def _load_values(self) -> None:
        s = self.settings
        self.bg_path_edit.setText(s.value(SettingsKey.BG_PATH, "", type=str))
        alpha = s.value(SettingsKey.BG_ALPHA, 70, type=int)
        self.bg_alpha_slider.setValue(alpha)
        self.label_alpha.setText(f"{alpha} %")
        overlay = s.value(SettingsKey.OVERLAY_STRENGTH, 40, type=int)
        self.overlay_slider.setValue(overlay)
        self.label_overlay.setText(f"{overlay} %")
        theme = s.value(SettingsKey.THEME_MODE, "Dark", type=str)
        self.theme_combo.setCurrentIndex(1 if theme == "Light" else 0)
        self.spin_font_size.setValue(s.value(SettingsKey.FONT_SIZE, 11, type=int))
        self.output_edit.setText(s.value(SettingsKey.OUTPUT_PATH, "", type=str))
        self.check_hw.setChecked(s.value(SettingsKey.USE_HW_ACCEL, False, type=bool))
        preset = parse_preset(s.value(SettingsKey.QUALITY_PRESET, "balanced", type=str))
        idx = self.quality_combo.findData(preset.value)
        self.quality_combo.setCurrentIndex(max(0, idx))
        self.data_dir_edit.setText(s.value(SettingsKey.CUSTOM_DATA_DIR, "", type=str))

        conflict = s.value(SettingsKey.DEFAULT_CONFLICT_POLICY, "ask", type=str)
        idx = self.conflict_combo.findText(conflict)
        if idx >= 0:
            self.conflict_combo.setCurrentIndex(idx)
        self.filename_edit.setText(s.value(SettingsKey.DEFAULT_FILENAME_TEMPLATE, "{base}", type=str))
        self.check_mirror.setChecked(s.value(SettingsKey.DEFAULT_MIRROR_SUBDIRS, False, type=bool))
        self.check_continue.setChecked(s.value(SettingsKey.DEFAULT_CONTINUE_ON_FAILURE, True, type=bool))
        conc = s.value(SettingsKey.CONCURRENCY_MODE, "auto", type=str)
        idx = self.concurrency_combo.findText(conc)
        if idx >= 0:
            self.concurrency_combo.setCurrentIndex(idx)
        self.check_notify.setChecked(s.value(SettingsKey.NOTIFY_ON_COMPLETE, True, type=bool))
        self.check_open_output.setChecked(s.value(SettingsKey.OPEN_OUTPUT_ON_COMPLETE, False, type=bool))

        if self.check_ctx_menu is not None and win_registry is not None:
            currently = win_registry.is_registered()
            self.check_ctx_menu.setChecked(currently)
            self._original_ctx_enabled = currently

    def _refresh_data_info(self) -> None:
        """Rebuild the FFmpeg status line from what's currently on disk."""
        from .. import constants  # late import to see latest FFMPEG_PATH
        ffmpeg_path = constants.FFMPEG_PATH
        cache_dir = ffmpeg_cache_dir()

        marker = read_marker()
        if marker and installed_by_us():
            version = marker.get("ffmpeg_version", "") or "未知版本"
            ts = marker.get("installed_at", "")
            size_h = _human_bytes(cache_size_bytes())
            status = (
                f"✓ 由本程序自动下载\n"
                f"  版本: {version}\n"
                f"  位置: {cache_dir}\n"
                f"  大小: {size_h}\n"
                f"  下载于: {ts}"
            )
            self.btn_clear_ffmpeg.setEnabled(True)
            self.btn_clear_ffmpeg.setToolTip("安全删除：只移除本程序下载的副本")
        elif ffmpeg_path and os.path.isfile(ffmpeg_path):
            status = (
                f"● 使用系统安装的 FFmpeg\n"
                f"  位置: {ffmpeg_path}\n"
                f"  由于不是本程序下载，不会被“清除”动作触碰。"
            )
            self.btn_clear_ffmpeg.setEnabled(False)
            self.btn_clear_ffmpeg.setToolTip("系统安装的 FFmpeg 不会被删除")
        else:
            status = "✗ 未找到 FFmpeg。下次启动会提示下载或指定路径。"
            self.btn_clear_ffmpeg.setEnabled(False)
            self.btn_clear_ffmpeg.setToolTip("")
        self.ffmpeg_status_label.setText(status)

    # ---- Actions: appearance/conversion tabs -------------------------
    def _browse_bg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", "", "图片 (*.png *.jpg *.jpeg *.bmp *.gif);;所有文件 (*)"
        )
        if path:
            self.bg_path_edit.setText(path)

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", "")
        if path:
            self.output_edit.setText(path)

    # ---- Actions: data tab -------------------------------------------
    def _pick_data_dir(self) -> None:
        start = self.data_dir_edit.text().strip() or str(app_data_dir().parent)
        chosen = QFileDialog.getExistingDirectory(
            self, "选择数据目录的父目录（其下会创建 Vertenda/ 子目录）", start,
        )
        if not chosen:
            return
        if not os.access(chosen, os.W_OK):
            QMessageBox.warning(self, "无法写入", f"{chosen} 不可写。")
            return
        self.data_dir_edit.setText(chosen)

    def _reset_data_dir(self) -> None:
        self.data_dir_edit.clear()

    def _open_data_dir(self) -> None:
        path = str(app_data_dir())
        try:
            os.makedirs(path, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError as exc:
            QMessageBox.warning(self, "打开失败", str(exc))

    def _clear_ffmpeg_cache(self) -> None:
        if not installed_by_us():
            # Defence in depth - button should already be disabled.
            QMessageBox.information(
                self, "无需清理",
                "检测到的 FFmpeg 不是由本程序下载的，不会被删除。",
            )
            return
        reply = QMessageBox.question(
            self, "确认清理",
            f"将删除本程序下载的 FFmpeg 缓存，位于:\n{ffmpeg_cache_dir()}\n\n"
            "下次启动时若还需要 FFmpeg，会提示重新下载或指定路径。继续吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        removed = remove_cache()
        # Re-resolve so the main window no longer points at the now-deleted binary.
        from .. import constants
        constants.FFMPEG_PATH, constants.FFPROBE_PATH = constants.resolve_ffmpeg_paths()
        self._refresh_data_info()
        QMessageBox.information(
            self, "清理完成" if removed else "已是空的",
            "FFmpeg 缓存已移除。" if removed else "缓存目录原本就不存在。",
        )

    # ---- Save --------------------------------------------------------
    def _save(self) -> None:
        s = self.settings
        s.setValue(SettingsKey.BG_PATH, self.bg_path_edit.text().strip())
        s.setValue(SettingsKey.BG_ALPHA, self.bg_alpha_slider.value())
        s.setValue(SettingsKey.OVERLAY_STRENGTH, self.overlay_slider.value())
        s.setValue(SettingsKey.THEME_MODE, self.theme_combo.currentText())
        s.setValue(SettingsKey.FONT_SIZE, self.spin_font_size.value())
        s.setValue(SettingsKey.OUTPUT_PATH, self.output_edit.text().strip())
        s.setValue(SettingsKey.USE_HW_ACCEL, self.check_hw.isChecked())
        s.setValue(SettingsKey.QUALITY_PRESET,
                    self.quality_combo.currentData() or QualityPreset.BALANCED.value)

        new_data_dir = self.data_dir_edit.text().strip()
        old_data_dir = s.value(SettingsKey.CUSTOM_DATA_DIR, "", type=str).strip()
        s.setValue(SettingsKey.CUSTOM_DATA_DIR, new_data_dir)

        # Live-apply the override so the rest of the session uses the new path.
        set_data_dir_override(new_data_dir or None)
        from .. import constants
        constants.FFMPEG_PATH, constants.FFPROBE_PATH = constants.resolve_ffmpeg_paths()
        if new_data_dir != old_data_dir:
            self.data_dir_changed_signal.emit()

        s.setValue(SettingsKey.DEFAULT_CONFLICT_POLICY, self.conflict_combo.currentText())
        s.setValue(SettingsKey.DEFAULT_FILENAME_TEMPLATE, self.filename_edit.text().strip() or "{base}")
        s.setValue(SettingsKey.DEFAULT_MIRROR_SUBDIRS, self.check_mirror.isChecked())
        s.setValue(SettingsKey.DEFAULT_CONTINUE_ON_FAILURE, self.check_continue.isChecked())
        s.setValue(SettingsKey.CONCURRENCY_MODE, self.concurrency_combo.currentText())
        s.setValue(SettingsKey.NOTIFY_ON_COMPLETE, self.check_notify.isChecked())
        s.setValue(SettingsKey.OPEN_OUTPUT_ON_COMPLETE, self.check_open_output.isChecked())

        self.hw_accel_changed_signal.emit(self.check_hw.isChecked())

        if self.check_ctx_menu is not None and win_registry is not None:
            wanted = self.check_ctx_menu.isChecked()
            if wanted != self._original_ctx_enabled:
                self._apply_context_menu_change(wanted)

        self.accept()

    def _apply_context_menu_change(self, enable: bool) -> None:
        """Register or unregister the Windows cascading context menu."""
        assert win_registry is not None
        try:
            if enable:
                exe = _current_executable_path()
                win_registry.register(exe)
            else:
                win_registry.unregister()
            self._original_ctx_enabled = enable
        except (OSError, win_registry.PlatformError, FileNotFoundError) as exc:
            QMessageBox.warning(
                self, "右键集成失败",
                f"无法修改注册表：{exc}\n\n"
                "请检查运行权限，或在命令行手动执行：\n"
                "  Vertenda.exe --gui\n"
                "来确认程序路径可达。",
            )


def _current_executable_path() -> str:
    """Path to use in right-click ``command`` values.

    For frozen (PyInstaller) builds this is ``sys.executable`` itself.
    For dev / source runs, we point at a ``pythonw.exe <project>\\Main.py``
    command so the shell entry still works; but in practice the user will
    only toggle this in a packaged build.
    """
    if getattr(sys, "frozen", False):
        return sys.executable
    # Source checkout fallback: use Main.py via pythonw.
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    main_py = os.path.join(project_root, "Main.py")
    if not os.path.isfile(main_py):
        raise FileNotFoundError(main_py)
    # Return Main.py so win_registry.build_command_line turns it into
    # `"Main.py" convert "%1" -f mp3` - Explorer will run it via its
    # associated interpreter. For a more robust setup the user should
    # trigger this toggle from a PyInstaller build.
    return main_py
