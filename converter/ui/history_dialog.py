# -*- coding: utf-8 -*-
"""Task history dialog: view recent conversions, replay."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..history import HistoryRecord, TaskHistory


class HistoryDialog(QDialog):
    """Shows the last N conversion records with a 'replay' button."""

    replay_requested = None  # callback: Callable[[HistoryRecord], None]

    def __init__(self, history: TaskHistory, parent=None) -> None:
        super().__init__(parent)
        self.history = history
        self.setWindowTitle("任务历史")
        self.resize(700, 460)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        records = self.history.records
        if not records:
            layout.addWidget(QLabel("暂无历史记录。"))
            return

        cols = ["时间", "类型", "格式", "文件数", "成功", "失败", "跳过", "耗时", "预设"]
        self.table = QTableWidget(len(records), len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)

        for row, rec in enumerate(reversed(records)):
            self.table.setItem(row, 0, QTableWidgetItem(rec.timestamp[:16]))
            self.table.setItem(row, 1, QTableWidgetItem(rec.task_kind))
            self.table.setItem(row, 2, QTableWidgetItem(rec.target_format))
            self.table.setItem(row, 3, QTableWidgetItem(str(rec.file_count)))
            self.table.setItem(row, 4, QTableWidgetItem(str(rec.success_count)))
            self.table.setItem(row, 5, QTableWidgetItem(str(rec.fail_count)))
            self.table.setItem(row, 6, QTableWidgetItem(str(rec.skip_count)))
            elapsed = int(rec.duration_s)
            m, s = divmod(elapsed, 60)
            self.table.setItem(row, 7, QTableWidgetItem(f"{m}m{s:02d}s"))
            self.table.setItem(row, 8, QTableWidgetItem(rec.preset_name or "-"))

        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("清空历史")
        btn_clear.setObjectName("DangerButton")
        btn_clear.clicked.connect(self._clear)
        btn_row.addWidget(btn_clear)
        btn_row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _clear(self) -> None:
        reply = QMessageBox.question(
            self, "确认", "清空所有历史记录？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.history.clear()
            self.accept()
