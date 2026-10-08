# ── ДИЗАЙН-СИСТЕМА ──────────────────────────────────────────────────────────
# Современный тёмный UI с чёткой иерархией:
#   • Фон #1e1e2e (тёмно-серо-синий, светлее чисто-чёрного)
#   • Кнопки #2b2b3d с чёткой границей #3d3d52 — видны, не сливаются
#   • Текст по центру — симметрично, не прижат к левому краю
#   • Акцент #7c9eff (приглушённо-синий, не кислотный)
#   • Скругления 8px — мягче, современнее
#   • Hover = подсветка границы акцентом + текст акцентом

STYLE = """
QWidget {
    background-color: #1e1e2e;
    color: #e4e4e7;
    font-family: 'Segoe UI', 'Segoe UI Emoji', sans-serif;
    font-size: 11pt;
}

/* Заголовок — по центру, с акцентной полосой снизу */
QLabel#title {
    color: #e4e4e7;
    font-size: 16pt;
    font-weight: bold;
    padding: 10px 4px 10px 4px;
    border-bottom: 2px solid #7c9eff;
    margin-bottom: 6px;
    qproperty-alignment: AlignCenter;
}

/* Кнопки профилей — с чёткой границей, текст по центру */
QPushButton {
    background-color: #2b2b3d;
    border: 1px solid #3d3d52;
    border-radius: 8px;
    color: #d4d4d8;
    font-weight: bold;
    padding: 7px 12px;
    text-align: center;
}

QPushButton:hover {
    background-color: #353548;
    border: 1px solid #7c9eff;
    color: #a5b4fc;
}

QPushButton:pressed {
    background-color: #7c9eff;
    color: #1e1e2e;
    border: 1px solid #7c9eff;
}

/* STOP — красный, заметный, по центру */
QPushButton#stop_all {
    background-color: #dc2626;
    border: 1px solid #ef4444;
    border-radius: 8px;
    color: #ffffff;
    font-weight: bold;
    font-size: 12pt;
    padding: 9px 12px;
    text-align: center;
}

QPushButton#stop_all:hover {
    background-color: #ef4444;
    border: 1px solid #f87171;
}

QPushButton#stop_all:pressed {
    background-color: #b91c1c;
    color: #ffffff;
}

/* Активные кнопки профилей (счётчик > 0) — зелёный акцент */
QPushButton#active {
    background-color: #166534;
    border: 1px solid #22c55e;
    color: #86efac;
}

QPushButton#active:hover {
    background-color: #22c55e;
    color: #052e16;
    border: 1px solid #4ade80;
}

/* Кнопка обновы — синий акцент */
QPushButton#upd_btn {
    background-color: #7c9eff;
    border: 1px solid #a5b4fc;
    border-radius: 8px;
    color: #1e1e2e;
    font-size: 9pt;
    font-weight: bold;
    padding: 6px 14px;
    text-align: center;
}
QPushButton#upd_btn:hover {
    background-color: #a5b4fc;
    border: 1px solid #c7d2fe;
}
"""

SCROLL = """
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #4a4a5e;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #7c9eff;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0px;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
}
"""

NICK_STYLE = """
    QFrame { border: 1px solid #3d3d52; border-radius: 8px; background-color: transparent; }
"""

UPD = """
    QPushButton {
        background-color: #7c9eff;
        color: #1e1e2e;
        font-size: 9pt;
        font-weight: bold;
        border: 1px solid #a5b4fc;
        border-radius: 8px;
        padding: 6px 14px;
    }
    QPushButton:hover {
        background-color: #a5b4fc;
    }
"""

ERROR_STYLE = """
QWidget {
    background-color: #1e1e2e;
    color: #ef4444;
    font-family: 'Consolas', monospace;
    font-size: 11pt;
}

QMessageBox QLabel {
    color: #ef4444;
}

QPushButton {
    background-color: #2b2b3d;
    color: #ef4444;
    border: 1px solid #ef4444;
    border-radius: 8px;
    padding: 6px 12px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #ef4444;
    color: #1e1e2e;
}

QPushButton:pressed {
    background-color: #b91c1c;
    color: #ffffff;
}
"""

CARD = """
    QFrame {
        border: 1px solid #3d3d52;
        border-radius: 8px;
        background-color: #2b2b3d;
    }
    QFrame[selected="true"] {
        background-color: #7c9eff;
        border: 1px solid #a5b4fc;
    }
    QLabel {
        font-size: 9px;
        color: #e4e4e7;
    }
"""

WINDOWS_FRAME = """
    QFrame {
        border: 1px solid #3d3d52;
        border-radius: 8px;
        background-color: #1a1a28;
    }
"""

MONITOR = """
    QPushButton {
        background-color: #2b2b3d;
        border: 1px solid #3d3d52;
        border-radius: 6px;
        color: #d4d4d8;
        font-size: 9pt;
    }
    QPushButton:hover {
        background-color: #353548;
        border: 1px solid #7c9eff;
        color: #a5b4fc;
    }
    QPushButton:checked {
        background-color: #7c9eff;
        color: #1e1e2e;
        border: 1px solid #a5b4fc;
        font-weight: bold;
    }
"""

PAYMENT_CARD_STYLE = """
QWidget#payment_card {
    background-color: #2b2b3d;
    border: 1px solid #3d3d52;
    border-radius: 8px;
    padding: 8px;
}
QWidget#payment_card:hover {
    background-color: #353548;
    border: 1px solid #7c9eff;
}
"""

PAYMENT_VALUE_LABEL_STYLE = """
QLabel {
    color: #a5b4fc;
    font-weight: bold;
    padding: 6px 12px;
    background-color: #1a1a28;
    border: 1px solid #3d3d52;
    border-radius: 6px;
}
QLabel:hover {
    background-color: #2b2b3d;
    border: 1px solid #7c9eff;
}
"""
