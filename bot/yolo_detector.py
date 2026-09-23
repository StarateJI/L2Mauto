"""
bot/yolo_detector.py — YOLOv8 детектор предметов для инвентаря.

Логика:
1. YOLOv8 находит все слоты предметов (bounding boxes)
2. Для каждого слота: вырезаем иконку → сравниваем с образцом
   через perceptual hash (pHash) + normalized cross-correlation
3. Если совпадает + красная точка рядом → клик

ВАЖНО: попиксельное сравнение (absdiff) НЕ РАБОТАЕТ для иконок разного
размера — sample из вкладки Продажа (60×53) больше чем иконка в инвентаре
(~40×35). При ресайзе появляется мыло, absdiff даёт мусор.
Поэтому используем pHash (DCT-based) + TM_CCOEFF_NORMED — оба
устойчивы к разному размеру, мылу, лёгким сдвигам цвета.
"""
from __future__ import annotations

import os
from typing import Optional, Tuple, List

import numpy as np
import cv2

from bot.clogger import log


# ── YOLOv8 singleton ────────────────────────────────────────────────────────
_yolo_model = None
_yolo_failed = False

MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "models", "item_detector.pt")


def get_model():
    """Возвращает YOLOv8 модель или None."""
    global _yolo_model, _yolo_failed
    if _yolo_failed:
        return None
    if _yolo_model is not None:
        return _yolo_model

    if not os.path.exists(MODEL_PATH):
        log(f"YOLO: модель не найдена: {MODEL_PATH}", level="WARNING")
        _yolo_failed = True
        return None

    try:
        from ultralytics import YOLO
        _yolo_model = YOLO(MODEL_PATH)
        log(f"YOLO: модель загружена ({MODEL_PATH})", level="DEBUG")
        return _yolo_model
    except ImportError:
        log("YOLO: ultralytics не установлен — pip install ultralytics",
            level="WARNING")
        _yolo_failed = True
        return None
    except Exception as e:
        log(f"YOLO: init failed: {e}", level="WARNING")
        _yolo_failed = True
        return None


def detect_items(img_bgr: np.ndarray, conf_threshold: float = 0.15) -> List[Tuple[int, int, int, int, float]]:
    """
    Найти все слоты предметов через YOLOv8.

    Returns:
        [(cx, cy, w, h, conf), ...]
    """
    model = get_model()
    if model is None or img_bgr is None:
        return []

    try:
        results = model(img_bgr, conf=conf_threshold, verbose=False)

        items = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for box in boxes:
                xywh = box.xywh[0].cpu().numpy()
                conf = float(box.conf[0].cpu().numpy())
                cx, cy, w, h = int(xywh[0]), int(xywh[1]), int(xywh[2]), int(xywh[3])
                items.append((cx, cy, w, h, conf))

        return items
    except Exception as e:
        log(f"YOLO: detect error: {e}", level="WARNING")
        return []


# ── Иконка сравнения ────────────────────────────────────────────────────────

def _to_gray(img: np.ndarray) -> np.ndarray:
    if img is None:
        return None
    if len(img.shape) == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def _phash(gray: np.ndarray, hash_size: int = 16) -> np.ndarray:
    """
    Perceptual hash через DCT.
    Устойчив к: разному размеру, мылу от ресайза, лёгким сдвигам яркости.

    1. Resize → 32×32 grayscale
    2. DCT (discrete cosine transform)
    3. Берём top-left hash_size×hash_size (низкие частоты = общая структура)
    4. Исключаем DC (первый элемент)
    5. hash[i] = 1 если coeff > mean, иначе 0

    hash_size=16 → 255 бит (достаточно дискриминации для игровых иконок)
    """
    g = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    g = np.float32(g)
    dct = cv2.dct(g)
    dct_low = dct[:hash_size, :hash_size].flatten()
    dct_low = dct_low[1:]  # исключаем DC
    mean = dct_low.mean()
    return (dct_low > mean).astype(np.uint8)


def _dhash(gray: np.ndarray) -> np.ndarray:
    """
    Difference hash.
    Устойчив к: яркости, экспозиции.
    hash[i] = 1 если pixel_left > pixel_right, иначе 0.
    """
    g = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    return (g[:, 1:] > g[:, :-1]).flatten().astype(np.uint8)


def _hamming(h1: np.ndarray, h2: np.ndarray) -> int:
    """Hamming distance между двумя хешами."""
    return int(np.count_nonzero(h1 != h2))


def _corr_norm(gray1: np.ndarray, gray2: np.ndarray, size=(60, 53)) -> float:
    """
    Нормализованная кросс-корреляция (TM_CCOEFF_NORMED).
    Обе иконки ресайзятся к одному размеру, потом корреляция.
    Возвращает -1..1, конвертируем в 0..1.
    """
    g1 = cv2.resize(gray1, size, interpolation=cv2.INTER_AREA)
    g2 = cv2.resize(gray2, size, interpolation=cv2.INTER_AREA)
    g1 = np.float32(g1)
    g2 = np.float32(g2)
    res = cv2.matchTemplate(g1, g2, cv2.TM_CCOEFF_NORMED)
    val = float(res[0, 0])
    return max(0.0, val)  # отрицательная корреляция = не совпадает


