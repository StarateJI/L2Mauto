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
    """
    answer = vlm_ask(img_bgr,
        "Есть ли на этом скриншоте красная точка (значок 'новое') "
        "сверху-справа у какого-либо предмета? "
        "Если да — назови ТОЛЬКО координаты центра красной точки в пикселях "
        "в формате X,Y (где X — горизонталь, Y — вертикаль, от левого верхнего угла). "
        "Если нет — скажи 'нет'."
    )
    if not answer or answer.lower().startswith("нет"):
        return None

    # Парсим координаты
    import re
    numbers = re.findall(r'\d+', answer)
    if len(numbers) >= 2:
        cx, cy = int(numbers[0]), int(numbers[1])
        log(f"VLM: красная точка найдена ({cx},{cy})", level="DEBUG")
        return (cx, cy)
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
