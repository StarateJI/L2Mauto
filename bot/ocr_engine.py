"""
bot/ocr_engine.py — OCR движок с RapidOCR + VLM fallback.

Иерархия:
1. RapidOCR (локальный, быстрый, бесплатный) — основной
2. VLM через z-ai-web-dev-sdk (облачный, точный) — fallback если RapidOCR не нашёл
3. Tesseract (старый, кривой) — последний fallback

Используется для распознавания текста в игре:
- поиск "Благословенная Земля" в списке данжей
- чтение статусов лотов на аукционе
- чтение цен
"""
from __future__ import annotations

import os
import io
import base64
import subprocess
import tempfile
from typing import Optional, Tuple, List

import cv2
import numpy as np

from bot.clogger import log


# ── RapidOCR singleton (ленивая инициализация) ──────────────────────────────
_rapidocr = None
_rapidocr_failed = False


def get_rapidocr():
    """Возвращает экземпляр RapidOCR или None если не установлен."""
    global _rapidocr, _rapidocr_failed
    if _rapidocr_failed:
        return None
    if _rapidocr is not None:
        return _rapidocr
    try:
        from rapidocr_onnxruntime import RapidOCR
        _rapidocr = RapidOCR()
        log("OCR: RapidOCR инициализирован", level="DEBUG")
        return _rapidocr
    except ImportError:
        log("OCR: rapidocr-onnxruntime не установлен — pip install rapidocr-onnxruntime",
            level="WARNING")
        _rapidocr_failed = True
        return None
    except Exception as e:
        log(f"OCR: RapidOCR init failed: {e}", level="WARNING")
        _rapidocr_failed = True
        return None


# ── Tesseract fallback ─────────────────────────────────────────────────────
_tesseract = None


def get_tesseract():
    """Возвращает pytesseract или None."""
    global _tesseract
    if _tesseract is not None:
        return _tesseract
    try:
        import pytesseract as pt
        for cand in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                     r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                     r"C:\Tesseract-OCR\tesseract.exe"):
            if os.path.exists(cand):
                pt.pytesseract.tesseract_cmd = cand
                break
        _tesseract = pt
        return _tesseract
    except ImportError:
        return None
    except Exception as e:
        log(f"OCR: tesseract init failed: {e}", level="WARNING")
        return None


# ── VLM через z-ai CLI ─────────────────────────────────────────────────────

def vlm_find_text(img_bgr: np.ndarray, needle: str) -> Optional[Tuple[int, int]]:
    """
    Спросить VLM через z-ai CLI: видит ли он needle на скриншоте?
    Если видит — вернуть примерные координаты (x, y) центра слова.
    Если не видит — None.

    Использует: z-ai vision -p "..." -i image.png
    На Windows z-ai CLI может быть не установлен — в этом случае
    возвращаем None (fallback на Tesseract).
    """
    tmp_path = None
    try:
        # Сохраняем изображение во временный файл
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        cv2.imwrite(tmp_path, img_bgr)

        # Формируем запрос к VLM
        prompt = (f"Это скриншот из игры Lineage 2M. "
                  f"Найди на скрине текст '{needle}'. "
                  f"Если видишь — ответь ТОЛЬКО координатами центра слова "
                  f"в формате 'X,Y' (в пикселях, размер изображения "
                  f"{img_bgr.shape[1]}x{img_bgr.shape[0]}). "
                  f"Если не видишь — ответь 'NO'.")

        # Запускаем z-ai vision CLI
        # ВАЖНО: проверяем что z-ai есть в PATH через shutil.which
        import shutil
        zai_path = shutil.which("z-ai")
        if zai_path is None:
            log("VLM: z-ai CLI не найден в PATH — пропускаю VLM",
                level="DEBUG")
            return None

        result = subprocess.run(
            [zai_path, "vision", "-p", prompt, "-i", tmp_path],
            capture_output=True, text=True, timeout=30
        )

        if result.returncode != 0:
            log(f"VLM: CLI упал: {result.stderr[:200]}", level="DEBUG")
            return None

        # Парсим ответ — ищем "X,Y" или "NO"
        output = result.stdout.strip()
        if "NO" in output.upper():
            return None

        # Ищем числа через запятую
        import re
        match = re.search(r'(\d+)\s*[,]\s*(\d+)', output)
        if match:
            x = int(match.group(1))
            y = int(match.group(2))
            log(f"VLM: нашёл '{needle}' на ({x},{y})", level="DEBUG")
            return (x, y)

        log(f"VLM: не распарсил ответ: {output[:100]}", level="DEBUG")
        return None

    except subprocess.TimeoutExpired:
        log("VLM: timeout 30 сек", level="WARNING")
        return None
    except FileNotFoundError:
        log("VLM: z-ai CLI не найден — пропускаю", level="DEBUG")
        return None
    except Exception as e:
        log(f"VLM: ошибка: {e}", level="WARNING")
        return None
    finally:
        # Удаляем временный файл
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ── ОСНОВНОЙ МЕТОД: find_text ──────────────────────────────────────────────

