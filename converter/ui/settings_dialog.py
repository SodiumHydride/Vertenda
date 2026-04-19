# -*- coding: utf-8 -*-
"""Settings dialog."""

from __future__ import annotations

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
    QPushButton,
    QSlider,
    QSpinBox,
)

from ..constants import SettingsKey
from ..ffmpeg.quality import QualityPreset, parse as parse_preset


class SettingsDialog(QDialog):
    """Dialog for background, theme, font, output dir, hardware accel, quality."""

    hw_accel_changed_signal = pyqtSignal(bool)
    settings_applied_signal = pyqtSignal()

    def __init__(self, parent, settings) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("偏好设置")
        self.resize(520, 480)

        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = QFormLayout(self)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(12)

        self.bg_path_edit = QLineEdit(self)
        btn_browse_bg = QPushButton("浏览…", self)
        btn_browse_bg.clicked.connect(self._browse_bg)
        row_bg = QHBoxLayout()
        row_bg.addWidget(self.bg_path_edit)
        row_bg.addWidget(btn_browse_bg)
        layout.addRow("背景图路径:", row_bg)

        self.bg_alpha_slider = QSlider(Qt.Horizontal, self)
        self.bg_alpha_slider.setRange(0, 100)
        self.label_alpha = QLabel("70 %", self)
        self.label_alpha.setFixedWidth(52)
        self.bg_alpha_slider.valueChanged.connect(
            lambda v: self.label_alpha.setText(f"{v} %")
        )
        row_alpha = QHBoxLayout()
        row_alpha.addWidget(self.bg_alpha_slider)
        row_alpha.addWidget(self.label_alpha)
        layout.addRow("背景透明度:", row_alpha)

        self.overlay_slider = QSlider(Qt.Horizontal, self)
        self.overlay_slider.setRange(0, 100)
        self.overlay_slider.setToolTip(
            "在背景图之上叠加的主题色遮罩强度。背景太花时调高，完全看不到背景时调低。"
        )
        self.label_overlay = QLabel("40 %", self)
        self.label_overlay.setFixedWidth(52)
        self.overlay_slider.valueChanged.connect(
            lambda v: self.label_overlay.setText(f"{v} %")
        )
        row_overlay = QHBoxLayout()
        row_overlay.addWidget(self.overlay_slider)
        row_overlay.addWidget(self.label_overlay)
        layout.addRow("可读性遮罩:", row_overlay)

        self.theme_combo = QComboBox(self)
        self.theme_combo.addItems(["Dark", "Light"])
        layout.addRow("主题模式:", self.theme_combo)

        self.spin_font_size = QSpinBox(self)
        self.spin_font_size.setRange(8, 24)
        layout.addRow("字体大小:", self.spin_font_size)

        self.output_edit = QLineEdit(self)
        btn_browse_out = QPushButton("选择…", self)
        btn_browse_out.clicked.connect(self._browse_output)
        row_out = QHBoxLayout()
        row_out.addWidget(self.output_edit)
        row_out.addWidget(btn_browse_out)
        layout.addRow("输出目录:", row_out)

        self.check_hw = QCheckBox("启用 GPU 硬件加速 (macOS VideoToolbox)", self)
        layout.addRow("硬件加速:", self.check_hw)

        self.quality_combo = QComboBox(self)
        for preset in (QualityPreset.FAST, QualityPreset.BALANCED, QualityPreset.HIGH):
            self.quality_combo.addItem(preset.display, userData=preset.value)
        layout.addRow("转换质量:", self.quality_combo)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_save = QPushButton("保存", self)
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_cancel = QPushButton("取消", self)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_cancel)
        layout.addRow(btn_row)

        self.btn_save.clicked.connect(self._save)
        self.btn_cancel.clicked.connect(self.reject)

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

        self.hw_accel_changed_signal.emit(self.check_hw.isChecked())
        self.accept()
