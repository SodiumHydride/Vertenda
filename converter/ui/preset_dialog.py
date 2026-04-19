# -*- coding: utf-8 -*-
"""Preset management dialog: rename, delete, import/export."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ..presets import PresetStore


class PresetManagerDialog(QDialog):
    """Dialog for managing (rename / delete / import / export) presets."""

    def __init__(self, store: PresetStore, tab: str, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.tab = tab
        self.setWindowTitle(f"管理预设 · {tab}")
        self.resize(480, 360)
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(True)
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        btn_rename = QPushButton("重命名")
        btn_rename.clicked.connect(self._rename)
        btn_delete = QPushButton("删除")
        btn_delete.setObjectName("DangerButton")
        btn_delete.clicked.connect(self._delete)
        btn_import = QPushButton("导入…")
        btn_import.clicked.connect(self._import)
        btn_export = QPushButton("导出…")
        btn_export.clicked.connect(self._export)
        btn_row.addWidget(btn_rename)
        btn_row.addWidget(btn_delete)
        btn_row.addStretch()
        btn_row.addWidget(btn_import)
        btn_row.addWidget(btn_export)
        layout.addLayout(btn_row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(self.accept)
        close_row.addWidget(btn_close)
        layout.addLayout(close_row)

    def _refresh(self) -> None:
        self.list_widget.clear()
        for name in self.store.list_names(self.tab):
            self.list_widget.addItem(QListWidgetItem(name))

    def _rename(self) -> None:
        item = self.list_widget.currentItem()
        if not item:
            return
        old_name = item.text()
        new_name, ok = QInputDialog.getText(self, "重命名预设", "新名称:", text=old_name)
        if ok and new_name.strip() and new_name != old_name:
            self.store.rename(old_name, new_name.strip())
            self._refresh()

    def _delete(self) -> None:
        item = self.list_widget.currentItem()
        if not item:
            return
        name = item.text()
        reply = QMessageBox.question(
            self, "确认删除", f"删除预设 "{name}"？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.store.delete(name)
            self._refresh()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入预设", "", "JSON (*.json);;所有文件 (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            count = self.store.import_json(text)
            QMessageBox.information(self, "导入完成", f"已导入 {count} 个预设。")
            self._refresh()
        except OSError as exc:
            QMessageBox.warning(self, "导入失败", str(exc))

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出预设", f"presets_{self.tab}.json",
            "JSON (*.json);;所有文件 (*)",
        )
        if not path:
            return
        try:
            text = self.store.export_all(self.tab)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            QMessageBox.information(self, "导出完成", f"已保存到 {path}")
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
