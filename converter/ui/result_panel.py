# -*- coding: utf-8 -*-
"""Post-conversion result panel: success / failed / skipped breakdown."""

from __future__ import annotations

import os
import subprocess
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..queue import FileResult, FileStatus


class ResultPanel(QDialog):
    """Modal dialog showing structured conversion results."""

    retry_requested = None  # set by caller if retry is supported

    def __init__(self, results: list[FileResult], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("转换结果")
        self.resize(800, 520)
        self.results = results

        self._success = [r for r in results if r.status == FileStatus.SUCCESS]
        self._failed = [r for r in results if r.status == FileStatus.FAILED]
        self._skipped = [r for r in results if r.status in (FileStatus.SKIPPED, FileStatus.CANCELLED)]

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        summary = QLabel(
            f"成功 {len(self._success)}  ·  "
            f"失败 {len(self._failed)}  ·  "
            f"跳过 {len(self._skipped)}  ·  "
            f"总计 {len(self.results)}"
        )
        summary.setStyleSheet("font-size: 14px; font-weight: 600; padding: 4px;")
        layout.addWidget(summary)

        tabs = QTabWidget()
        if self._success:
            tabs.addTab(
                self._build_table(self._success, show_output=True),
                f"成功 ({len(self._success)})",
            )
        if self._failed:
            tabs.addTab(
                self._build_table(self._failed, show_reason=True),
                f"失败 ({len(self._failed)})",
            )
        if self._skipped:
            tabs.addTab(
                self._build_table(self._skipped, show_reason=True),
                f"跳过 ({len(self._skipped)})",
            )
        layout.addWidget(tabs, 1)

        btn_row = QHBoxLayout()
        if self._failed:
            btn_retry = QPushButton("重试失败项")
            btn_retry.setObjectName("PrimaryButton")
            btn_retry.clicked.connect(self._retry_failed)
            btn_row.addWidget(btn_retry)

            btn_copy = QPushButton("复制失败日志")
            btn_copy.clicked.connect(self._copy_failures)
            btn_row.addWidget(btn_copy)

        if self._success:
            btn_open = QPushButton("打开输出目录")
            btn_open.clicked.connect(self._open_outputs)
            btn_row.addWidget(btn_open)

        btn_row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

    def _build_table(
        self, items: list[FileResult], *, show_output: bool = False, show_reason: bool = False,
    ) -> QWidget:
        cols = ["源文件", "耗时"]
        if show_output:
            cols.append("输出路径")
        if show_reason:
            cols.append("原因")

        table = QTableWidget(len(items), len(cols))
        table.setHorizontalHeaderLabels(cols)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setAlternatingRowColors(True)

        for row, r in enumerate(items):
            table.setItem(row, 0, QTableWidgetItem(os.path.basename(r.source)))
            table.item(row, 0).setToolTip(r.source)
            elapsed = f"{r.elapsed_s:.1f}s" if r.elapsed_s else "-"
            table.setItem(row, 1, QTableWidgetItem(elapsed))
            col = 2
            if show_output:
                table.setItem(row, col, QTableWidgetItem(r.output))
                table.item(row, col).setToolTip(r.output)
                col += 1
            if show_reason:
                table.setItem(row, col, QTableWidgetItem(r.reason))

        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(table)
        return w

    def _retry_failed(self) -> None:
        if self.retry_requested is not None:
            failed_paths = [r.source for r in self._failed if r.source]
            self.retry_requested(failed_paths)
        self.accept()

    def _copy_failures(self) -> None:
        lines = []
        for r in self._failed:
            lines.append(f"{r.source}")
            if r.reason:
                lines.append(f"  原因: {r.reason}")
            lines.append("")
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText("\n".join(lines))

    def _open_outputs(self) -> None:
        dirs_opened: set[str] = set()
        for r in self._success:
            if not r.output:
                continue
            d = os.path.dirname(r.output)
            if d in dirs_opened:
                continue
            dirs_opened.add(d)
            try:
                if sys.platform == "win32":
                    os.startfile(d)  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", d])
                else:
                    subprocess.Popen(["xdg-open", d])
            except OSError:
                pass

    def failed_paths(self) -> list[str]:
        return [r.source for r in self._failed if r.source]