def find_text(img_bgr: np.ndarray,
              needles: List[str],
              use_vlm: bool = True) -> Tuple[bool, int]:
    """
    Найти любой из needles в изображении.

    Иерархия:
    1. RapidOCR — быстрый локальный OCR
    2. VLM через z-ai — точный облачный (если RapidOCR не нашёл)
    3. Tesseract — старый fallback

    Args:
        img_bgr: BGR numpy array
        needles: список строк (lowercase) для поиска
        use_vlm: использовать VLM как fallback (default True)

    Returns:
        (found: bool, y_pixel: int) — y пиксель центра найденного слова
    """
    if img_bgr is None:
        return False, 0

    needles_lower = [n.lower() for n in needles]

    # ── 1. RapidOCR ─────────────────────────────────────────────────────
    rapid = get_rapidocr()
    if rapid is not None:
        try:
            # RapidOCR принимает путь или numpy array
            # x2 resize для лучшего распознавания мелкого шрифта
            h, w = img_bgr.shape[:2]
            big = cv2.resize(img_bgr, (w * 2, h * 2),
                             interpolation=cv2.INTER_CUBIC)
            result, _ = rapid(big)
            if result:
                # result = [(box, text, score), ...]
                # box = [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                all_text = " ".join(r[1] for r in result).lower()
                log(f"OCR RapidOCR: '{all_text[:100]}'", level="DEBUG")

                for needle in needles_lower:
                    if needle in all_text:
                        # Нашли — ищем координаты
                        for box, text, score in result:
                            if needle in text.lower():
                                # Центр бокса
                                xs = [p[0] for p in box]
                                ys = [p[1] for p in box]
                                cx = int(sum(xs) / len(xs)) // 2  # делим на 2 (resize x2)
                                cy = int(sum(ys) / len(ys)) // 2
                                return True, cy
                log(f"OCR RapidOCR: текст найден но needles не совпали",
                    level="DEBUG")
        except Exception as e:
            log(f"OCR RapidOCR error: {e}", level="DEBUG")

    # ── 2. VLM fallback (если RapidOCR не нашёл) ────────────────────────
    if use_vlm:
        # VLM ищет первое слово из needles (самое длинное/уникальное)
        longest = max(needles_lower, key=len) if needles_lower else ""
        if longest:
            coords = vlm_find_text(img_bgr, longest)
            if coords is not None:
                return True, coords[1]

    # ── 3. Tesseract fallback ──────────────────────────────────────────
    pt = get_tesseract()
    if pt is not None:
        try:
            gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
            big = cv2.resize(gray, (gray.shape[1] * 2, gray.shape[0] * 2),
                             interpolation=cv2.INTER_CUBIC)
            _, thresh = cv2.threshold(big, 0, 255,
                                       cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            text = pt.image_to_string(thresh, lang="rus+eng",
                                       config="--psm 6").lower()
            log(f"OCR Tesseract: '{text[:80]}'", level="DEBUG")
            for needle in needles_lower:
                if needle in text:
                    data = pt.image_to_data(thresh, lang="rus+eng",
                                            config="--psm 6",
                                            output_type=pt.Output.DICT)
                    for i, word in enumerate(data["text"]):
                        if needle in word.lower():
                            y_orig = data["top"][i] // 2 + data["height"][i] // 4
                            return True, y_orig
                    return True, gray.shape[0] // 2
        except Exception as e:
            log(f"OCR Tesseract error: {e}", level="DEBUG")

    return False, 0


# ── Тест ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Тест: загрузить скриншот и найти "земля"
    import sys
    if len(sys.argv) < 2:
        print("Usage: python ocr_engine.py <image.png>")
        sys.exit(1)
    img = cv2.imread(sys.argv[1])
    if img is None:
        print(f"Cannot load {sys.argv[1]}")
        sys.exit(1)
    found, y = find_text(img, ["земля", "благословен", "благ"])
    print(f"Found: {found}, y={y}")
