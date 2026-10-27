"""
test_resolutions.py — тест OCR на разных разрешениях окна.

Использование:
1. Открой аукцион в игре, вкладка Продажа
2. Сними лот с продажи → откроется окно ввода цены (с калькулятором)
3. Запусти: python test_resolutions.py

Скрипт:
- Меняет размер окна на 1280x720, 960x540, 800×450, 640×360
- На каждом делает скрин зоны цены (ZONE_PRICE)
- Прогоняет OCR
- Сохраняет скрины в test_res_*.png
- Печатает результат
"""
import sys
import os
import time

# Добавляем папку бота в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pygetwindow as gw
import mss
import numpy as np
import cv2
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Зона цены при 1280×720 (window-relative)
# Будет масштабироваться пропорционально для других разрешений
BASE_W, BASE_H = 1280, 720
ZONE_PRICE_1280 = (868, 306, 80, 20)

RESOLUTIONS = [
    (1280, 720),
    (960, 540),
    (800, 450),
    (640, 360),
]

def find_window():
    """Найти окно Lineage2M."""
    windows = gw.getWindowsWithTitle("Lineage2M")
    if not windows:
        print("❌ Окно Lineage2M не найдено!")
        print("   Открой игру и убедись что окно существует.")
        return None
    return windows[0]

def scale_zone(zone, scale_x, scale_y):
    """Масштабировать зону под разрешение."""
    x, y, w, h = zone
    return (int(x * scale_x), int(y * scale_y), int(w * scale_x), int(h * scale_y))

def grab_zone(sct, win, zone):
    """Захват зоны экрана."""
    x, y, w, h = zone
    monitor = {"left": win.left + x, "top": win.top + y, "width": w, "height": h}
    shot = sct.grab(monitor)
    arr = np.array(shot)
    return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)

def ocr_price(img):
    """OCR цены из изображения."""
    h, w = img.shape[:2]
    # Увеличиваем x4
    big = cv2.resize(img, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    inv = cv2.bitwise_not(gray)
    _, thr = cv2.threshold(inv, 128, 255, cv2.THRESH_BINARY)

    text = pytesseract.image_to_string(
        thr,
        config="--psm 7 -c tessedit_char_whitelist=0123456789",
    ).strip()
    return text, thr

def main():
    print("=" * 60)
    print("  Тест OCR на разных разрешениях")
    print("=" * 60)

    win = find_window()
    if win is None:
        return

    print(f"\n✅ Найдено окно: {win.title}")
    print(f"   Текущий размер: {win.width}x{win.height}")
    print(f"   Позиция: ({win.left}, {win.top})")

    # Сохраняем исходный размер
    orig_w, orig_h = win.width, win.height
    orig_left, orig_top = win.left, win.top

    input("\n⚠️ Открой окно ввода цены (сними лот с продажи).")
    input("   Нажми Enter когда окно цены открыто и калькулятор виден...")

    sct = mss.mss()
    results = []

    for res_w, res_h in RESOLUTIONS:
        print(f"\n{'─' * 40}")
        print(f"  Тестирую {res_w}x{res_h}")

        # Меняем размер окна
        try:
            win = find_window()
            if win is None:
                print("  ❌ Окно потеряно!")
                continue

            win.resizeTo(res_w, res_h)
            time.sleep(1.5)  # ждём перерисовки

            # Масштабируем зону
            scale_x = res_w / BASE_W
            scale_y = res_h / BASE_H
            zone = scale_zone(ZONE_PRICE_1280, scale_x, scale_y)
            print(f"  Зона: {zone} (scale {scale_x:.2f}x{scale_y:.2f})")

            # Захват
            win = find_window()
            if win is None:
                print("  ❌ Окно потеряно после resize!")
                continue

            img = grab_zone(sct, win, zone)
            print(f"  Скрин: {img.shape[1]}x{img.shape[0]}")

            # Сохраняем сырой скрин
            raw_path = f"test_res_{res_w}x{res_h}_raw.png"
            cv2.imwrite(raw_path, img)
            print(f"  Сырой скрин: {raw_path}")

            # OCR
            text, thr = ocr_price(img)

            # Сохраняем обработанный
            thr_path = f"test_res_{res_w}x{res_h}_ocr.png"
            cv2.imwrite(thr_path, thr)

            print(f"  OCR результат: '{text}'")
            print(f"  Обработанный: {thr_path}")

            results.append((res_w, res_h, text, zone))

        except Exception as e:
            print(f"  ❌ Ошибка: {e}")
            results.append((res_w, res_h, f"ERROR: {e}", None))

    # Восстанавливаем размер
    print(f"\n{'─' * 40}")
    print(f"Восстанавливаю размер: {orig_w}x{orig_h}")
    try:
        win = find_window()
        if win:
            win.resizeTo(orig_w, orig_h)
            win.moveTo(orig_left, orig_top)
    except Exception:
        pass

    # Итог
    print(f"\n{'=' * 60}")
    print("  ИТОГИ ТЕСТА")
    print(f"{'=' * 60}")
    print(f"{'Разрешение':<15} {'Зона':<25} {'OCR':<15} {'Статус'}")
    print(f"{'─' * 60}")
    for res_w, res_h, text, zone in results:
        zone_str = str(zone) if zone else "N/A"
        status = "✅ OK" if text and text.isdigit() else "❌ FAIL"
        print(f"{res_w}x{res_h:<8} {zone_str:<25} '{text:<13}' {status}")

    print(f"\nСкрины сохранены: test_res_*.png")
    print(f"Отправь скрины боту если результаты плохие.")

    input("\nНажми Enter для выхода...")

if __name__ == "__main__":
    main()
