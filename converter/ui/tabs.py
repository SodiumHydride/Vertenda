# -*- coding: utf-8 -*-
"""Tab page builders. Each returns a handles object so the main window can
wire up signals without owning the layout code.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QStandardItem, QStandardItemModel
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..constants import BURN_OUTPUT_FORMATS
from ..format_meta import (
    AUDIO_FORMAT_INFO,
    SUBTITLE_FORMAT_INFO,
    VIDEO_FORMAT_INFO,
    FormatInfo,
    MediaKind,
    format_display_text,
)
from .file_list import FileListWidget


# -- Rich format combobox helpers -------------------------------------------

_FORMAT_KEY_ROLE = Qt.UserRole + 1
_FORMAT_ROLE_HEADER = Qt.UserRole + 2


def _populate_format_combo(combo: QComboBox, infos: tuple[FormatInfo, ...]) -> None:
    """Add items from `infos`, using userData to store the raw format key."""
    model = QStandardItemModel(combo)
    for info in infos:
        item = QStandardItem(format_display_text(info))
        item.setData(info.key, _FORMAT_KEY_ROLE)
        item.setToolTip(info.summary)
        model.appendRow(item)
    combo.setModel(model)
    combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)


def _add_separator(combo: QComboBox, caption: str) -> None:
    """Append a disabled header item to visually group the combo list."""
    model = combo.model()
    item = QStandardItem(f"— {caption} —")
    item.setFlags(Qt.NoItemFlags)
    item.setData(True, _FORMAT_ROLE_HEADER)
    item.setToolTip("")
    item.setData("", _FORMAT_KEY_ROLE)
    model.appendRow(item)


def format_combo_current_key(combo: QComboBox) -> str:
    """Return the format key for the currently selected row."""
    idx = combo.currentIndex()
    if idx < 0:
        return ""
    return combo.itemData(idx, _FORMAT_KEY_ROLE) or ""


def format_combo_set_key(combo: QComboBox, key: str) -> None:
    """Select the row matching `key` if present; keep current selection otherwise."""
    if not key:
        return
    for i in range(combo.count()):
        if combo.itemData(i, _FORMAT_KEY_ROLE) == key:
            combo.setCurrentIndex(i)
            return


# -- Common section helpers --------------------------------------------------

def _section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    label.setStyleSheet("font-weight: 600; font-size: 13px; padding: 2px 2px 4px 2px;")
    return label


def _file_list_button_row(btn_add: QPushButton, btn_add_dir: QPushButton,
                           btn_remove: QPushButton, btn_clear: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(btn_add)
    row.addWidget(btn_add_dir)
    row.addWidget(btn_remove)
    row.addWidget(btn_clear)
    row.addStretch()
    return row


# -- Handle dataclasses ------------------------------------------------------

@dataclass
class AudioTabHandles:
    widget: QWidget
    format_combo: QComboBox
    file_list: FileListWidget
    btn_add: QPushButton
    btn_add_dir: QPushButton
    btn_remove: QPushButton
    btn_clear: QPushButton


@dataclass
class VideoTabHandles:
    widget: QWidget
    format_combo: QComboBox
    file_list: FileListWidget
    check_merge: QCheckBox
    btn_add: QPushButton
    btn_add_dir: QPushButton
    btn_remove: QPushButton
    btn_clear: QPushButton


@dataclass
class SubtitleTabHandles:
    widget: QWidget
    format_combo: QComboBox
    file_list: FileListWidget
    btn_add: QPushButton
    btn_add_dir: QPushButton
    btn_remove: QPushButton
    btn_clear: QPushButton


@dataclass
class BurnTabHandles:
    widget: QWidget
    video_list: FileListWidget
    subtitle_list: FileListWidget
    mode_combo: QComboBox
    output_format_combo: QComboBox
    hint_label: QLabel
    btn_add_video: QPushButton
    btn_add_subtitle: QPushButton
    btn_remove_video: QPushButton
    btn_remove_subtitle: QPushButton


# -- Builders ---------------------------------------------------------------

def build_audio_tab() -> AudioTabHandles:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(10)

    layout.addWidget(_section_title("输出格式"))
    combo = QComboBox()
    _populate_format_combo(combo, AUDIO_FORMAT_INFO)
    layout.addWidget(combo)

    layout.addWidget(_section_title("待转换音频文件"))
    lst = FileListWidget("拖拽音频文件到这里 · 支持 mp3 / wav / flac / aac / ogg / opus 等")
    layout.addWidget(lst, stretch=1)

    btn_add = QPushButton("添加文件")
    btn_add_dir = QPushButton("从目录添加")
    btn_remove = QPushButton("移除选中")
    btn_clear = QPushButton("清空")
    layout.addLayout(_file_list_button_row(btn_add, btn_add_dir, btn_remove, btn_clear))

    return AudioTabHandles(w, combo, lst, btn_add, btn_add_dir, btn_remove, btn_clear)


def build_video_tab() -> VideoTabHandles:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(10)

    layout.addWidget(_section_title("输出格式"))
    combo = QComboBox()
    _populate_format_combo(combo, VIDEO_FORMAT_INFO)
    # Let users strip out audio-only outputs from this tab too, so they don't
    # have to mentally switch tabs just to extract sound.
    _add_separator(combo, "仅提取音频")
    _populate_audio_only_items(combo, AUDIO_FORMAT_INFO)
    layout.addWidget(combo)

    layout.addWidget(_section_title("待处理视频文件"))
    lst = FileListWidget("拖拽视频文件到这里 · 支持 mp4 / mkv / mov / avi / webm 等")
    layout.addWidget(lst, stretch=1)

    check_merge = QCheckBox("合并音视频 (取列表中首个音频和首个视频文件)")
    layout.addWidget(check_merge)

    btn_add = QPushButton("添加文件")
    btn_add_dir = QPushButton("从目录添加")
    btn_remove = QPushButton("移除选中")
    btn_clear = QPushButton("清空")
    layout.addLayout(_file_list_button_row(btn_add, btn_add_dir, btn_remove, btn_clear))

    return VideoTabHandles(w, combo, lst, check_merge, btn_add, btn_add_dir, btn_remove, btn_clear)


def _populate_audio_only_items(combo: QComboBox, infos: tuple[FormatInfo, ...]) -> None:
    """Append audio formats as 'audio-only' choices on the video tab."""
    model = combo.model()
    for info in infos:
        label = f"   仅音频 · {info.label}  ·  {info.summary}"
        item = QStandardItem(label)
        item.setData(info.key, _FORMAT_KEY_ROLE)
        item.setToolTip(f"从视频中提取音频，输出为 {info.label}")
        model.appendRow(item)


def build_subtitle_tab() -> SubtitleTabHandles:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(10)

    layout.addWidget(_section_title("目标格式"))
    combo = QComboBox()
    _populate_format_combo(combo, SUBTITLE_FORMAT_INFO)
    layout.addWidget(combo)

    layout.addWidget(_section_title("待转换字幕文件"))
    lst = FileListWidget("拖拽字幕文件到这里 · 支持 srt / vtt / ass / ssa / lrc 互转")
    layout.addWidget(lst, stretch=1)

    btn_add = QPushButton("添加文件")
    btn_add_dir = QPushButton("从目录添加")
    btn_remove = QPushButton("移除选中")
    btn_clear = QPushButton("清空")
    layout.addLayout(_file_list_button_row(btn_add, btn_add_dir, btn_remove, btn_clear))

    return SubtitleTabHandles(w, combo, lst, btn_add, btn_add_dir, btn_remove, btn_clear)


def build_burn_tab() -> BurnTabHandles:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(14, 14, 14, 14)
    layout.setSpacing(10)

    top = QHBoxLayout()
    top.setSpacing(12)

    col_video = QVBoxLayout()
    col_video.addWidget(_section_title("视频文件 (仅取第一个)"))
    video_list = FileListWidget("拖拽视频文件到这里")
    col_video.addWidget(video_list, stretch=1)
    row_v = QHBoxLayout()
    btn_add_v = QPushButton("添加视频")
    btn_rm_v = QPushButton("移除")
    row_v.addWidget(btn_add_v)
    row_v.addWidget(btn_rm_v)
    row_v.addStretch()
    col_video.addLayout(row_v)

    col_sub = QVBoxLayout()
    col_sub.addWidget(_section_title("字幕文件 (仅取第一个)"))
    sub_list = FileListWidget("拖拽字幕文件到这里")
    col_sub.addWidget(sub_list, stretch=1)
    row_s = QHBoxLayout()
    btn_add_s = QPushButton("添加字幕")
    btn_rm_s = QPushButton("移除")
    row_s.addWidget(btn_add_s)
    row_s.addWidget(btn_rm_s)
    row_s.addStretch()
    col_sub.addLayout(row_s)

    top.addLayout(col_video, stretch=1)
    top.addLayout(col_sub, stretch=1)
    layout.addLayout(top, stretch=1)

    opts = QHBoxLayout()
    opts.addWidget(QLabel("烧录模式:"))
    mode_combo = QComboBox()
    mode_combo.addItems(["硬编码", "软封装"])
    mode_combo.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
    opts.addWidget(mode_combo, 1)
    opts.addSpacing(16)
    opts.addWidget(QLabel("输出格式:"))
    fmt_combo = QComboBox()
    fmt_combo.addItems(list(BURN_OUTPUT_FORMATS))
    fmt_combo.setCurrentText("mkv")
    fmt_combo.setSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Preferred)
    opts.addWidget(fmt_combo, 1)
    layout.addLayout(opts)

    hint = QLabel("")
    hint.setObjectName("HintLabel")
    hint.setWordWrap(True)
    layout.addWidget(hint)

    return BurnTabHandles(
        w, video_list, sub_list, mode_combo, fmt_combo, hint,
        btn_add_v, btn_add_s, btn_rm_v, btn_rm_s,
    )
