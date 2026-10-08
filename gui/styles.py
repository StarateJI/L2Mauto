# ── ДИЗАЙН-СИСТЕМА ──────────────────────────────────────────────────────────
# Лаконичный стиль в духе Студии Артемия Лебедева:
#   • Глубокий чёрный фон (#0a0a0a)
#   • Чистый белый текст
#   • Один кислотный акцент — #00ff88 (электрик-зелёный)
#   • Без рамок, без скруглений (radius 0)
#   • Чёткая типографика, uppercase для кнопок действий
#   • Hover = заливка акцентом, текст становится чёрным
#   • Минимум визуального шума

STYLE = """
QWidget {
    background-color: #0a0a0a;
    color: #ffffff;
    font-family: 'Segoe UI', 'Segoe UI Emoji', sans-serif;
    font-size: 11pt;
}

/* Заголовок — крупный, bold, с акцентной полосой снизу */
QLabel#title {
    color: #ffffff;
    font-size: 18pt;
    font-weight: 900;
    padding: 10px 4px 12px 4px;
    border-bottom: 3px solid #00ff88;
    margin-bottom: 6px;
    letter-spacing: 1px;
}

/* Кнопки профилей — плоские, без рамок */
QPushButton {
    background-color: #1a1a1a;
    border: none;
    border-radius: 0px;
    color: #e0e0e0;
    font-weight: bold;
    padding: 8px 12px;
    text-align: left;
}

QPushButton:hover {
    background-color: #00ff88;
    color: #0a0a0a;
}

QPushButton:pressed {
    background-color: #00cc6a;
    color: #0a0a0a;
}

/* STOP — чистый красный, контраст */
QPushButton#stop_all {
    background-color: #ff3b30;
    border: none;
    border-radius: 0px;
    color: #ffffff;
    font-weight: 900;
    font-size: 13pt;
    padding: 10px 12px;
    letter-spacing: 2px;
}

QPushButton#stop_all:hover {
    background-color: #ffffff;
    color: #ff3b30;
}

QPushButton#stop_all:pressed {
    background-color: #cc2f26;
    color: #ffffff;
}

/* Активные кнопки профилей (счётчик > 0) — акцент */
QPushButton#active {
    background-color: #00ff88;
    color: #0a0a0a;
}

QPushButton#active:hover {
    background-color: #ffffff;
    color: #0a0a0a;
}

/* Кнопка обновы — акцент */
QPushButton#upd_btn {
    background-color: #00ff88;
    border: none;
    border-radius: 0px;
    color: #0a0a0a;
    font-size: 9pt;
    font-weight: 900;
    padding: 6px 14px;
    letter-spacing: 1px;
}
QPushButton#upd_btn:hover {
    background-color: #ffffff;
    color: #0a0a0a;
}
"""

SCROLL = """
QScrollBar:vertical {
    background: #0a0a0a;
    width: 6px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: #333;
    min-height: 20px;
    border-radius: 0px;
}
QScrollBar::handle:vertical:hover {
    background: #00ff88;
}
QScrollBar::add-line, QScrollBar::sub-line {
    height: 0px;
}
QScrollBar::add-page, QScrollBar::sub-page {
    background: none;
}
"""

NICK_STYLE = """
    QFrame { border: 1px solid #333; border-radius: 0px; background-color: transparent; }
"""

UPD = """
    QPushButton {
        background-color: #00ff88;
        color: #0a0a0a;
        font-size: 9pt;
        font-weight: 900;
        border: none;
        border-radius: 0px;
        padding: 6px 14px;
    }
    QPushButton:hover {
        background-color: #ffffff;
    }
"""

ERROR_STYLE = """
QWidget {
    background-color: #0a0a0a;
    color: #ff3b30;
    font-family: 'Consolas', monospace;
    font-size: 11pt;
}

QMessageBox QLabel {
    color: #ff3b30;
}

QPushButton {
    background-color: #1a1a1a;
    color: #ff3b30;
    border: none;
    border-radius: 0px;
    padding: 6px 12px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #ff3b30;
    color: #0a0a0a;
}

QPushButton:pressed {
    background-color: #cc2f26;
    color: #ffffff;
}
"""

CARD = """
    QFrame {
        border: 1px solid #333;
        border-radius: 0px;
        background-color: #141414;
    }
    QFrame[selected="true"] {
        background-color: #00ff88;
        border: 1px solid #00ff88;
    }
    QLabel {
        font-size: 9px;
        color: #ffffff;
    }
"""

WINDOWS_FRAME = """
    QFrame {
        border: 1px solid #222;
        border-radius: 0px;
        background-color: #0f0f0f;
    }
"""

MONITOR = """
    QPushButton {
        background-color: #141414;
        border: none;
        border-radius: 0px;
        color: #e0e0e0;
        font-size: 9pt;
    }
    QPushButton:hover {
        background-color: #00ff88;
        color: #0a0a0a;
    }
    QPushButton:checked {
        background-color: #00ff88;
        color: #0a0a0a;
        font-weight: bold;
    }
"""

PAYMENT_CARD_STYLE = """
QWidget#payment_card {
    background-color: #141414;
    border: none;
    border-radius: 0px;
    padding: 8px;
}
QWidget#payment_card:hover {
    background-color: #00ff88;
}
"""

PAYMENT_VALUE_LABEL_STYLE = """
QLabel {
    color: #00ff88;
    font-weight: bold;
    padding: 6px 12px;
    background-color: #0a0a0a;
    border: none;
    border-radius: 0px;
}
QLabel:hover {
    background-color: #ffffff;
    color: #0a0a0a;
}
"""
