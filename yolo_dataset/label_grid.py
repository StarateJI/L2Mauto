#!/usr/bin/env python3
"""
label_grid.py — Авто-разметка скриншотов инвентаря по сетке.

Инвентарь Lineage 2M — регулярная сетка предметов.
Анализируем яркость по строкам/колонкам → находим центры предметов →
сохраняем YOLO разметку.

YOLO формат: class x_center y_center width height (нормализованные 0-1)
"""

import os
import sys
import glob
import cv2
import numpy as np
from scipy.signal import find_peaks

IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
LABELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labels")

os.makedirs(LABELS_DIR, exist_ok=True)

# Размер ячейки предмета в пикселях (примерно)
ITEM_W = 55
ITEM_H = 53


def detect_grid_items(image_path):
    """
    Найти все предметы на скриншоте инвентаря через анализ яркости.
    Возвращает список [(cx, cy, w, h), ...] в пикселях.
    """
    img = cv2.imread(image_path)
    if img is None:
        return []
    
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    
    # Средняя яркость по колонкам и строкам
    mean_cols = gray.mean(axis=0)
    mean_rows = gray.mean(axis=1)
    
    # Пики = центры предметов (ярче фона)
    col_threshold = mean_cols.mean() + 3
    row_threshold = mean_rows.mean() + 3
    
    col_peaks, _ = find_peaks(mean_cols, height=col_threshold, distance=50)
    row_peaks, _ = find_peaks(mean_rows, height=row_threshold, distance=50)
    
    # Если пиков мало — пробуем другой порог
    if len(col_peaks) < 3:
        col_peaks, _ = find_peaks(mean_cols, height=mean_cols.mean(), distance=50)
    if len(row_peaks) < 3:
        row_peaks, _ = find_peaks(mean_rows, height=mean_rows.mean(), distance=50)
    
    # Для каждого пересечения (колонка × строка) = предмет
    boxes = []
    for cx in col_peaks:
        for cy in row_peaks:
            # Проверяем что в этом месте действительно есть предмет
            # (не пустая ячейка — есть цветные пиксели)
            x1 = max(0, cx - ITEM_W // 2)
            y1 = max(0, cy - ITEM_H // 2)
            x2 = min(w, cx + ITEM_W // 2)
            y2 = min(h, cy + ITEM_H // 2)
            
            cell = gray[y1:y2, x1:x2]
            if cell.size == 0:
                continue
            
            # Проверяем: средняя яркость > порога (предмет есть)
            cell_mean = cell.mean()
            bg_mean = gray.mean()
            
            if cell_mean > bg_mean - 5:  # есть что-то
                boxes.append((cx, cy, ITEM_W, ITEM_H))
    
    return boxes


def save_yolo_label(image_path, boxes):
    """Сохранить разметку в YOLO формате."""
    img = cv2.imread(image_path)
    if img is None:
        return 0
    
    h, w = img.shape[:2]
    
    basename = os.path.splitext(os.path.basename(image_path))[0]
    label_path = os.path.join(LABELS_DIR, basename + ".txt")
    
    lines = []
    for (cx, cy, bw, bh) in boxes:
        # YOLO: class cx cy w h (нормализованные 0-1)
        ncx = max(0, min(1, cx / w))
        ncy = max(0, min(1, cy / h))
        nbw = max(0, min(1, bw / w))
        nbh = max(0, min(1, bh / h))
        lines.append(f"0 {ncx:.6f} {ncy:.6f} {nbw:.6f} {nbh:.6f}")
    
    with open(label_path, "w") as f:
        f.write("\n".join(lines))
    
    return len(lines)


def main():
    images = sorted(glob.glob(os.path.join(IMAGES_DIR, "*au_page*.png")))
    
    if not images:
        print("No au_page images found")
        return
    
    print(f"Found {len(images)} images to label")
    
    labeled = 0
    total_boxes = 0
    
    for img_path in images:
        basename = os.path.basename(img_path)
        boxes = detect_grid_items(img_path)
        
        if boxes:
            count = save_yolo_label(img_path, boxes)
            labeled += 1
            total_boxes += count
            print(f"  {basename}: {count} items")
        else:
            # Пустой файл (YOLO требует)
            label_path = os.path.join(LABELS_DIR,
                                      os.path.splitext(basename)[0] + ".txt")
            with open(label_path, "w") as f:
                pass
            print(f"  {basename}: 0 items (empty)")
    
    print(f"\n=== DONE ===")
    print(f"Labeled: {labeled}/{len(images)} images")
    print(f"Total boxes: {total_boxes}")
    print(f"Labels in: {LABELS_DIR}")


if __name__ == "__main__":
    main()
