"""
auction_eye.py — читалка «Текущая минимальная цена» через Tesseract OCR.

python auction_eye.py test — t прочитать, q выход
python auction_eye.py dump — диагностика (сохраняет zone.png с тем, что видит)

Никакого обучения. Цифры крупные и контрастные — OCR берёт их напрямую.
"""
import os
import sys

import mss
import numpy as np
import pytesseract
from PIL import Image

# Путь к Tesseract (стандартный установщик UB Mannheim)
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Строка цифр «Текущая минимальная цена» (фуллскрин 2560x1440, mouse_xy: 1741/614 - 1841/645)
ZONE = {"left": 1736, "top": 612, "width": 160, "height": 40}

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def grab_zone():
    with mss.MSS() as sct:
        img = np.array(sct.grab(ZONE))
    return img[:, :, :3][:, :, ::-1]


def preprocess(img):
    """Готовим картинку под OCR: увеличим, переведём в ч/б с высоким контрастом."""
    pil = Image.fromarray(img.astype('uint8'))
    # OCR любит крупные буквы: увеличиваем x4
    pil = pil.resize((pil.width * 4, pil.height * 4), Image.LANCZOS)
    # ч/б с автопорогом
    gray = pil.convert("L")
    # инвертируем: tesseract лучше читает чёрный текст на белом
    inverted = Image.eval(gray, lambda x: 255 - x)
    # жёсткий контраст: всё темнее середины -> чёрное, остальное -> белое
    threshold = inverted.point(lambda x: 0 if x < 128 else 255)
    return threshold


def read_price():
    img = grab_zone()
    processed = preprocess(img)
    # PSM 7: «одна строка текста». whitelist — только цифры и запятая
    text = pytesseract.image_to_string(
        processed,
        config="--psm 7 -c tessedit_char_whitelist=0123456789,"
    ).strip()
    # убираем запятые-разделители: 12,500 -> 12500
    digits = text.replace(",", "").replace(" ", "")
    return digits


def test():
    print("t + Enter — прочитать цену, q + Enter — выход.")
    print()

    while True:
        cmd = input("Прочитать? (t — да, q — выход): ").strip().lower()
        if cmd == "q":
            break
        if cmd != "t":
            continue

        try:
            result = read_price()
        except Exception as e:
            print(f"  Ошибка: {e}")
            if "tesseract" in str(e).lower() or "Failed" in str(e):
                print("  Tesseract не найден — проверь путь в tesseract_cmd")
            continue

        if not result:
            print("  Пусто — цифры не найдены. Окно продажи открыто? Цена видна?")
            continue

        print(f"  Прочитано: {result}")


def dump():
    img = grab_zone()
    processed = preprocess(img)
    processed.save(os.path.join(OUT_DIR, "dump_processed.png"))
    Image.fromarray(img.astype('uint8')).save(os.path.join(OUT_DIR, "dump_color.png"))
    print("Сохранено: dump_color.png (сырая зона), dump_processed.png (что видит OCR)")
    try:
        result = read_price()
        print(f"OCR прочитал: {result or '(пусто)'}")
    except Exception as e:
        print(f"Ошибка OCR: {e}")
    input("Enter — выход")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "test":
        test()
    elif mode == "dump":
        dump()
    else:
        print("Запуск: python auction_eye.py test — чтение цены")
        print("        python auction_eye.py dump — диагностика")