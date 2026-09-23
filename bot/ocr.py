"""
bot/ocr.py — OCR через RapidOCR (PaddleOCR на ONNX).

RapidOCR — предобученная модель для русского текста.
Точнее Tesseract в 5-10 раз для мелкого шрифта в играх.
"""
from __future__ import annotations

from typing import Optional, Tuple, List

import numpy as np

from bot.clogger import log


_engine = None
_engine_failed = False


def get_engine():
    """Возвращает экземпляр RapidOCR или None."""
    global _engine, _engine_failed
    if _engine_failed:
        return None
    if _engine is not None:
        return _engine
    try:
        from rapidocr_onnxruntime import RapidOCR
        _engine = RapidOCR()
        log("OCR: RapidOCR инициализирован", level="DEBUG")
        return _engine
    except ImportError:
        log("OCR: rapidocr-onnxruntime не установлен — "
            "pip install rapidocr-onnxruntime", level="WARNING")
        _engine_failed = True
        return None
    except Exception as e:
        log(f"OCR: RapidOCR init failed: {e}", level="WARNING")
        _engine_failed = True
        return None


def recognize(img_bgr: np.ndarray) -> List[Tuple[str, float]]:
    """
    Распознать текст на изображении.
    Returns: список (text, confidence).
    """
    engine = get_engine()
    if engine is None or img_bgr is None:
        return []
    try:
        result, _ = engine(img_bgr)
        if result is None:
            return []
        return [(item[1], item[2]) for item in result]
    except Exception as e:
        log(f"OCR: recognize error: {e}", level="DEBUG")
        return []


def recognize_text(img_bgr: np.ndarray) -> str:
    """Распознать текст → строка (lowercase)."""
    results = recognize(img_bgr)
    if not results:
        return ""
    return " ".join(text for text, _ in results).lower()


def recognize_digits(img_bgr: np.ndarray) -> Optional[int]:
    """Распознать число (для цены)."""
    if img_bgr is None:
        return None
    engine = get_engine()
    if engine is None:
        return None
    try:
        result, _ = engine(img_bgr)
        if result is None:
            return None
        all_text = " ".join(item[1] for item in result)
        log(f"OCR price: '{all_text}'", level="DEBUG")
        import re
        digits = re.sub(r'[^\d]', '', all_text)
        if digits:
            digits = digits.lstrip('0') or '0'
            return int(digits)
    except Exception as e:
        log(f"OCR: recognize_digits error: {e}", level="DEBUG")
    return None
