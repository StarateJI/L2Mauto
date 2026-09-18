import json
import os
import time

from bot.clogger import log

_tname = "ПамятьОкон"

MEMORY_DIR = os.path.join("settings", "gui")
MEMORY_PATH = os.path.join(MEMORY_DIR, "windows_memory.json")

# Насколько далеко (в пикселях) окно может стоять от запомненного места,
# чтобы мы поверили, что это оно. Окна лежат сеткой (~440px между соседями),
# так что 60 — безопасный запас: дальше — точно чужое место
MATCH_TOLERANCE = 60

# Первые N секунд без ника считаем «окно просто грузится» и не опознаём,
# чтобы не пугать при обычном запуске новых окон
GRACE_SECONDS = 60

_first_seen = {}   # когда впервые увидели окно без ника
_reported = set()  # о чём уже писали в ТГ (анти-спам)


def _load() -> dict:
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save(data: dict) -> None:
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"Не смог сохранить дневник окон: {e}", _tname, level="WARNING")


def _pos_is_sane(pos) -> bool:
    """Свёрнутые окна рапортуют позицию около -32000,-32000 — это мусор."""
    try:
        x, y = int(pos[0]), int(pos[1])
    except Exception:
        return False
    return x > -10000 and y > -10000


def remember(window_info: dict) -> None:
    """
    Дневник: запоминает, на какой позиции стоит каждое окно с ником.
    Вызывается при каждом сканировании окон — сам себя обновляет.
    """
    data = _load()
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    for nick, info in window_info.items():
        pos = info.get("Position")
        if not _pos_is_sane(pos):
            continue  # свёрнутое окно — позиция мусорная, дневник не портим
        data[nick] = {
            "left": int(pos[0]),
            "top": int(pos[1]),
            "width": info.get("Width"),
            "height": info.get("Height"),
            "seen": now,
        }

    _save(data)


def try_recognize(info: dict):
    """
    Пробует опознать окно БЕЗ ника по позиции.
    Возвращает ник, если уверены, иначе None.
    """
    pos = info.get("Position")
    if not _pos_is_sane(pos):
        return None

    hwnd = info.get("ID")
    now = time.time()

    # окно без ника видимо первый раз — подождём: может, просто грузится
    first = _first_seen.get(hwnd)
    if first is None:
        _first_seen[hwnd] = now
        return None
    if now - first < GRACE_SECONDS:
        return None

    data = _load()
    if not data:
        return None  # дневник пуст — учиться пока не на чем

    best_nick = None
    best_dist = None
    for nick, rec in data.items():
        try:
            dx = abs(int(rec.get("left", -99999)) - int(pos[0]))
            dy = abs(int(rec.get("top", -99999)) - int(pos[1]))
        except (TypeError, ValueError):
            continue
        dist = dx + dy
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_nick = nick

    if best_nick is None or best_dist is None or best_dist > MATCH_TOLERANCE:
        return None

    if hwnd not in _reported:
        _reported.add(hwnd)
        log(f"Окно без ника (#{hwnd}) опознано по памяти как {best_nick}", _tname, level="WARNING")
        try:
            from tgbot.bot import TgBot
            tg = TgBot()
            tg.send_notification(
                level="warning",
                text=f"🖼 Окно без ника опознано по памяти как {best_nick}",
            )
        except Exception:
            pass

    return best_nick