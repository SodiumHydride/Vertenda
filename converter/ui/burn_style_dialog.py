# -*- coding: utf-8 -*-
"""Visual editor for subtitle burn style (font, colors, outline, position)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..subtitle.styling_config import BurnStyle


def _ass_color_to_qcolor(ass: str) -> QColor:
    """Convert ``&H00BBGGRR`` to QColor.  Best-effort."""
    try:
        h = ass.lstrip("&Hh").lstrip("0")
        if not h:
            return QColor(0, 0, 0)
        val = int(h, 16)
        r = val & 0xFF
        g = (val >> 8) & 0xFF
        b = (val >> 16) & 0xFF
        return QColor(r, g, b)
    except (ValueError, TypeError):
        return QColor(255, 192, 203)


def _qcolor_to_ass(c: QColor) -> str:
    """Convert QColor to ``&H00BBGGRR`` ASS format."""
    return f"&H00{c.blue():02X}{c.green():02X}{c.red():02X}"


class BurnStyleDialog(QDialog):
    """Editor for BurnStyle with live preview text."""

    def __init__(self, style: BurnStyle, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("字幕样式编辑")
        self.resize(460, 440)
        self.style = BurnStyle(**style.__dict__)
        self._build_ui()
        self._update_preview()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.font_combo = QComboBox()
        self.font_combo.setEditable(True)
        self.font_combo.addItems([
            "Arial", "Helvetica Neue", "PingFang SC", "Microsoft YaHei",
            "SimHei", "Noto Sans CJK SC", "Source Han Sans SC",
        ])
        self.font_combo.setCurrentText(self.style.font_name)
        self.font_combo.currentTextChanged.connect(self._on_change)
        form.addRow("字体:", self.font_combo)

        self._primary_color = _ass_color_to_qcolor(self.style.primary_color)
        self.btn_primary = QPushButton()
        self.btn_primary.setFixedSize(80, 28)
        self._set_button_color(self.btn_primary, self._primary_color)
        self.btn_primary.clicked.connect(self._pick_primary)
        form.addRow("文字颜色:", self.btn_primary)

        self._outline_color = _ass_color_to_qcolor(self.style.outline_color)
        self.btn_outline = QPushButton()
        self.btn_outline.setFixedSize(80, 28)
        self._set_button_color(self.btn_outline, self._outline_color)
        self.btn_outline.clicked.connect(self._pick_outline)
        form.addRow("描边颜色:", self.btn_outline)

        self.spin_outline = QSpinBox()
        self.spin_outline.setRange(0, 10)
        self.spin_outline.setValue(self.style.outline_width)
        self.spin_outline.valueChanged.connect(self._on_change)
        form.addRow("描边宽度:", self.spin_outline)

        self.spin_fontsize = QSpinBox()
        self.spin_fontsize.setRange(8, 120)
        self.spin_fontsize.setValue(self.style.font_size)
        self.spin_fontsize.valueChanged.connect(self._on_change)
        form.addRow("字号:", self.spin_fontsize)

        self.align_combo = QComboBox()
        self.align_combo.addItems(["左下 (1)", "底部居中 (2)", "右下 (3)",
                                    "左中 (4)", "居中 (5)", "右中 (6)",
                                    "左上 (7)", "顶部居中 (8)", "右上 (9)"])
        self.align_combo.setCurrentIndex(self.style.alignment - 1)
        self.align_combo.currentIndexChanged.connect(self._on_change)
        form.addRow("对齐方式:", self.align_combo)

        self.spin_margin = QSpinBox()
        self.spin_margin.setRange(0, 200)
        self.spin_margin.setValue(self.style.margin_v)
        self.spin_margin.valueChanged.connect(self._on_change)
        form.addRow("垂直边距:", self.spin_margin)

        layout.addLayout(form)

        self.preview = QLabel("字幕预览 Subtitle Preview 你好世界")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(60)
        self.preview.setStyleSheet(
            "background: #222; border-radius: 8px; padding: 14px;"
        )
        layout.addWidget(self.preview)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_save = QPushButton("保存")
        btn_save.setObjectName("PrimaryButton")
        btn_save.clicked.connect(self._save)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_save)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _on_change(self) -> None:
        self._update_preview()

    def _pick_primary(self) -> None:
        c = QColorDialog.getColor(self._primary_color, self, "文字颜色")
        if c.isValid():
            self._primary_color = c
            self._set_button_color(self.btn_primary, c)
            self._update_preview()

    def _pick_outline(self) -> None:
        c = QColorDialog.getColor(self._outline_color, self, "描边颜色")
        if c.isValid():
            self._outline_color = c
            self._set_button_color(self.btn_outline, c)
            self._update_preview()

    @staticmethod
    def _set_button_color(btn: QPushButton, color: QColor) -> None:
        btn.setStyleSheet(
            f"background-color: {color.name()}; border: 1px solid #666; border-radius: 4px;"
        )

    def _update_preview(self) -> None:
        fg = self._primary_color.name()
        outline = self._outline_color.name()
        size = self.spin_fontsize.value()
        font_name = self.font_combo.currentText()
        self.preview.setStyleSheet(
            f"background: #222; border-radius: 8px; padding: 14px; "
            f"color: {fg}; font-family: '{font_name}'; font-size: {size}px; "
            f"text-shadow: {outline} 0px 0px {self.spin_outline.value()}px;"
        )

    def _save(self) -> None:
        self.style.font_name = self.font_combo.currentText()
        self.style.primary_color = _qcolor_to_ass(self._primary_color)
        self.style.outline_color = _qcolor_to_ass(self._outline_color)
        self.style.outline_width = self.spin_outline.value()
        self.style.font_size = self.spin_fontsize.value()
        self.style.alignment = self.align_combo.currentIndex() + 1
        self.style.margin_v = self.spin_margin.value()
        self.accept()
