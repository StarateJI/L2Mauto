"""
bot/ollama_vlm.py — VLM через Ollama (локально, бесплатно).

Бот отправляет картинку (base64) + вопрос на локальный Ollama.
Ollama работает на http://localhost:11434.

Использование:
    from bot.ollama_vlm import vlm_ask
    answer = vlm_ask(img_bgr, "Есть красная точка? Координаты?")
"""
from __future__ import annotations

import base64
import cv2
import numpy as np
from typing import Optional
import requests

from bot.clogger import log

OLLAMA_URL = "http://localhost:11434/api/chat"
OLLAMA_MODEL = "minicpm-v"
OLLAMA_TIMEOUT = 60


def vlm_ask(img_bgr: np.ndarray, question: str, timeout: int = OLLAMA_TIMEOUT) -> Optional[str]:
    """
    Отправить картинку + вопрос на Ollama.
    Вернуть текст ответа или None.
    """
    try:
        # Кодируем картинку в base64
        ok, buf = cv2.imencode('.png', img_bgr)
        if not ok:
            log("VLM: не удалось закодировать картинку", level="WARNING")
            return None
        img_b64 = base64.b64encode(buf.tobytes()).decode()

        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": question,
                    "images": [img_b64]
                }
            ],
            "stream": False
        }

        resp = requests.post(OLLAMA_URL, json=payload, timeout=timeout)

        if resp.status_code != 200:
            log(f"VLM: HTTP {resp.status_code} — {resp.text[:100]}", level="WARNING")
            return None

        data = resp.json()
        answer = data.get("message", {}).get("content", "")
        if answer:
            log(f"VLM: ответ получен ({len(answer)} символов)", level="DEBUG")
            return answer.strip()
        return None

    except requests.exceptions.ConnectionError:
        log("VLM: Ollama недоступен (ConnectionError). Запущен ли ollama serve?",
            level="WARNING")
        return None
    except Exception as e:
        log(f"VLM: ошибка: {e}", level="WARNING")
        return None


def vlm_find_red_dot(img_bgr: np.ndarray) -> Optional[tuple]:
    """
    Найти красную точку через VLM.
    Возвращает (cx, cy) в координатах картинки, или None.
    Координаты ограничены в пределах картинки.
    """
    h, w = img_bgr.shape[:2]
    answer = vlm_ask(img_bgr,
        f"Есть ли на этом скриншоте красная точка (значок 'новое') "
        f"сверху-справа у какого-либо предмета? "
        f"Размер картинки: {w} пикселей в ширину, {h} пикселей в высоту. "
        f"Если да — назови координаты центра красной точки в пикселях "
        f"в формате X,Y (где X от 0 до {w}, Y от 0 до {h}). "
        f"Если нет — скажи 'нет'."
    )
    if not answer or answer.lower().startswith("нет"):
        return None

    # Парсим координаты
    import re
    numbers = re.findall(r'\d+', answer)
    if len(numbers) >= 2:
        cx, cy = int(numbers[0]), int(numbers[1])
        # Ограничиваем в пределах картинки
        cx = max(0, min(cx, w - 1))
        cy = max(0, min(cy, h - 1))
        log(f"VLM: красная точка найдена ({cx},{cy})", level="DEBUG")
        return (cx, cy)
    return None


def vlm_find_item_by_icon(inventory_img: np.ndarray, sample_img: np.ndarray) -> Optional[bool]:
    """
    Проверить через VLM — есть ли предмет с такой иконкой в инвентаре.
    Возвращает True/False/None(ошибка).
    Не возвращает координаты — VLM не может дать точные пиксели.
    Координаты берём через _find_red_dots (точный фильтр).
    """
    try:
        ok1, buf1 = cv2.imencode('.png', inventory_img)
        ok2, buf2 = cv2.imencode('.png', sample_img)
        if not ok1 or not ok2:
            return None
        inv_b64 = base64.b64encode(buf1.tobytes()).decode()
        sample_b64 = base64.b64encode(buf2.tobytes()).decode()

        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Первое изображение — инвентарь. "
                        "Второе изображение — иконка предмета. "
                        "Есть ли в инвентаре предмет с ТАКОЙ ЖЕ или ПОХОЖЕЙ иконкой? "
                        "Ответь только 'да' или 'нет'."
                    ),
                    "images": [inv_b64, sample_b64]
                }
            ],
            "stream": False
        }

        resp = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        if resp.status_code != 200:
            log(f"VLM: HTTP {resp.status_code}", level="WARNING")
            return None

        data = resp.json()
        answer = data.get("message", {}).get("content", "").strip().lower()
        if "да" in answer:
            log(f"VLM: предмет найден по иконке", level="DEBUG")
            return True
        elif "нет" in answer:
            log(f"VLM: предмет не найден по иконке", level="DEBUG")
            return False
        return None

    except Exception as e:
        log(f"VLM: ошибка поиска по иконке: {e}", level="WARNING")
        return None


def vlm_read_price(img_bgr: np.ndarray) -> Optional[int]:
    """
    Прочитать цену через VLM.
    """
    answer = vlm_ask(img_bgr,
        "Прочитай число 'Текущая минимальная цена' на этом скриншоте. "
        "Назови ТОЛЬКО число без пробелов и запятых. "
        "Если числа нет — скажи 'нет'."
    )
    if not answer or answer.lower().startswith("нет"):
        return None

    import re
    numbers = re.findall(r'\d+', answer.replace(',', '').replace(' ', ''))
    if numbers:
        price = int(numbers[0])
        log(f"VLM: цена = {price}", level="DEBUG")
        return price
    return None


def vlm_check_dungeon(img_bgr: np.ndarray) -> Optional[str]:
    """
    Проверить название данжа через VLM.
    """
    answer = vlm_ask(img_bgr,
        "Какой данж сейчас выбран? Прочитай название. "
        "Назови ТОЛЬКО название, без описания."
    )
    if answer:
        log(f"VLM: данж = {answer}", level="DEBUG")
        return answer
    return None
