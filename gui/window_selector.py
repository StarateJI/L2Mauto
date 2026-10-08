"""
gui/window_selector.py — Диалог выбора окон перед запуском сценария.

Выбранные окна подсвечиваются, невыбранные — тусклые серые.
Выбор запоминается для каждого сценария отдельно.
"""
from __future__ import annotations

import json
import os
from typing import List, Optional

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QWidget, QGridLayout, QMessageBox
)
from PyQt5.QtGui import QFont, QColor, QPalette

from bot.clogger import log


# Файл для сохранения выбора окон по сценариям
SELECT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "window_selection.json")


def load_selection() -> dict:
    """Загрузить сохранённый выбор окон."""
    try:
        with open(SELECT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_selection(data: dict) -> None:
    """Сохранить выбор окон."""
    try:
        with open(SELECT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"window_selector: save error: {e}", level="WARNING")


class WindowButton(QPushButton):
    """Кнопка окна — подсвечивается если выбрано, тусклая если нет."""

    def __init__(self, nick: str, selected: bool = True):
        super().__init__(nick)
        self.nick = nick
        self.selected = selected
        self.setCheckable(True)
        self.setChecked(selected)
        self.setFixedHeight(32)
        self.setMinimumWidth(120)
        self.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.setCursor(Qt.PointingHandCursor)
        self._update_style()
        self.toggled.connect(lambda _: self._update_style())

    def _update_style(self):
        if self.isChecked():
            self.setStyleSheet("""
                QPushButton {
                    background-color: #2d5a2d;
                    color: #ffffff;
                    border: 2px solid #4CAF50;
                    border-radius: 6px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #3a6b3a;
                    border: 2px solid #66BB6A;
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: #3a3a3a;
                    color: #666666;
                    border: 2px solid #555555;
                    border-radius: 6px;
                    font-weight: normal;
                }
                QPushButton:hover {
                    background-color: #444444;
                    color: #888888;
                    border: 2px solid #666666;
                }
            """)


class WindowSelectorDialog(QDialog):
    """Диалог выбора окон для сценария."""

    def __init__(self, scenario_name: str, all_windows: List[str],
                 parent=None):
        super().__init__(parent)
        self.scenario_name = scenario_name
        self.all_windows = all_windows
        self.buttons: List[WindowButton] = []

        self.setWindowTitle(f"Выбор окон — {scenario_name}")
        self.setMinimumWidth(400)
        self.setMinimumHeight(500)

        self._load_saved = load_selection()
        saved = set(self._load_saved.get(scenario_name, all_windows))

        layout = QVBoxLayout(self)

        # Заголовок
        title = QLabel(f"Выбери окна для: {scenario_name}")
        title.setFont(QFont("Segoe UI", 11, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #ffffff; padding: 10px;")
        layout.addWidget(title)

        info = QLabel("Зелёные = выбраны, серые = пропустить. Выбор запоминается.")
        info.setAlignment(Qt.AlignCenter)
        info.setStyleSheet("color: #999999; font-size: 10px; padding: 5px;")
        layout.addWidget(info)

        # Кнопки "Выбрать все" / "Снять все"
        btn_row = QHBoxLayout()
        btn_all = QPushButton("✓ Все")
        btn_all.setFixedHeight(28)
        btn_all.clicked.connect(self._select_all)
        btn_row.addWidget(btn_all)

        btn_none = QPushButton("✕ Снять все")
        btn_none.setFixedHeight(28)
        btn_none.clicked.connect(self._select_none)
        btn_row.addWidget(btn_none)
        layout.addLayout(btn_row)

        # Сетка с кнопками окон
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        grid = QGridLayout(scroll_content)

        cols = 3
        for i, nick in enumerate(all_windows):
            selected = nick in saved
            btn = WindowButton(nick, selected)
            row = i // cols
            col = i % cols
            grid.addWidget(btn, row, col)
            self.buttons.append(btn)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        # Кнопки ОК / Отмена
        btn_row2 = QHBoxLayout()
        self.btn_ok = QPushButton("▶ Запустить")
        self.btn_ok.setFixedHeight(32)
        self.btn_ok.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.btn_ok.setStyleSheet("""
            QPushButton {
                background-color: #2d5a2d;
                color: white;
                border: 2px solid #4CAF50;
                border-radius: 6px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #3a6b3a; }
        """)
        self.btn_ok.clicked.connect(self._on_ok)
        btn_row2.addWidget(self.btn_ok)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.setFixedHeight(32)
        btn_cancel.clicked.connect(self.reject)
        btn_row2.addWidget(btn_cancel)
        layout.addLayout(btn_row2)

    def _select_all(self):
        for btn in self.buttons:
            btn.setChecked(True)

    def _select_none(self):
        for btn in self.buttons:
            btn.setChecked(False)

    def _on_ok(self):
        selected = [btn.nick for btn in self.buttons if btn.isChecked()]
        if not selected:
            QMessageBox.warning(self, "Внимание", "Не выбрано ни одного окна!")
            return
        # Сохраняем выбор
        self._load_saved[self.scenario_name] = selected
        save_selection(self._load_saved)
        log(f"Выбор окон для {self.scenario_name}: {selected}")
        self.accept()

    def get_selected(self) -> List[str]:
        return [btn.nick for btn in self.buttons if btn.isChecked()]
