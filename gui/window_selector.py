"""
gui/window_selector.py — Единый диалог выбора окон + настроек сценария.

Объединяет в одном окне:
  - Сетку ников (зелёные = выбраны, серые = пропустить)
  - Спиннер "сколько окон одновременно" (для всех кроме PvPDodge)
  - Выбор типа данжа (только для Dungeon)

Выбор окон запоминается для каждого сценария отдельно.
Количество и тип данжа тоже запоминаются (через cache.json).
"""
from __future__ import annotations

import json
import os
from typing import List, Optional

from PyQt5.QtCore import Qt, QSize
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QScrollArea, QWidget, QGridLayout, QMessageBox, QSpinBox,
    QButtonGroup, QFrame
)
from PyQt5.QtGui import QFont, QColor, QPalette

from bot.clogger import log
from gui.styles import STYLE, SCROLL


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
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #22c55e, stop:1 #16a34a);
                    border: 1px solid #4ade80;
                    border-top: 1px solid #86efac;
                    border-bottom: 1px solid #15803d;
                    border-radius: 10px;
                    color: #052e16;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #4ade80, stop:1 #22c55e);
                    border: 1px solid #86efac;
                }
                QPushButton:pressed {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #16a34a, stop:1 #22c55e);
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #34344a, stop:1 #2a2a3d);
                    border: 1px solid #3d3d52;
                    border-top: 1px solid #4a4a63;
                    border-bottom: 1px solid #1f1f30;
                    border-radius: 10px;
                    color: #71717a;
                    font-weight: 400;
                }
                QPushButton:hover {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #3d3d56, stop:1 #30304a);
                    border: 1px solid #818cf8;
                    border-top: 1px solid #a5b4fc;
                    color: #c7d2fe;
                }
                QPushButton:pressed {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #2a2a3d, stop:1 #34344a);
                }
            """)


class DungeonTypeButton(QPushButton):
    """Кнопка выбора типа данжа — компактная, с подсветкой."""

    def __init__(self, text: str, selected: bool = False):
        super().__init__(text)
        self.setCheckable(True)
        self.setChecked(selected)
        self.setFixedHeight(30)
        self.setMinimumWidth(140)
        self.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.setCursor(Qt.PointingHandCursor)
        self._update_style()
        self.toggled.connect(lambda _: self._update_style())

    def _update_style(self):
        if self.isChecked():
            self.setStyleSheet("""
                QPushButton {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #fb923c, stop:1 #f97316);
                    border: 1px solid #fdba74;
                    border-top: 1px solid #fed7aa;
                    border-bottom: 1px solid #c2410c;
                    border-radius: 10px;
                    color: #431407;
                    font-weight: 600;
                }
                QPushButton:hover {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #fdba74, stop:1 #fb923c);
                    border: 1px solid #fed7aa;
                }
                QPushButton:pressed {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #f97316, stop:1 #fb923c);
                }
            """)
        else:
            self.setStyleSheet("""
                QPushButton {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #34344a, stop:1 #2a2a3d);
                    border: 1px solid #3d3d52;
                    border-top: 1px solid #4a4a63;
                    border-bottom: 1px solid #1f1f30;
                    border-radius: 10px;
                    color: #71717a;
                    font-weight: 400;
                }
                QPushButton:hover {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #3d3d56, stop:1 #30304a);
                    border: 1px solid #818cf8;
                    border-top: 1px solid #a5b4fc;
                    color: #c7d2fe;
                }
                QPushButton:pressed {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #2a2a3d, stop:1 #34344a);
                }
            """)


class WindowSelectorDialog(QDialog):
    """
    Единый диалог выбора окон + настроек сценария.

    Параметры:
      scenario_name: имя профиля (для ключа сохранения)
      all_windows: список ников доступных окон
      show_count: показывать ли спиннер "сколько одновременно"
                  (False только для PvPDodge)
      dungeon_types: список типов данжа (только для Dungeon)
      default_count: значение по умолчанию для спиннера
      default_dungeon_type: выбранный по умолчанию тип данжа
    """

    def __init__(self, scenario_name: str, all_windows: List[str],
                 parent=None,
                 show_count: bool = True,
                 dungeon_types: Optional[List[str]] = None,
                 default_count: int = 2,
                 default_dungeon_type: Optional[str] = None):
        super().__init__(parent)
        self.scenario_name = scenario_name
        self.all_windows = all_windows
        self.buttons: List[WindowButton] = []
        self.dungeon_types = dungeon_types or []
        self._dungeon_btn_group: Optional[QButtonGroup] = None
        self._dungeon_btns: List[DungeonTypeButton] = []
        self._count_spin: Optional[QSpinBox] = None

        self.setWindowTitle(f"Запуск — {scenario_name}")
        self.setMinimumWidth(520)
        self.setMinimumHeight(600)
        self.setStyleSheet(STYLE)

        self._load_saved = load_selection()
        saved = set(self._load_saved.get(scenario_name, all_windows))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # ── Заголовок ────────────────────────────────────────────────────
        title = QLabel(f"▶ {scenario_name}")
        title.setFont(QFont("Segoe UI", 13, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            "color: #f4f4f5; font-size: 16pt; font-weight: 700; "
            "letter-spacing: 1px; padding: 6px 4px;"
        )
        layout.addWidget(title)

        info = QLabel("Зелёные = выбраны, серые = пропустить. Выбор запоминается.")
        info.setAlignment(Qt.AlignCenter)
        info.setStyleSheet(
            "color: #71717a; font-size: 9pt; letter-spacing: 2px; padding: 2px 4px;"
        )
        layout.addWidget(info)

        # ── Кнопки "Все" / "Снять все" + счётчик ─────────────────────────
        btn_row = QHBoxLayout()
        btn_all = QPushButton("✓ Все")
        btn_all.setFixedHeight(28)
        btn_all.setCursor(Qt.PointingHandCursor)
        btn_all.clicked.connect(self._select_all)
        btn_row.addWidget(btn_all)

        btn_none = QPushButton("✕ Снять все")
        btn_none.setFixedHeight(28)
        btn_none.setCursor(Qt.PointingHandCursor)
        btn_none.clicked.connect(self._select_none)
        btn_row.addWidget(btn_none)

        self.lbl_count_windows = QLabel("0 выбрано")
        self.lbl_count_windows.setStyleSheet(
            "color: #22c55e; font-size: 9pt; font-weight: 700; padding: 2px 8px;"
        )
        btn_row.addWidget(self.lbl_count_windows, alignment=Qt.AlignRight)
        layout.addLayout(btn_row)

        # ── Сетка с кнопками окон ────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(SCROLL)
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background-color: transparent;")
        grid = QGridLayout(scroll_content)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)
        grid.setContentsMargins(8, 8, 8, 8)

        cols = 3
        for i, nick in enumerate(all_windows):
            selected = nick in saved
            btn = WindowButton(nick, selected)
            btn.toggled.connect(self._update_count_label)
            row = i // cols
            col = i % cols
            grid.addWidget(btn, row, col)
            self.buttons.append(btn)

        scroll.setWidget(scroll_content)
        layout.addWidget(scroll, stretch=1)

        # ── Панель настроек (количество + тип данжа) ─────────────────────
        if show_count or dungeon_types:
            self._build_settings_panel(layout, show_count, dungeon_types,
                                       default_count, default_dungeon_type)

        self._update_count_label()

        # ── Кнопки ОК / Отмена ──────────────────────────────────────────
        btn_row2 = QHBoxLayout()
        self.btn_ok = QPushButton("▶ Запустить")
        self.btn_ok.setFixedHeight(36)
        self.btn_ok.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_ok.setCursor(Qt.PointingHandCursor)
        self.btn_ok.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #22c55e, stop:1 #16a34a);
                border: 1px solid #4ade80;
                border-top: 1px solid #86efac;
                border-bottom: 1px solid #15803d;
                border-radius: 10px;
                color: #052e16;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4ade80, stop:1 #22c55e);
                border: 1px solid #86efac;
            }
            QPushButton:pressed {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #16a34a, stop:1 #22c55e);
            }
        """)
        self.btn_ok.clicked.connect(self._on_ok)
        btn_row2.addWidget(self.btn_ok, stretch=2)

        btn_cancel = QPushButton("Отмена")
        btn_cancel.setFixedHeight(36)
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #34344a, stop:1 #2a2a3d);
                border: 1px solid #3d3d52;
                border-top: 1px solid #4a4a63;
                border-bottom: 1px solid #1f1f30;
                border-radius: 10px;
                color: #d4d4d8;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3d3d56, stop:1 #30304a);
                border: 1px solid #818cf8;
                border-top: 1px solid #a5b4fc;
                color: #c7d2fe;
            }
            QPushButton:pressed {
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2a2a3d, stop:1 #34344a);
            }
        """)
        btn_cancel.clicked.connect(self.reject)
        btn_row2.addWidget(btn_cancel, stretch=1)
        layout.addLayout(btn_row2)

    def _build_settings_panel(self, layout: QVBoxLayout, show_count: bool,
                              dungeon_types: Optional[List[str]],
                              default_count: int,
                              default_dungeon_type: Optional[str]):
        """Панель настроек: сколько одновременно + тип данжа."""
        panel = QFrame()
        panel.setStyleSheet("""
            QFrame {
                background-color: #2a2a3d;
                border: 1px solid #3d3d52;
                border-radius: 10px;
            }
        """)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 8, 10, 8)
        panel_layout.setSpacing(6)

        # ── Количество одновременно ──────────────────────────────────────
        if show_count:
            row = QHBoxLayout()
            lbl = QLabel("⚡ Одновременно:")
            lbl.setStyleSheet(
                "color: #d4d4d8; font-size: 10pt; font-weight: 600;"
            )
            row.addWidget(lbl)

            self._count_spin = QSpinBox()
            self._count_spin.setMinimum(1)
            self._count_spin.setMaximum(20)
            self._count_spin.setValue(default_count)
            self._count_spin.setFixedHeight(30)
            self._count_spin.setMinimumWidth(80)
            self._count_spin.setStyleSheet("""
                QSpinBox {
                    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #1f1f30, stop:1 #1a1a26);
                    color: #c7d2fe;
                    border: 1px solid #3d3d52;
                    border-radius: 8px;
                    font-weight: 600;
                    font-size: 11pt;
                    padding: 2px 6px;
                }
                QSpinBox:focus {
                    border: 1px solid #818cf8;
                }
                QSpinBox::up-button, QSpinBox::down-button {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #34344a, stop:1 #2a2a3d);
                    width: 18px;
                    border: none;
                    border-radius: 4px;
                }
                QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 #818cf8, stop:1 #6366f1);
                }
            """)
            row.addWidget(self._count_spin)

            hint = QLabel("окон за пачку")
            hint.setStyleSheet("color: #71717a; font-size: 9pt;")
            row.addWidget(hint)
            row.addStretch()
            panel_layout.addLayout(row)

        # ── Тип данжа ───────────────────────────────────────────────────
        if dungeon_types:
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color: #3d3d52; max-height: 1px;")
            panel_layout.addWidget(sep)

            lbl_d = QLabel("⚔ Тип данжа:")
            lbl_d.setStyleSheet(
                "color: #fb923c; font-size: 10pt; font-weight: 600;"
            )
            panel_layout.addWidget(lbl_d)

            dungeon_row = QHBoxLayout()
            self._dungeon_btn_group = QButtonGroup(self)
            self._dungeon_btn_group.setExclusive(True)

            for dt in dungeon_types:
                is_default = (default_dungeon_type == dt) or (
                    default_dungeon_type is None and dt == dungeon_types[0]
                )
                dbtn = DungeonTypeButton(dt, selected=is_default)
                self._dungeon_btn_group.addButton(dbtn)
                self._dungeon_btns.append(dbtn)
                dungeon_row.addWidget(dbtn)
            dungeon_row.addStretch()
            panel_layout.addLayout(dungeon_row)

        layout.addWidget(panel)

    def _update_count_label(self):
        """Обновить счётчик выбранных окон."""
        n = sum(1 for b in self.buttons if b.isChecked())
        self.lbl_count_windows.setText(f"{n} выбрано")

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
        # Сохраняем выбор окон
        self._load_saved[self.scenario_name] = selected
        save_selection(self._load_saved)
        log(f"Выбор окон для {self.scenario_name}: {selected}")
        self.accept()

    def get_selected(self) -> List[str]:
        return [btn.nick for btn in self.buttons if btn.isChecked()]

    def get_count(self) -> int:
        """Сколько окон запускать одновременно."""
        if self._count_spin is not None:
            return self._count_spin.value()
        return 2

    def get_dungeon_type(self) -> Optional[str]:
        """Выбранный тип данжа (None если панель данжа не показана)."""
        if self._dungeon_btn_group is None:
            return None
        checked = self._dungeon_btn_group.checkedButton()
        if checked is None:
            return self.dungeon_types[0] if self.dungeon_types else None
        return checked.text()