def compare_icons(icon1: np.ndarray, icon2: np.ndarray) -> float:
    """
    Сравнить две иконки. Устойчиво к разному размеру иконок.

    Использует 3 метода, берёт СРЕДНЕЕ (не max — max давал ложные совпадения
    на похожих иконках типа shield vs potion):

    1. pHash (DCT-based, 255 бит) — структура изображения
    2. dHash (difference) — градиенты
    3. TM_CCOEFF_NORMED — нормализованная корреляция

    Тесты показали: та же иконка → avg 0.93, разные → avg 0.49-0.63.
    Threshold 0.70 хорошо разделяет.

    Returns: score 0.0-1.0 (1.0 = идентичные)
    """
    if icon1 is None or icon2 is None:
        return 0.0
    if icon1.size == 0 or icon2.size == 0:
        return 0.0

    g1 = _to_gray(icon1)
    g2 = _to_gray(icon2)

    try:
        # pHash (255 бит при hash_size=16)
        ph1 = _phash(g1)
        ph2 = _phash(g2)
        ph_dist = _hamming(ph1, ph2)
        nbits = ph1.shape[0]
        phash_score = 1.0 - (ph_dist / nbits)

        # dHash (64 бита)
        dh1 = _dhash(g1)
        dh2 = _dhash(g2)
        dh_dist = _hamming(dh1, dh2)
        dhash_score = 1.0 - (dh_dist / 64.0)

        # Normalized cross-correlation
        corr_score = _corr_norm(g1, g2)

        # СРЕДНЕЕ — лучше разделяет та же/разные чем max
        score = (phash_score + dhash_score + corr_score) / 3.0
        return float(score)
    except Exception as e:
        log(f"compare_icons: error: {e}", level="DEBUG")
        return 0.0


def find_item(img_bgr: np.ndarray, sample_bgr: np.ndarray,
              conf_threshold: float = 0.15,
              match_threshold: float = 0.70) -> Optional[Tuple[int, int, float]]:
    """
    Найти конкретный предмет в инвентаре.

    1. YOLOv8 находит все слоты
    2. Для каждого слота: вырезаем иконку → compare_icons (pHash+dHash+corr)
    3. Возвращает центр лучшего совпадения

    Args:
        img_bgr: скриншот инвентаря
        sample_bgr: иконка предмета (образец из вкладки Продажа)
        conf_threshold: минимальная уверенность YOLO (0.15 — ниже, больше слотов)
        match_threshold: минимальный score совпадения (0.65 = 65%)

    Returns:
        (cx, cy, score) или None
    """
    if img_bgr is None or sample_bgr is None:
        log("YOLO find_item: img или sample None", level="DEBUG")
        return None

    sample_h, sample_w = sample_bgr.shape[:2]
    log(f"YOLO find_item: sample {sample_w}×{sample_h}, "
        f"inv {img_bgr.shape[1]}×{img_bgr.shape[0]}", level="DEBUG")

    # 1. YOLOv8 находит все слоты
    items = detect_items(img_bgr, conf_threshold)
    if not items:
        log(f"YOLO find_item: YOLO нашёл 0 слотов (conf={conf_threshold}) — "
            f"модель не загружена или нет детекций", level="WARNING")
        return None

    log(f"YOLO find_item: YOLO нашёл {len(items)} слотов, "
        f"сравниваю с образцом {sample_w}×{sample_h}", level="DEBUG")

    best_match = None
    best_score = 0.0
    all_scores = []

    for (cx, cy, w, h, conf) in items:
        # Вырезаем иконку из слота
        x1 = max(0, cx - w // 2)
        y1 = max(0, cy - h // 2)
        x2 = min(img_bgr.shape[1], cx + w // 2)
        y2 = min(img_bgr.shape[0], cy + h // 2)

        slot_img = img_bgr[y1:y2, x1:x2]
        if slot_img.size == 0 or w < 5 or h < 5:
            continue

        # Сравниваем с образцом
        score = compare_icons(slot_img, sample_bgr)
        all_scores.append((score, cx, cy, w, h, conf))

        if score > best_score:
            best_score = score
            if score >= match_threshold:
                best_match = (cx, cy, score)

    # Сортируем по score для лога
    all_scores.sort(reverse=True)

    # Логируем ТОП-5 слотов
    for score, cx, cy, w, h, conf in all_scores[:5]:
        mark = " ★ MATCH" if score >= match_threshold else ""
        log(f"YOLO: слот ({cx},{cy}) {w}×{h} conf={conf:.2f} "
            f"score={score:.3f}{mark}", level="DEBUG")

    log(f"YOLO find_item: лучший score={best_score:.3f} "
        f"(порог {match_threshold}) из {len(items)} слотов",
        level="DEBUG")

    if best_match is not None:
        return best_match

    log(f"YOLO find_item: предмет не найден — лучший score "
        f"{best_score:.3f} < порога {match_threshold}", level="WARNING")
    return None
