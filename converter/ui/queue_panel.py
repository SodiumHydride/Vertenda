# -*- coding: utf-8 -*-
"""Queue management panel: shows pending/running tasks with reorder and control."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..queue import TaskCoordinator, TaskQueue
from ..worker import ConvertTask, TaskKind


def _task_label(task: ConvertTask) -> str:
    kind_map = {
        TaskKind.AUDIO: "音频",
        TaskKind.VIDEO: "视频",
        TaskKind.SUBTITLE: "字幕",
        TaskKind.BURN: "烧录",
    }
    kind = kind_map.get(task.kind, "?")
    fmt = task.target_format or "?"
    n = len(task.files)
    if task.burn:
        return f"[{kind}] {fmt} · 烧录任务"
    return f"[{kind}] → {fmt} · {n} 个文件"


class QueuePanel(QWidget):
    """Collapsible side panel showing the task queue."""

    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    skip_requested = pyqtSignal()
    cancel_all_requested = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._coordinator: TaskCoordinator | None = None
        self._build_ui()

    def set_coordinator(self, coord: TaskCoordinator) -> None:
        self._coordinator = coord

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QLabel("任务队列")
        header.setStyleSheet("font-weight: 600; font-size: 13px;")
        layout.addWidget(header)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        layout.addWidget(self.list_widget, 1)

        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)
        self.btn_pause = QPushButton("暂停")
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_skip = QPushButton("跳过当前")
        self.btn_skip.clicked.connect(self.skip_requested.emit)
        self.btn_cancel = QPushButton("取消全部")
        self.btn_cancel.setObjectName("DangerButton")
        self.btn_cancel.clicked.connect(self.cancel_all_requested.emit)
        ctrl.addWidget(self.btn_pause)
        ctrl.addWidget(self.btn_skip)
        ctrl.addWidget(self.btn_cancel)
        layout.addLayout(ctrl)

        reorder = QHBoxLayout()
        reorder.setSpacing(6)
        self.btn_up = QPushButton("上移")
        self.btn_up.clicked.connect(self._move_up)
        self.btn_down = QPushButton("下移")
        self.btn_down.clicked.connect(self._move_down)
        self.btn_remove = QPushButton("移除")
        self.btn_remove.clicked.connect(self._remove)
        self.btn_clear = QPushButton("清空")
        self.btn_clear.clicked.connect(self._clear)
        reorder.addWidget(self.btn_up)
        reorder.addWidget(self.btn_down)
        reorder.addWidget(self.btn_remove)
        reorder.addWidget(self.btn_clear)
        layout.addLayout(reorder)

        self._paused = False

    def refresh(self) -> None:
        """Rebuild the list from the coordinator's queue."""
        self.list_widget.clear()
        if self._coordinator is None:
            return
        for task in self._coordinator.queue.pending:
            item = QListWidgetItem(_task_label(task))
            self.list_widget.addItem(item)

    def set_running(self, running: bool) -> None:
        self.btn_pause.setEnabled(running)
        self.btn_skip.setEnabled(running)
        self.btn_cancel.setEnabled(running)

    def _on_pause(self) -> None:
        if self._paused:
            self.resume_requested.emit()
            self.btn_pause.setText("暂停")
            self._paused = False
        else:
            self.pause_requested.emit()
            self.btn_pause.setText("继续")
            self._paused = True

    def _move_up(self) -> None:
        row = self.list_widget.currentRow()
        if row > 0 and self._coordinator:
            self._coordinator.queue.move_up(row)
            self.refresh()
            self.list_widget.setCurrentRow(row - 1)

    def _move_down(self) -> None:
        row = self.list_widget.currentRow()
        if row >= 0 and self._coordinator:
            self._coordinator.queue.move_down(row)
            self.refresh()
            self.list_widget.setCurrentRow(row + 1)

    def _remove(self) -> None:
        row = self.list_widget.currentRow()
        if row >= 0 and self._coordinator:
            self._coordinator.queue.remove_pending(row)
            self.refresh()

    def _clear(self) -> None:
        if self._coordinator:
            self._coordinator.queue.clear()
            self.refresh()
