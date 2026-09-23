"""
bot/yolo_detector.py — YOLOv8 детектор предметов для инвентаря.

Логика:
1. YOLOv8 находит все слоты предметов
2. Для каждого слота: вырезаем иконку → сравниваем с образцом
   через histogram correlation (без ORB, без matchTemplate)
3. Если совпадает + красная точка рядом → клик
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
        log("YOLO: модель загружена", level="DEBUG")
        return _yolo_model
    except ImportError:
        log("YOLO: ultralytics не установлен", level="WARNING")
        _yolo_failed = True
        return None
    except Exception as e:
        log(f"YOLO: init failed: {e}", level="WARNING")
        _yolo_failed = True
        return None


def detect_items(img_bgr: np.ndarray, conf_threshold: float = 0.3) -> List[Tuple[int, int, int, int, float]]:
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
        log(f"YOLO: detect error: {e}", level="DEBUG")
        return []


def compare_icons(icon1: np.ndarray, icon2: np.ndarray) -> float:
    """
    Сравнить две иконки через histogram correlation.
    Возвращает score 0.0-1.0 (1.0 = идентичные).
    
    Как это работает:
    1. Resize обе иконки к одному размеру (60x53)
    2. Считаем цветовые гистограммы
    3. Сравниваем гистограммы через correlation
    
    Это надёжнее ORB — работает как человек: "та же картинка или нет".
    """
    if icon1 is None or icon2 is None:
        return 0.0
    
    # Resize к одному размеру
    h, w = 53, 60
    img1 = cv2.resize(icon1, (w, h), interpolation=cv2.INTER_AREA)
    img2 = cv2.resize(icon2, (w, h), interpolation=cv2.INTER_AREA)
    
    # Гистограммы по каждому каналу (HSV — устойчивее к освещению)
    hsv1 = cv2.cvtColor(img1, cv2.COLOR_BGR2HSV)
    hsv2 = cv2.cvtColor(img2, cv2.COLOR_BGR2HSV)
    
    # H: 0-180, S: 0-256, V: 0-256
    channels = [0, 1, 2]
    hist_size = [50, 50, 50]
    ranges = [0, 180, 0, 256, 0, 256]
    
    hist1 = cv2.calcHist([hsv1], channels, None, hist_size, ranges)
    hist2 = cv2.calcHist([hsv2], channels, None, hist_size, ranges)
    
    cv2.normalize(hist1, hist1, 0, 1, cv2.NORM_MINMAX)
    cv2.normalize(hist2, hist2, 0, 1, cv2.NORM_MINMAX)
    
    score = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
    return float(score)


def find_item(img_bgr: np.ndarray, sample_bgr: np.ndarray,
              conf_threshold: float = 0.3,
              match_threshold: float = 0.7) -> Optional[Tuple[int, int, float]]:
    """
    Найти конкретный предмет в инвентаре.
    
    1. YOLOv8 находит все слоты
    2. Для каждого слота: вырезаем иконку → сравниваем с образцом
       через histogram correlation
    3. Возвращает центр лучшего совпадения
    
    Args:
        img_bgr: скриншот инвентаря
        sample_bgr: иконка предмета (образец)
        conf_threshold: минимальная уверенность YOLO
        match_threshold: минимальный score совпадения (0.7 = 70% схожести)
    
    Returns:
        (cx, cy, score) или None
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
    
    best_match = None
    best_score = 0.0
    
    for (cx, cy, w, h, conf) in items:
        # Вырезаем иконку из слота
        x1 = max(0, cx - w // 2)
        y1 = max(0, cy - h // 2)
        x2 = min(img_bgr.shape[1], cx + w // 2)
        y2 = min(img_bgr.shape[0], cy + h // 2)
        
        slot_img = img_bgr[y1:y2, x1:x2]
        if slot_img.size == 0:
            continue
        
        # Сравниваем с образцом
        score = compare_icons(slot_img, sample_bgr)
        
        # Логируем ВСЕ слоты — видим какие score
        if score > 0.3:
            log(f"YOLO: слот ({cx},{cy}) score={score:.3f} conf={conf:.2f}",
                level="DEBUG")
        
        if score > best_score:
            best_score = score
            if score >= match_threshold:
                best_match = (cx, cy, score)
                log(f"YOLO: СОВПАДЕНИЕ ({cx},{cy}) score={score:.3f}",
                    level="DEBUG")
    
    log(f"YOLO: лучший score={best_score:.3f} (порог {match_threshold})",
        level="DEBUG")
    
    if best_match is not None:
        return best_match
    
    log("YOLO: предмет не найден ни в одном слоте", level="DEBUG")
    return None
