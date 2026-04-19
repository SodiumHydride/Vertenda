# -*- coding: utf-8 -*-
"""Custom QListWidget: drag-in files, right-click menu, O(1) dedup, file size hint."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

from PyQt5.QtCore import QFileInfo, QSize, Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFileIconProvider,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
)


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    value = float(num_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


@dataclass
class CustomAction:
    """Extra right-click menu item injected by the main window.

    `label`   - menu text
    `handler` - called with the list of selected paths
    `enabled` - optional predicate to gate enablement
    """
    label: str
    handler: Callable[[list[str]], None]
    enabled: Callable[[list[str]], bool] | None = None


class FileListWidget(QListWidget):
    """List widget with drag-drop, O(1) dedup via a path cache, and context menu."""

    def __init__(self, placeholder: str = "拖拽文件到这里 · 或点击下方按钮添加", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._paths: set[str] = set()
        self._icon_provider = QFileIconProvider()
        self._custom_actions: list[CustomAction] = []

        self.setAcceptDrops(True)
        self.setDragEnabled(False)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setIconSize(QSize(18, 18))
        self.setUniformItemSizes(False)
        self.setAlternatingRowColors(False)

        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

    # ---- Public API ---------------------------------------------------
    def add_path(self, path: str) -> bool:
        path = os.path.abspath(path)
        if path in self._paths:
            return False
        if not os.path.isfile(path):
            return False
        self._paths.add(path)
        item = QListWidgetItem(self._format_label(path))
        item.setData(Qt.UserRole, path)
        item.setIcon(self._icon_for(path))
        item.setToolTip(path)
        self.addItem(item)
        return True

    def add_many(self, paths: list[str]) -> tuple[int, int]:
        """Return (added, duplicates)."""
        added = 0
        for p in paths:
            if self.add_path(p):
                added += 1
        return added, len(paths) - added

    def add_directory(self, directory: str, extensions: frozenset[str] | None = None,
                        recursive: bool = True) -> tuple[int, int]:
        """Scan `directory` for files, optionally filtered by extensions."""
        collected: list[str] = []
        if recursive:
            walker = os.walk(directory)
            for root, _dirs, files in walker:
                for name in files:
                    if extensions is None or os.path.splitext(name)[1].lower() in extensions:
                        collected.append(os.path.join(root, name))
        else:
            for name in os.listdir(directory):
                full = os.path.join(directory, name)
                if os.path.isfile(full):
                    if extensions is None or os.path.splitext(name)[1].lower() in extensions:
                        collected.append(full)
        collected.sort()
        return self.add_many(collected)

    def remove_selected(self) -> int:
        removed = 0
        for item in self.selectedItems():
            path = item.data(Qt.UserRole)
            self._paths.discard(path)
            self.takeItem(self.row(item))
            removed += 1
        return removed

    def clear_all(self) -> None:
        self._paths.clear()
        self.clear()

    def all_paths(self) -> list[str]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())]

    def selected_paths(self) -> list[str]:
        return [item.data(Qt.UserRole) for item in self.selectedItems()]

    def register_action(self, action: CustomAction) -> None:
        """Main-window-injected menu entries (e.g. 'send to burn tab')."""
        self._custom_actions.append(action)

    # ---- Rendering helpers -------------------------------------------
    def _format_label(self, path: str) -> str:
        try:
            size = os.path.getsize(path)
            return f"{os.path.basename(path)}   ·   {_format_size(size)}"
        except OSError:
            return os.path.basename(path)

    def _icon_for(self, path: str) -> QIcon:
        info = QFileInfo(path)
        return self._icon_provider.icon(info)

    def paintEvent(self, event):  # noqa: N802 (Qt override)
        super().paintEvent(event)
        if self.count() == 0:
            from PyQt5.QtGui import QColor, QPainter
            painter = QPainter(self.viewport())
            painter.setPen(QColor(155, 155, 170))
            painter.drawText(self.viewport().rect(), Qt.AlignCenter, self._placeholder)
            painter.end()

    # ---- Drag & drop --------------------------------------------------
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
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            if os.path.isdir(local):
                self.add_directory(local)
            else:
                self.add_path(local)

    # ---- Context menu -------------------------------------------------
    def _show_menu(self, pos):
        menu = QMenu(self)
        selected = self.selected_paths()

        act_open = menu.addAction("打开文件位置")
        act_open.setEnabled(self.currentItem() is not None)

        act_remove = menu.addAction("从列表移除")
        act_remove.setEnabled(bool(selected))

        act_clear = menu.addAction("清空列表")
        act_clear.setEnabled(self.count() > 0)

        custom_pairs: list[tuple[object, CustomAction]] = []
        if self._custom_actions:
            menu.addSeparator()
            for custom in self._custom_actions:
                item = menu.addAction(custom.label)
                if custom.enabled is None:
                    item.setEnabled(bool(selected))
                else:
                    item.setEnabled(custom.enabled(selected))
                custom_pairs.append((item, custom))

        chosen = menu.exec_(self.viewport().mapToGlobal(pos))
        if chosen is None:
            return
        if chosen is act_open:
            self._open_location()
        elif chosen is act_remove:
            self.remove_selected()
        elif chosen is act_clear:
            self.clear_all()
        else:
            for item, custom in custom_pairs:
                if item is chosen:
                    custom.handler(selected)
                    break

    def _open_location(self):
        item = self.currentItem()
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if not path or not os.path.exists(path):
            return
        folder = os.path.dirname(path)
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except OSError as exc:
            QMessageBox.warning(self, "无法打开", f"打开文件位置失败: {exc}")
