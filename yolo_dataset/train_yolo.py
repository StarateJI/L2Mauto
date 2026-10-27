#!/usr/bin/env python3
"""
train_yolo.py — Обучение YOLOv8 для детекции предметов в инвентаре.

Использование:
    pip install ultralytics
    python train_yolo.py

Результат: runs/detect/train/weights/best.pt — обученная модель
"""

import os
import sys
import random
import shutil

# Проверка ultralytics
try:
    from ultralytics import YOLO
except ImportError:
    print("ERROR: ultralytics не установлен")
    print("Run: pip install ultralytics")
    sys.exit(1)

DATASET_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES_DIR = os.path.join(DATASET_DIR, "images")
LABELS_DIR = os.path.join(DATASET_DIR, "labels")

# Структура YOLO dataset
TRAIN_IMAGES = os.path.join(DATASET_DIR, "train", "images")
TRAIN_LABELS = os.path.join(DATASET_DIR, "train", "labels")
VAL_IMAGES = os.path.join(DATASET_DIR, "val", "images")
VAL_LABELS = os.path.join(DATASET_DIR, "val", "labels")

# data.yaml для YOLO
DATA_YAML = os.path.join(DATASET_DIR, "data.yaml")


def prepare_dataset(val_ratio=0.2):
    """Разделить изображения на train/val."""
    import glob
    
    images = sorted(glob.glob(os.path.join(IMAGES_DIR, "*au_page*.png")))
    if not images:
        print("No images found")
        return
    
    print(f"Found {len(images)} images")
    
    # Очистка
    for d in (TRAIN_IMAGES, TRAIN_LABELS, VAL_IMAGES, VAL_LABELS):
        if os.path.exists(d):
            shutil.rmtree(d)
        os.makedirs(d, exist_ok=True)
    
    # Перемешиваем
    random.seed(42)
    random.shuffle(images)
    
    val_count = max(1, int(len(images) * val_ratio))
    val_images = images[:val_count]
    train_images = images[val_count:]
    
    print(f"Train: {len(train_images)}, Val: {len(val_images)}")
    
    # Копируем train
    for img_path in train_images:
        basename = os.path.basename(img_path)
        name = os.path.splitext(basename)[0]
        
        shutil.copy2(img_path, os.path.join(TRAIN_IMAGES, basename))
        
        label_path = os.path.join(LABELS_DIR, name + ".txt")
        if os.path.exists(label_path):
            shutil.copy2(label_path, os.path.join(TRAIN_LABELS, name + ".txt"))
        else:
            # Пустой файл
            open(os.path.join(TRAIN_LABELS, name + ".txt"), "w").close()
    
    # Копируем val
    for img_path in val_images:
        basename = os.path.basename(img_path)
        name = os.path.splitext(basename)[0]
        
        shutil.copy2(img_path, os.path.join(VAL_IMAGES, basename))
        
        label_path = os.path.join(LABELS_DIR, name + ".txt")
        if os.path.exists(label_path):
            shutil.copy2(label_path, os.path.join(VAL_LABELS, name + ".txt"))
        else:
            open(os.path.join(VAL_LABELS, name + ".txt"), "w").close()
    
    # data.yaml
    yaml_content = f"""path: {DATASET_DIR}
train: train/images
val: val/images

names:
  0: item
"""
    with open(DATA_YAML, "w") as f:
        f.write(yaml_content)
    
    print(f"data.yaml saved: {DATA_YAML}")


def train():
    """Обучить YOLOv8."""
    # Модель: yolov8n (nano) — маленькая и быстрая, ~3MB
    model = YOLO("yolov8n.pt")
    
    results = model.train(
        data=DATA_YAML,
        imgsz=640,          # размер входа
        batch=8,            # batch size (уменьшить если мало RAM)
        device="cpu",       # CPU (AMD GPU не поддерживает CUDA, а ROCm только Linux)
        epochs=100,         # 100 эпох (~30-40 мин на CPU для 45 скринов)
        save=True,
        project=os.path.join(DATASET_DIR, "runs"),
        name="train",
    )
    
    print(f"\n=== TRAINING DONE ===")
    print(f"Best model: {os.path.join(DATASET_DIR, 'runs', 'train', 'weights', 'best.pt')}")
    print(f"Copy best.pt to bot/models/item_detector.pt")


if __name__ == "__main__":
    prepare_dataset(val_ratio=0.2)
    train()
