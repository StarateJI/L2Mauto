"""
bot/yolo_detector.py — YOLOv8 детектор предметов для инвентаря.

Использует обученную модель (item_detector.pt) для нахождения всех слотов
предметов в инвентаре. Потом сравнивает каждый слот с образцом через ORB.

Иерархия:
1. YOLOv8 находит все слоты предметов (быстро, ~30ms)
2. Для каждого слота: ORB/SIFT сравнение с образцом (быстро, маленькая картинка)
3. Если совпало + красная точка рядом → клик
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

# Путь к модели
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
        log("YOLO: модель загружена", level="DEBUG")
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


def detect_items(img_bgr: np.ndarray, conf_threshold: float = 0.3) -> List[Tuple[int, int, int, int, float]]:
    """
    Найти все предметы на скриншоте через YOLOv8.
    
    Args:
        img_bgr: BGR numpy array (скриншот инвентаря)
        conf_threshold: минимальная уверенность (0-1)
    
    Returns:
        Список [(cx, cy, w, h, conf), ...] — координаты в пикселях.
        cx, cy — центр предмета. w, h — размер рамки.
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
                # box.xywh = [cx, cy, w, h] в пикселях
                xywh = box.xywh[0].cpu().numpy()
                conf = float(box.conf[0].cpu().numpy())
                cx, cy, w, h = int(xywh[0]), int(xywh[1]), int(xywh[2]), int(xywh[3])
                items.append((cx, cy, w, h, conf))
        
        return items
    except Exception as e:
        log(f"YOLO: detect error: {e}", level="DEBUG")
        return []


def find_item(img_bgr: np.ndarray, sample_bgr: np.ndarray,
              conf_threshold: float = 0.3,
              match_threshold: int = 10) -> Optional[Tuple[int, int, float]]:
    """
    Найти конкретный предмет в инвентаре.
    
    1. YOLOv8 находит все слоты
    2. Для каждого слота: ORB сравнение с образцом
    3. Возвращает центр лучшего совпадения
    
    Args:
        img_bgr: BGR numpy array (скриншот инвентаря)
        sample_bgr: BGR numpy array (иконка предмета)
        conf_threshold: минимальная уверенность YOLO
        match_threshold: минимальное количество ORB совпадений
    
    Returns:
        (cx, cy, matches) или None
    """
    if img_bgr is None or sample_bgr is None:
        return None
    
    # 1. YOLOv8 находит все слоты
    items = detect_items(img_bgr, conf_threshold)
    if not items:
        log("YOLO: предметов не найдено", level="DEBUG")
        return None
    
    log(f"YOLO: найдено {len(items)} слотов, сравниваю с образцом",
        level="DEBUG")
    
    # 2. ORB для сравнения иконок (быстрее SIFT, не зависает)
    try:
        orb = cv2.ORB_create(nfeatures=100)
        kp_sample, desc_sample = orb.detectAndCompute(sample_bgr, None)
        if desc_sample is None or len(desc_sample) < 5:
            log(f"YOLO: образец имеет мало ORB точек ({len(kp_sample)})",
                level="DEBUG")
            return None
    except Exception as e:
        log(f"YOLO: ORB init error: {e}", level="DEBUG")
        return None
    
    # BF matcher для ORB (быстрый)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    
    best_match = None  # (cx, cy, num_matches)
    
    for (cx, cy, w, h, conf) in items:
        # Вырезаем иконку из слота
        x1 = max(0, cx - w // 2)
        y1 = max(0, cy - h // 2)
        x2 = min(img_bgr.shape[1], cx + w // 2)
        y2 = min(img_bgr.shape[0], cy + h // 2)
        
        slot_img = img_bgr[y1:y2, x1:x2]
        if slot_img.size == 0:
            continue
        
        # ORB на слоте
        try:
            kp_slot, desc_slot = orb.detectAndCompute(slot_img, None)
            if desc_slot is None or len(desc_slot) < 3:
                continue
            
            matches = bf.match(desc_sample, desc_slot)
            good_matches = [m for m in matches if m.distance < 50]
            
            if len(good_matches) >= match_threshold:
                if best_match is None or len(good_matches) > best_match[2]:
                    best_match = (cx, cy, len(good_matches))
                    log(f"YOLO: слот ({cx},{cy}) — {len(good_matches)} ORB matches",
                        level="DEBUG")
        except Exception:
            continue
    
    if best_match is not None:
        return best_match
    
    log("YOLO: предмет не найден ни в одном слоте", level="DEBUG")
    return None
