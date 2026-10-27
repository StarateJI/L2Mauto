#!/usr/bin/env python3
"""
label_via_vlm.py — Авто-разметка скриншотов инвентаря через VLM.

Принцип:
1. Берём скриншот au_page_*.png (зона инвентаря 259×318)
2. Отправляем в z-ai vision: "найди все предметы, верни координаты рамок"
3. VLM возвращает координаты в формате YOLO
4. Сохраняем .txt файл разметки

YOLO формат: class x_center y_center width height (нормализованные 0-1)
"""

import os
import sys
import json
import subprocess
import glob

IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
LABELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "labels")

os.makedirs(LABELS_DIR, exist_ok=True)


def vlm_detect_items(image_path):
    """
    Отправить скриншот в z-ai vision и получить координаты предметов.
    Возвращает список [(cx, cy, w, h), ...] в пикселях.
    """
    import cv2
    img = cv2.imread(image_path)
    if img is None:
        print(f"  Cannot read {image_path}")
        return []
    
    h, w = img.shape[:2]
    
    prompt = (
        f"Это скриншот инвентаря из игры Lineage 2M (размер {w}x{h} пикселей). "
        f"Найди ВСЕ предметы (иконки) на этом скриншоте. "
        f"Для каждого предмета верни координаты рамки в формате: "
        f"x1,y1,x2,y2 где (x1,y1) — верхний левый угол, (x2,y2) — нижний правый. "
        f"Каждую рамку на отдельной строке. Ничего больше не пиши. "
        f"Если предметов нет — напиши 'NONE'."
    )
    
    try:
        result = subprocess.run(
            ["z-ai", "vision", "-p", prompt, "-i", image_path],
            capture_output=True, text=True, timeout=60
        )
        
        if result.returncode != 0:
            print(f"  VLM CLI failed: {result.stderr[:200]}")
            return []
        
        output = result.stdout.strip()
        
        # Парсим JSON если есть
        if output.startswith("{"):
            try:
                data = json.loads(output)
                output = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            except Exception:
                pass
        
        if not output or "NONE" in output.upper():
            return []
        
        # Парсим строки "x1,y1,x2,y2"
        boxes = []
        for line in output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # Ищем 4 числа через запятую
            import re
            nums = re.findall(r'\d+', line)
            if len(nums) >= 4:
                x1, y1, x2, y2 = int(nums[0]), int(nums[1]), int(nums[2]), int(nums[3])
                # Нормализуем если перепутаны
                if x1 > x2: x1, x2 = x2, x1
                if y1 > y2: y1, y2 = y2, y1
                boxes.append((x1, y1, x2, y2))
        
        return boxes
    
    except subprocess.TimeoutExpired:
        print(f"  VLM timeout")
        return []
    except Exception as e:
        print(f"  VLM error: {e}")
        return []


def save_yolo_label(image_path, boxes):
    """
    Сохранить разметку в YOLO формате.
    Формат: class x_center y_center width height (нормализованные 0-1)
    """
    import cv2
    img = cv2.imread(image_path)
    if img is None:
        return
    
    h, w = img.shape[:2]
    
    basename = os.path.splitext(os.path.basename(image_path))[0]
    label_path = os.path.join(LABELS_DIR, basename + ".txt")
    
    lines = []
    for (x1, y1, x2, y2) in boxes:
        # YOLO формат: class cx cy w h (нормализованные)
        cx = ((x1 + x2) / 2) / w
        cy = ((y1 + y2) / 2) / h
        bw = (x2 - x1) / w
        bh = (y2 - y1) / h
        
        # Ограничиваем 0-1
        cx = max(0, min(1, cx))
        cy = max(0, min(1, cy))
        bw = max(0, min(1, bw))
        bh = max(0, min(1, bh))
        
        # class 0 = "item"
        lines.append(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
    
    with open(label_path, "w") as f:
        f.write("\n".join(lines))
    
    print(f"  Saved {len(lines)} boxes → {os.path.basename(label_path)}")


def main():
    images = sorted(glob.glob(os.path.join(IMAGES_DIR, "*au_page*.png")))
    
    if not images:
        print("No au_page_*.png found in images/")
        print(f"Looking in: {IMAGES_DIR}")
        return
    
    print(f"Found {len(images)} images to label")
    
    labeled = 0
    total_boxes = 0
    
    for img_path in images:
        basename = os.path.basename(img_path)
        print(f"\nLabeling: {basename}")
        
        boxes = vlm_detect_items(img_path)
        
        if boxes:
            save_yolo_label(img_path, boxes)
            labeled += 1
            total_boxes += len(boxes)
            print(f"  Found {len(boxes)} items")
        else:
            print(f"  No items found")
            # Сохраняем пустой файл (YOLO требует)
            label_path = os.path.join(LABELS_DIR,
                                      os.path.splitext(basename)[0] + ".txt")
            with open(label_path, "w") as f:
                pass
    
    print(f"\n=== DONE ===")
    print(f"Labeled: {labeled}/{len(images)} images")
    print(f"Total boxes: {total_boxes}")
    print(f"Labels saved in: {LABELS_DIR}")


if __name__ == "__main__":
    main()
