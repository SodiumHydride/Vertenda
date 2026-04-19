# -*- coding: utf-8 -*-
"""QSS stylesheets for dark / light themes.

Keeping them as string constants in a dedicated module keeps the window
class focused on layout.
"""

from __future__ import annotations


# Shared tokens (mental model: dark is primary, light is a port).
_DARK = {
    "fg":            "#ECECF2",
    "fg_dim":        "#A5A6B4",
    "bg_panel":      "rgba(32, 33, 44, 205)",
    "bg_panel_hov":  "rgba(58, 60, 80, 220)",
    "bg_input":      "rgba(18, 19, 27, 220)",
    "border":        "rgba(90, 95, 120, 190)",
    "border_strong": "rgba(140, 145, 190, 230)",
    "accent":        "#7B5CFF",
    "accent_soft":   "rgba(123, 92, 255, 100)",
    "accent_hover":  "#9077FF",
    "success":       "#32D17E",
    "warn":          "#F5A524",
    "danger":        "#F04444",
    "selection_bg":  "rgba(123, 92, 255, 140)",
    "progress_bg":   "rgba(26, 27, 38, 210)",
    "header_fg":     "#8888A6",
    "shadow":        "rgba(0, 0, 0, 180)",
}

_LIGHT = {
    "fg":            "#1B1B24",
    "fg_dim":        "#5D5D72",
    "bg_panel":      "rgba(255, 255, 255, 235)",
    "bg_panel_hov":  "rgba(240, 242, 252, 250)",
    "bg_input":      "rgba(255, 255, 255, 240)",
    "border":        "rgba(120, 125, 160, 140)",
    "border_strong": "rgba(80, 85, 130, 190)",
    "accent":        "#5B3FD6",
    "accent_soft":   "rgba(91, 63, 214, 85)",
    "accent_hover":  "#6E4EE8",
    "success":       "#1FAF66",
    "warn":          "#D68A0C",
    "danger":        "#D03030",
    "selection_bg":  "rgba(91, 63, 214, 110)",
    "progress_bg":   "rgba(220, 222, 236, 230)",
    "header_fg":     "#888D9C",
    "shadow":        "rgba(0, 0, 0, 40)",
}


