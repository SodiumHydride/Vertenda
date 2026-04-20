# -*- coding: utf-8 -*-
"""Startup helper: prompt for ffmpeg when the app cannot find any.

The whole point is to keep the user's system clean: we download ffmpeg into
the app's own data directory instead of touching PATH or installing globally.
Uninstall = delete the app data folder. No admin privileges required.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from .. import constants
from ..constants import SettingsKey
from ..ffmpeg.installer import (
    InstallError,
    app_data_dir,
    cached_binary_paths,
    ffmpeg_cache_dir,
    install_bundle,
    remove_cache,
    set_data_dir_override,
)


class _InstallThread(QThread):
    progress_signal = pyqtSignal(int, int)   # bytes_read, total
    status_signal = pyqtSignal(str)          # human-readable stage label
    finished_signal = pyqtSignal(bool, str)  # success, message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancel = threading.Event()

    def request_cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            install_bundle(
                on_progress=lambda r, t: self.progress_signal.emit(r, t),
                on_status=lambda s: self.status_signal.emit(s),
                cancel_flag=self._cancel,
            )
        except InstallError as exc:
            self.finished_signal.emit(False, str(exc))
            return
        except Exception as exc:  # Defensive - never crash the GUI thread.
            self.finished_signal.emit(False, f"内部错误: {exc}")
            return
        self.finished_signal.emit(True, "")


class FirstRunDialog(QDialog):
    """Shown on launch when `_resolve_executable` came up empty.

    Resolution paths:
      * auto-download into app data dir
      * user-supplied file dialog pointing at an existing ffmpeg binary
      * copy that user choice into app data dir too, so `ffprobe` alongside it is picked up
      * abort startup
    """

    SUCCESS = 1
    ABORTED = 0

    def __init__(self, settings=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("首次启动 · 需要 FFmpeg")
        self.setModal(True)
        self.resize(620, 400)
        self._thread: _InstallThread | None = None
        self._result_status = self.ABORTED
        self._settings = settings  # optional QSettings to persist custom path
        self._build_ui()

    # ---- UI -----------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(10)

        title = QLabel("找不到可用的 FFmpeg")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        body = QLabel(
            "本程序需要 FFmpeg 来处理音视频。\n"
            "我们会把二进制文件下载到下方显示的目录，不会写入系统 PATH 或其它位置。\n"
            "将来要清理，只需要删掉那个目录即可。\n\n"
            "如果你已经装过 FFmpeg（brew / gyan.dev / 手动编译），可以直接指定路径。"
        )
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(body)

        # Download location row.
        loc_row = QHBoxLayout()
        loc_row.setSpacing(8)
        loc_row.addWidget(QLabel("下载位置:"))
        self.location_label = QLabel(str(ffmpeg_cache_dir()))
        self.location_label.setStyleSheet("color: #888;")
        self.location_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.location_label.setWordWrap(True)
        loc_row.addWidget(self.location_label, 1)
        self.btn_change_location = QPushButton("更改…")
        self.btn_change_location.clicked.connect(self._pick_data_dir)
        loc_row.addWidget(self.btn_change_location)
        layout.addLayout(loc_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)   # permille for smoother updates
        self.progress.setValue(0)
        self.progress.setFormat("%p%")
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #888;")
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        layout.addStretch()

        row = QHBoxLayout()
        self.btn_download = QPushButton("自动下载（推荐）")
        self.btn_download.setDefault(True)
        self.btn_download.clicked.connect(self._start_download)

        self.btn_browse = QPushButton("指定已有 FFmpeg…")
        self.btn_browse.clicked.connect(self._pick_existing)

        self.btn_quit = QPushButton("退出")
        self.btn_quit.clicked.connect(self.reject)

        row.addWidget(self.btn_download)
        row.addWidget(self.btn_browse)
        row.addStretch()
        row.addWidget(self.btn_quit)
        layout.addLayout(row)

    # ---- Auto download ------------------------------------------------
    def _start_download(self) -> None:
        self._lock_buttons(True)
        self.progress.setVisible(True)
        self.status_label.setVisible(True)
        self.status_label.setText("连接下载源…")

        self._thread = _InstallThread(self)
        self._thread.progress_signal.connect(self._on_progress)
        self._thread.status_signal.connect(self.status_label.setText)
        self._thread.finished_signal.connect(self._on_finished)
        self._thread.start()

        # Repurpose the quit button as a cancel during the download.
        self.btn_quit.setEnabled(True)
        self.btn_quit.setText("取消下载")
        self.btn_quit.clicked.disconnect()
        self.btn_quit.clicked.connect(self._cancel_download)

    def _cancel_download(self) -> None:
        if self._thread is not None:
            self._thread.request_cancel()
            self.status_label.setText("已请求取消，正在等待…")

    def _on_progress(self, read: int, total: int) -> None:
        if total <= 0:
            self.progress.setRange(0, 0)  # indeterminate
            return
        self.progress.setRange(0, total)
        self.progress.setValue(read)

    def _on_finished(self, ok: bool, message: str) -> None:
        self._thread = None
        if ok:
            self.status_label.setText("✓ 下载并安装完成")
            self._result_status = self.SUCCESS
            QThread.msleep(400)  # brief pause so user sees the success state
            self.accept()
            return
        # Failure: restore the dialog so user can retry or switch to manual.
        QMessageBox.warning(self, "下载失败", message)
        self.progress.setVisible(False)
        self.status_label.setText(f"失败: {message}")
        self._lock_buttons(False)
        self.btn_quit.setText("退出")
        try:
            self.btn_quit.clicked.disconnect()
        except TypeError:
            pass
        self.btn_quit.clicked.connect(self.reject)
        # Best-effort cleanup of a partial cache.
        remove_cache()

    # ---- Manual path --------------------------------------------------
    def _pick_existing(self) -> None:
        exe_filter = "ffmpeg executable (ffmpeg ffmpeg.exe);;所有文件 (*)"
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 ffmpeg 可执行文件", str(Path.home()), exe_filter,
        )
        if not path:
            return
        path = os.path.abspath(path)
        if not self._probe(path):
            QMessageBox.warning(
                self, "不是可用的 FFmpeg",
                f"{path}\n\n运行 `-version` 失败。请确认选中的是正确的 FFmpeg 二进制文件。",
            )
            return

        # Derive ffprobe path. Expect it to live next to ffmpeg.
        basename = os.path.basename(path).lower()
        if basename.startswith("ffmpeg"):
            probe_name = basename.replace("ffmpeg", "ffprobe", 1)
            probe_path = os.path.join(os.path.dirname(path), probe_name)
        else:
            probe_path = ""
        if not probe_path or not self._probe(probe_path):
            probe_chosen, _ = QFileDialog.getOpenFileName(
                self, "选择对应的 ffprobe", os.path.dirname(path),
                "ffprobe executable (ffprobe ffprobe.exe);;所有文件 (*)",
            )
            if not probe_chosen or not self._probe(probe_chosen):
                QMessageBox.warning(
                    self, "未提供 ffprobe",
                    "需要 ffprobe 才能读取媒体时长和分辨率。请同时指定。",
                )
                return
            probe_path = probe_chosen

        # Copy both into the cache dir so next launch we find them automatically.
        try:
            self._link_into_cache(path, probe_path)
        except OSError as exc:
            QMessageBox.warning(
                self, "写入缓存失败",
                f"无法把 FFmpeg 复制到应用数据目录：{exc}",
            )
            return

        self._result_status = self.SUCCESS
        self.accept()

    def _link_into_cache(self, ffmpeg_path: str, ffprobe_path: str) -> None:
        cache = ffmpeg_cache_dir()
        cache.mkdir(parents=True, exist_ok=True)
        ff, fp = cached_binary_paths()
        # Copy (rather than symlink) so sandboxing and path-based security on
        # Windows / signed .app bundles keep working.
        import shutil
        shutil.copy2(ffmpeg_path, ff)
        shutil.copy2(ffprobe_path, fp)
        if sys.platform != "win32":
            for p in (ff, fp):
                mode = p.stat().st_mode
                p.chmod(mode | 0o111)

    # ---- helpers ------------------------------------------------------
    def _probe(self, path: str) -> bool:
        import subprocess
        try:
            cp = subprocess.run(
                [path, "-version"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4,
            )
            return cp.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _lock_buttons(self, locked: bool) -> None:
        self.btn_download.setEnabled(not locked)
        self.btn_browse.setEnabled(not locked)
        self.btn_change_location.setEnabled(not locked)

    # ---- Data directory override -------------------------------------
    def _pick_data_dir(self) -> None:
        current = str(app_data_dir().parent)  # default parent (excluding "Vertenda")
        chosen = QFileDialog.getExistingDirectory(
            self, "选择下载位置的父目录（其下会新建 Vertenda/ 子目录）", current,
        )
        if not chosen:
            return
        if not os.access(chosen, os.W_OK):
            QMessageBox.warning(
                self, "无法写入",
                f"{chosen} 不可写。请选一个你有权限的目录。",
            )
            return
        set_data_dir_override(chosen)
        if self._settings is not None:
            self._settings.setValue(SettingsKey.CUSTOM_DATA_DIR, chosen)
            self._settings.sync()
        self.location_label.setText(str(ffmpeg_cache_dir()))

    # ---- Result ------------------------------------------------------
    @property
    def succeeded(self) -> bool:
        return self._result_status == self.SUCCESS
