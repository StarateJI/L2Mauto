"""
bot/vlm_client.py — HTTP клиент для VLM сервиса.

Бот отправляет картинку (base64) + вопрос на VLM сервис.
Сервис работает на сервере (port 3010), доступ через caddy gateway.

Использование:
    from bot.vlm_client import vlm_ask
    answer = vlm_ask(img_bgr, "Есть красная точка? Координаты?")
    # answer = "Да, (782, 130)" или "нет"
"""
from __future__ import annotations

import base64
import cv2
import numpy as np
from typing import Optional
import requests

from bot.clogger import log


# VLM сервис доступен через caddy gateway с XTransformPort=3010
# Бот делает запрос: POST /ask?XTransformPort=3010
# Caddy перенаправляет на localhost:3010 (VLM сервис)
VLM_URL = "/ask?XTransformPort=3010"
VLM_TIMEOUT = 60  # секунд


def vlm_ask(img_bgr: np.ndarray, question: str, timeout: int = VLM_TIMEOUT) -> Optional[str]:
    """
    Отправить картинку + вопрос на VLM сервис.
    Вернуть текст ответа или None.

    Args:
        img_bgr: изображение в BGR формате (numpy array)
        question: текст вопроса
        timeout: таймаут в секундах

    Returns:
        Текст ответа от VLM, или None если сервис недоступен
    """
    try:
        # Кодируем картинку в base64
        ok, buf = cv2.imencode('.png', img_bgr)
        if not ok:
            log("VLM: не удалось закодировать картинку", level="WARNING")
            return None
        img_b64 = base64.b64encode(buf.tobytes()).decode()

        # Отправляем запрос
        resp = requests.post(
            VLM_URL,
            json={"image": img_b64, "question": question},
            timeout=timeout
        )

        if resp.status_code != 200:
            log(f"VLM: HTTP {resp.status_code}", level="WARNING")
            return None

        data = resp.json()
        answer = data.get("answer")
        if answer:
            log(f"VLM: ответ получен ({len(answer)} символов)", level="DEBUG")
            return answer.strip()
        return None

    except requests.exceptions.ConnectionError:
        log("VLM: сервис недоступен (ConnectionError)", level="DEBUG")
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
        "Если да — назови ТОЛЬКО координаты центра точки в пикселях "
        "в формате X,Y. Если нет — скажи 'нет'."
    )
    if not answer or answer.lower().startswith("нет"):
        return None

    # Парсим координаты из ответа
    import re
    # Ищем числа в ответе
    numbers = re.findall(r'\d+', answer)
    if len(numbers) >= 2:
        cx, cy = int(numbers[0]), int(numbers[1])
        log(f"VLM: красная точка найдена ({cx},{cy})", level="DEBUG")
        return (cx, cy)
    return None


def vlm_read_price(img_bgr: np.ndarray) -> Optional[int]:
    """
    Прочитать цену через VLM.
    Возвращает int (цена) или None.
    """
    answer = vlm_ask(img_bgr,
        "Прочитай число 'Текущая минимальная цена' на этом скриншоте. "
        "Назови ТОЛЬКО число без пробелов и запятых. "
        "Если числа нет — скажи 'нет'."
    )
    if not answer or answer.lower().startswith("нет"):
        return None

    import re
    # Извлекаем число
    numbers = re.findall(r'\d+', answer.replace(',', '').replace(' ', ''))
    if numbers:
        price = int(numbers[0])
        log(f"VLM: цена = {price}", level="DEBUG")
        return price
    return None


def vlm_check_dungeon(img_bgr: np.ndarray) -> Optional[str]:
    """
    Проверить название данжа через VLM.
    Возвращает название данжа или None.
    """
    answer = vlm_ask(img_bgr,
        "Какой данж сейчас выбран? Прочитай название. "
        "Назови ТОЛЬКО название, без описания."
    )
    if answer:
        log(f"VLM: данж = {answer}", level="DEBUG")
        return answer
    return None
