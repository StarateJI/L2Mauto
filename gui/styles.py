# ── ДИЗАЙН-СИСТЕМА ──────────────────────────────────────────────────────────
# Современный объёмный UI:
#   • Шрифт 'Segoe UI Variable Display' (Windows 11) → fallback Segoe UI
#   • Фон с лёгким вертикальным градиентом — глубина
#   • Кнопки выпуклые: градиент сверху-вниз + border-top светлее
#   • Скругления 10px — мягче, современнее
#   • Акцент #818cf8 (индиго) — спокойнее синего
#   • Hover = подсветка границы + лёгкий lift градиентом
#   • Pressed = инверсия градиента (кнопка «вдавливается»)

STYLE = """
QWidget {
    background-color: #1a1a26;
    color: #e4e4e7;
    font-family: 'Verdana', 'Tahoma', sans-serif;
    font-size: 11pt;
}

/* Заголовок — компактный */
QLabel#title {
    color: #f4f4f5;
    font-size: 13pt;
    font-weight: 700;
    padding: 6px 4px 2px 4px;
    qproperty-alignment: AlignCenter;
    letter-spacing: 1px;
}

/* Подзаголовок — мелкий, без отступов */
QLabel#subtitle {
    color: #52525b;
    font-size: 7pt;
    font-weight: 400;
    padding: 0px 4px 4px 4px;
    qproperty-alignment: AlignCenter;
    letter-spacing: 2px;
}

/* Кнопки профилей — выпуклые, пожирнее */
QPushButton {
    /* Градиент сверху-вниз: верх светлее → объём */
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #34344a, stop:1 #2a2a3d);
    border: 1px solid #3d3d52;
    border-top: 1px solid #4a4a63;
    border-bottom: 1px solid #1f1f30;
    border-radius: 10px;
    color: #d4d4d8;
    font-weight: 700;
    font-size: 12pt;
    padding: 8px 12px;
    text-align: center;
}

QPushButton:hover {
    /* Hover: ярче градиент + граница акцентом */
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #3d3d56, stop:1 #30304a);
    border: 1px solid #818cf8;
    border-top: 1px solid #a5b4fc;
    color: #c7d2fe;
}

QPushButton:pressed {
    /* Pressed: инверсия — кнопка вдавливается */
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #2a2a3d, stop:1 #34344a);
    border: 1px solid #818cf8;
    color: #a5b4fc;
}

/* STOP — синий, как кнопка обновы (была красная) */
QPushButton#stop_all {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #818cf8, stop:1 #6366f1);
    border: 1px solid #a5b4fc;
    border-top: 1px solid #c7d2fe;
    border-bottom: 1px solid #4f46e5;
    border-radius: 10px;
    color: #ffffff;
    font-weight: 700;
    font-size: 13pt;
    padding: 10px 12px;
    text-align: center;
    letter-spacing: 1px;
}

QPushButton#stop_all:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #a5b4fc, stop:1 #818cf8);
    border: 1px solid #c7d2fe;
}

QPushButton#stop_all:pressed {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #6366f1, stop:1 #818cf8);
    color: #ffffff;
}

/* Активные кнопки профилей (счётчик > 0) — зелёный, выпуклые */
QPushButton#active {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #22c55e, stop:1 #16a34a);
    border: 1px solid #4ade80;
    border-top: 1px solid #86efac;
    border-bottom: 1px solid #15803d;
    color: #052e16;
}

QPushButton#active:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #4ade80, stop:1 #22c55e);
    color: #052e16;
    border: 1px solid #86efac;
}

/* Кнопка обновы — индиго, выпуклая */
QPushButton#upd_btn {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #818cf8, stop:1 #6366f1);
    border: 1px solid #a5b4fc;
    border-top: 1px solid #c7d2fe;
    border-bottom: 1px solid #4f46e5;
    border-radius: 10px;
    color: #ffffff;
    font-size: 9pt;
    font-weight: 700;
    padding: 7px 16px;
    text-align: center;
    letter-spacing: 0.5px;
}
QPushButton#upd_btn:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #a5b4fc, stop:1 #818cf8);
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
    background: #3d3d52;
    min-height: 24px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #818cf8;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0px;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
}
"""

NICK_STYLE = """
    QFrame { border: 1px solid #3d3d52; border-radius: 10px; background-color: transparent; }
"""

UPD = """
    QPushButton {
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #818cf8, stop:1 #6366f1);
        color: #ffffff;
        font-size: 9pt;
        font-weight: 700;
        border: 1px solid #a5b4fc;
        border-radius: 10px;
        padding: 7px 16px;
    }
    QPushButton:hover {
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #a5b4fc, stop:1 #818cf8);
    }
"""

ERROR_STYLE = """
QWidget {
    background-color: #1a1a26;
    color: #ef4444;
    font-family: 'Segoe UI Variable', 'Segoe UI', 'Consolas', monospace;
    font-size: 11pt;
}

QMessageBox QLabel {
    color: #ef4444;
}

QPushButton {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #34344a, stop:1 #2a2a3d);
    color: #ef4444;
    border: 1px solid #ef4444;
    border-radius: 10px;
    padding: 7px 14px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #ef4444, stop:1 #dc2626);
    color: #ffffff;
}
"""

CARD = """
    QFrame {
        border: 1px solid #3d3d52;
        border-radius: 10px;
        background-color: #2a2a3d;
    }
    QFrame[selected="true"] {
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #818cf8, stop:1 #6366f1);
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
        border-radius: 10px;
        background-color: #1f1f30;
    }
"""

MONITOR = """
    QPushButton {
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #34344a, stop:1 #2a2a3d);
        border: 1px solid #3d3d52;
        border-radius: 8px;
        color: #d4d4d8;
        font-size: 9pt;
    }
    QPushButton:hover {
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #3d3d56, stop:1 #30304a);
        border: 1px solid #818cf8;
        color: #c7d2fe;
    }
    QPushButton:checked {
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #818cf8, stop:1 #6366f1);
        color: #ffffff;
        border: 1px solid #a5b4fc;
        font-weight: bold;
    }
"""

PAYMENT_CARD_STYLE = """
QWidget#payment_card {
    background-color: #2a2a3d;
    border: 1px solid #3d3d52;
    border-radius: 10px;
    padding: 8px;
}
QWidget#payment_card:hover {
    background-color: #34344a;
    border: 1px solid #818cf8;
}
"""

PAYMENT_VALUE_LABEL_STYLE = """
QLabel {
    color: #a5b4fc;
    font-weight: bold;
    padding: 7px 12px;
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1f1f30, stop:1 #1a1a26);
    border: 1px solid #3d3d52;
    border-radius: 8px;
}
QLabel:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #34344a, stop:1 #2a2a3d);
    border: 1px solid #818cf8;
}
"""
