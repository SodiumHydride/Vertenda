# -*- coding: utf-8 -*-
"""Pre-flight estimation dialog: shows total duration, size, conflicts, disk status."""

from __future__ import annotations

import os

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..estimator import EstimateReport
from ..fs import ConflictPolicy


class EstimateDialog(QDialog):
    """Shows a pre-flight summary and lets the user confirm or adjust conflict policy."""

    def __init__(self, report: EstimateReport, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("任务预估")
        self.resize(620, 420)
        self.report = report
        self.chosen_conflict: ConflictPolicy | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        headline = QLabel(
            f"即将处理 {self.report.files_total} 个文件\n"
            f"总时长 {self.report.duration_display}  ·  "
            f"预计输出 ~{self.report.size_display}"
        )
        headline.setStyleSheet("font-size: 15px; font-weight: 600;")
        headline.setWordWrap(True)
        layout.addWidget(headline)

        note = QLabel("预计输出体积为粗估值（±30%），实际大小取决于源素材复杂度。")
        note.setStyleSheet("color: #888; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        if self.report.conflicts:
            conflict_label = QLabel(f"检测到 {len(self.report.conflicts)} 个同名冲突:")
            conflict_label.setStyleSheet("font-weight: 600; color: #e8a838;")
            layout.addWidget(conflict_label)

            table = QTableWidget(min(len(self.report.conflicts), 50), 2)
            table.setHorizontalHeaderLabels(["源文件", "将覆盖"])
            table.horizontalHeader().setStretchLastSection(True)
            table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            table.setEditTriggers(QTableWidget.NoEditTriggers)
            table.setMaximumHeight(150)
            for row, (src, tgt) in enumerate(self.report.conflicts[:50]):
                table.setItem(row, 0, QTableWidgetItem(os.path.basename(src)))
                table.item(row, 0).setToolTip(src)
                table.setItem(row, 1, QTableWidgetItem(os.path.basename(tgt)))
                table.item(row, 1).setToolTip(tgt)
            layout.addWidget(table)

            conflict_row = QHBoxLayout()
            conflict_row.addWidget(QLabel("冲突处理:"))
            btn_skip = QPushButton("全部跳过")
            btn_skip.clicked.connect(lambda: self._set_conflict(ConflictPolicy.SKIP))
            btn_overwrite = QPushButton("全部覆盖")
            btn_overwrite.clicked.connect(lambda: self._set_conflict(ConflictPolicy.OVERWRITE))
            btn_rename = QPushButton("全部重命名")
            btn_rename.clicked.connect(lambda: self._set_conflict(ConflictPolicy.RENAME))
            conflict_row.addWidget(btn_skip)
            conflict_row.addWidget(btn_overwrite)
            conflict_row.addWidget(btn_rename)
            conflict_row.addStretch()
            layout.addLayout(conflict_row)

            self._conflict_status = QLabel("当前选择: 询问时再决定")
            self._conflict_status.setStyleSheet("color: #888; font-size: 11px;")
            layout.addWidget(self._conflict_status)

        if self.report.disk_warn:
            warn = QLabel(
                f"磁盘空间可能不足！\n"
                f"预计需要 ~{self.report.size_display}，"
                f"目标盘剩余 {self.report.free_display}。"
            )
            warn.setStyleSheet(
                "color: #ff4444; font-weight: 600; "
                "background: rgba(255, 68, 68, 30); "
                "border-radius: 6px; padding: 10px;"
            )
            warn.setWordWrap(True)
            layout.addWidget(warn)

        disk_info = QLabel(f"目标磁盘剩余: {self.report.free_display}")
        disk_info.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(disk_info)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_start = QPushButton("开始")
        btn_start.setObjectName("PrimaryButton")
        btn_start.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_start)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _set_conflict(self, policy: ConflictPolicy) -> None:
        self.chosen_conflict = policy
        names = {
            ConflictPolicy.SKIP: "全部跳过",
            ConflictPolicy.OVERWRITE: "全部覆盖",
            ConflictPolicy.RENAME: "全部重命名",
        }
        if hasattr(self, "_conflict_status"):
            self._conflict_status.setText(f"当前选择: {names.get(policy, str(policy))}")