_TEMPLATE = """
QWidget {
    background: transparent;
    color: %(fg)s;
    font-family: "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif;
}

QMainWindow { background-color: transparent; }

QDialog {
    background-color: %(bg_panel)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
}

QLabel { background: transparent; color: %(fg)s; }
QLabel#HintLabel, QLabel#StatusLabel {
    color: %(fg_dim)s;
    padding: 2px 4px;
}
QLabel#SectionTitle {
    color: %(fg_dim)s;
    letter-spacing: 0.5px;
}
QLabel#TitleLabel {
    font-size: 20px;
    font-weight: 700;
    padding: 2px 8px 2px 2px;
    color: %(fg)s;
}
QLabel#SubtitleLabel {
    font-size: 11px;
    color: %(fg_dim)s;
}

QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: %(bg_input)s;
    color: %(fg)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: %(selection_bg)s;
    selection-color: %(fg)s;
}
QPlainTextEdit {
    font-family: "Menlo", "Consolas", "Courier New", monospace;
    padding: 8px 10px;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border: 1px solid %(accent)s;
}

QComboBox::drop-down {
    width: 24px;
    border: none;
    background: transparent;
}
QComboBox QAbstractItemView {
    background-color: %(bg_panel)s;
    border: 1px solid %(border)s;
    selection-background-color: %(accent_soft)s;
    color: %(fg)s;
    padding: 4px;
    border-radius: 8px;
    outline: 0;
}
QComboBox QAbstractItemView::item {
    padding: 6px 10px;
    border-radius: 6px;
    min-height: 22px;
}
QComboBox QAbstractItemView::item:disabled {
    color: %(header_fg)s;
    padding-top: 10px;
    padding-bottom: 4px;
    font-size: 11px;
}

QListWidget {
    background-color: %(bg_input)s;
    color: %(fg)s;
    border: 1px solid %(border)s;
    border-radius: 10px;
    padding: 4px;
    outline: 0;
}
QListWidget::item {
    padding: 7px 10px;
    border-radius: 6px;
    margin: 1px 0;
}
QListWidget::item:hover {
    background-color: %(bg_panel_hov)s;
}
QListWidget::item:selected {
    background-color: %(accent_soft)s;
    color: %(fg)s;
}

QPushButton, QToolButton {
    background-color: %(bg_panel)s;
    color: %(fg)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
    padding: 7px 18px;
    font-weight: 500;
}
QPushButton:hover, QToolButton:hover {
    background-color: %(bg_panel_hov)s;
    border: 1px solid %(border_strong)s;
}
QPushButton:pressed, QToolButton:pressed {
    background-color: %(accent_soft)s;
}
QPushButton:disabled, QToolButton:disabled {
    color: %(fg_dim)s;
    border: 1px solid %(border)s;
    background-color: transparent;
}
QPushButton#PrimaryButton {
    background-color: %(accent)s;
    color: #FFFFFF;
    border: 1px solid %(accent)s;
    padding: 8px 22px;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    background-color: %(accent_hover)s;
    border: 1px solid %(accent_hover)s;
}
QPushButton#PrimaryButton:disabled {
    background-color: %(accent_soft)s;
    color: rgba(255, 255, 255, 140);
    border: 1px solid %(accent_soft)s;
}
QPushButton#DangerButton {
    border: 1px solid %(danger)s;
    color: %(danger)s;
    background-color: transparent;
}
QPushButton#DangerButton:hover {
    background-color: rgba(240, 68, 68, 40);
}

QProgressBar {
    min-height: 22px;
    max-height: 22px;
    background-color: %(progress_bg)s;
    border: 1px solid %(border)s;
    border-radius: 11px;
    text-align: center;
    color: %(fg)s;
    font-weight: 600;
    font-size: 11px;
}
QProgressBar::chunk {
    background-color: %(accent)s;
    border-radius: 10px;
    margin: 1px;
}
QProgressBar#FileProgress {
    min-height: 6px;
    max-height: 6px;
    border-radius: 4px;
    border: none;
    background-color: %(progress_bg)s;
}
QProgressBar#FileProgress::chunk {
    background-color: %(accent_hover)s;
    border-radius: 4px;
}

QCheckBox { spacing: 8px; color: %(fg)s; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid %(border_strong)s;
    background: %(bg_input)s;
}
QCheckBox::indicator:checked {
    background-color: %(accent)s;
    border: 1px solid %(accent)s;
}

QRadioButton::indicator {
    width: 14px; height: 14px;
    border-radius: 7px;
    border: 1px solid %(border_strong)s;
    background: %(bg_input)s;
}
QRadioButton::indicator:checked {
    background-color: %(accent)s;
    border: 1px solid %(accent)s;
}

QSlider::groove:horizontal {
    height: 4px;
    background: %(border)s;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: %(accent)s;
    border: none;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover { background: %(accent_hover)s; }

QTabWidget::pane {
    background: %(bg_panel)s;
    border: 1px solid %(border)s;
    border-radius: 12px;
    padding: 6px;
}
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab {
    background: transparent;
    color: %(fg_dim)s;
    padding: 8px 18px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-radius: 8px;
    font-weight: 500;
}
QTabBar::tab:hover { color: %(fg)s; }
QTabBar::tab:selected {
    background: %(accent_soft)s;
    color: %(fg)s;
    border: 1px solid %(accent_soft)s;
}

QMenu {
    background-color: %(bg_panel)s;
    border: 1px solid %(border)s;
    border-radius: 8px;
    padding: 4px;
    color: %(fg)s;
}
QMenu::item {
    padding: 6px 18px;
    border-radius: 6px;
}
QMenu::item:selected { background-color: %(accent_soft)s; }
QMenu::separator { height: 1px; background-color: %(border)s; margin: 4px 6px; }

QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: %(border_strong)s;
    border-radius: 4px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: %(accent_hover)s; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 2px;
}
QScrollBar::handle:horizontal {
    background: %(border_strong)s;
    border-radius: 4px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: %(accent_hover)s; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

QStatusBar {
    background-color: %(bg_panel)s;
    color: %(fg)s;
    border-top: 1px solid %(border)s;
    padding: 2px 6px;
}
QStatusBar QLabel { color: %(fg)s; }

QToolTip {
    background-color: %(bg_panel)s;
    color: %(fg)s;
    border: 1px solid %(border_strong)s;
    padding: 4px 8px;
    border-radius: 6px;
}
"""


def build_stylesheet(theme_mode: str) -> str:
    tokens = _LIGHT if theme_mode == "Light" else _DARK
    return _TEMPLATE % tokens


def overlay_color_for(theme_mode: str) -> tuple[int, int, int]:
    """Base RGB of the readability overlay drawn over the background image."""
    if theme_mode == "Light":
        return (248, 249, 255)
    return (12, 14, 22)
