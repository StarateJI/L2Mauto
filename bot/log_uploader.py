"""
bot/log_uploader.py — авто-загрузка логов и debug PNG в GitHub.

После каждого прогона аукциона бот вызывает upload_run_logs(window_id).
Этот модуль:
  1. Берёт последние N строк из logs/{window_id}.log
  2. Берёт все au_*.png файлы из bot/methods/game/
  3. Коммитит их в ветку `bot-logs` репозитория через GitHub Contents API
  4. Я (ИИ) могу фетчить эту ветку и читать логи + смотреть PNG через VLM

Токен читается из tg.ini (секция [github], ключ token).
Это безопасно: tg.ini уже в .gitignore.

Если токена нет или запрос упал — бот молча работает дальше (это диагностика,
она не должна ломать основной поток).
"""
from __future__ import annotations

import base64
import configparser
import os
import time
from datetime import datetime
from typing import Optional

import requests

from bot.clogger import log

# ── Настройки ──────────────────────────────────────────────────────────────
REPO_OWNER = "StarateJI"
REPO_NAME = "L2Mauto"
BRANCH = "bot-logs"

# Файлы с логами (RotatingFileHandler делает .1, .2 — берём только активный)
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "logs")

# Папка с debug PNG (там же, где auction.py)
DEBUG_DIR = os.path.dirname(os.path.abspath(__file__)) \
    if os.path.basename(os.path.dirname(os.path.abspath(__file__))) == "methods" \
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), "methods", "game")
DEBUG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "methods", "game")
DEBUG_DIR = os.path.abspath(DEBUG_DIR)

# Префиксы файлов, которые считаем debug'ом аукциона
DEBUG_PREFIXES = ("au_", "cmp_")

# Сколько строк лога тащить (последние — самые важные)
LOG_TAIL_LINES = 500

# ──────────────────────────────────────────────────────────────────────────
_token_cache: Optional[str] = None


def _load_token() -> Optional[str]:
    """Прочитать GitHub-токен из tg.ini -> [github] -> token."""
    global _token_cache
    if _token_cache is not None:
        return _token_cache

    ini_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "tg.ini"
    )
    if not os.path.exists(ini_path):
        return None

    try:
        cp = configparser.ConfigParser()
        cp.read(ini_path, encoding="utf-8")
        if cp.has_section("github") and cp.has_option("github", "token"):
            tok = cp.get("github", "token").strip()
            if tok:
                _token_cache = tok
                return tok
    except Exception as e:
        log(f"log_uploader: не смог прочитать tg.ini: {e}", level="WARNING")
    return None


def _api_put(path_in_repo: str, content_bytes: bytes, token: str,
             commit_msg: str) -> Optional[str]:
    """
    Закоммитить файл в ветку bot-logs через GitHub Contents API.
    Если файл уже существует — обновит (используя SHA старой версии).
    Возвращает URL файла на GitHub или None при ошибке.
    """
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/{path_in_repo}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    content_b64 = base64.b64encode(content_bytes).decode("ascii")

    # Получить SHA существующего файла (если есть) — для обновления
    sha: Optional[str] = None
    try:
        r = requests.get(url, headers=headers, params={"ref": BRANCH}, timeout=10)
        if r.status_code == 200:
            sha = r.json().get("sha")
    except Exception:
        pass

    payload = {
        "message": commit_msg,
        "content": content_b64,
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha

    try:
        r = requests.put(url, headers=headers, json=payload, timeout=20)
        if r.status_code in (200, 201):
            data = r.json()
            return data.get("content", {}).get("html_url")
        log(f"log_uploader: PUT {path_in_repo} -> {r.status_code}: "
            f"{r.text[:200]}", level="WARNING")
    except Exception as e:
        log(f"log_uploader: PUT {path_in_repo} exception: {e}", level="WARNING")
    return None


def _tail_file(path: str, n_lines: int) -> bytes:
    """Прочитать последние n_lines строк файла как bytes."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        tail = "".join(lines[-n_lines:])
        # Добавим шапку с временем запуска
        header = f"=== Log tail {datetime.now().isoformat()} | last {n_lines} lines ===\n"
        return (header + tail).encode("utf-8")
    except Exception as e:
        return f"=== Не удалось прочитать {path}: {e} ===\n".encode("utf-8")


def _list_debug_pngs() -> list:
    """Список debug PNG-файлов в DEBUG_DIR с префиксом au_ или cmp_."""
    out = []
    try:
        if not os.path.isdir(DEBUG_DIR):
            return out
        for name in sorted(os.listdir(DEBUG_DIR)):
            if not name.lower().endswith(".png"):
                continue
            if not name.startswith(DEBUG_PREFIXES):
                continue
            full = os.path.join(DEBUG_DIR, name)
            try:
                size = os.path.getsize(full)
            except Exception:
                continue
            # GitHub Contents API лимит 100 МБ, но мы не хотим гигантов
            if size > 5_000_000:  # 5 МБ
                continue
            out.append((name, full, size))
    except Exception as e:
        log(f"log_uploader: list PNGs exception: {e}", level="WARNING")
    return out


def upload_run_logs(window_id: str, made: int = 0, error: Optional[str] = None) -> None:
    """
    Главная точка входа. Вызывается из auction.reregister() в finally блоке
    (всегда — даже если бот упал).

    Загружает:
      - logs/{window_id}.log (последние 500 строк) -> bot-logs/runs/{ts}_{ok|fail|crash}_{win}.log
      - bot/methods/game/au_*.png + cmp_*.png -> bot-logs/debug/{win}/{name}

    Каждый прогон создаёт новый файл с timestamp в имени — старые остаются
    для истории (можно сравнивать «было/стало»).

    Параметры:
      window_id: ник окна (например 'Zakamsk')
      made: сколько лотов переставлено (0 = провал)
      error: строка с описанием ошибки если бот упал (None если штатно)
    """
    token = _load_token()
    if not token:
        log("log_uploader: нет GitHub-токена в tg.ini [github] token — пропускаю",
            window_id, level="DEBUG")
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    if error:
        summary_tag = "crash"
    elif made > 0:
        summary_tag = "ok"
    else:
        summary_tag = "fail"

    # ── 1. Лог ─────────────────────────────────────────────────────────────
    log_path = os.path.join(LOG_DIR, f"{window_id}.log")
    if os.path.exists(log_path):
        content = _tail_file(log_path, LOG_TAIL_LINES)
        # Добавим шапку с ошибкой если бот упал
        if error:
            header = (f"=== CRASH REPORT {datetime.now().isoformat()} ===\n"
                      f"=== Window: {window_id} ===\n"
                      f"=== Error: {error} ===\n"
                      f"=== Made: {made} ===\n\n"
                      f"=== Log tail {LOG_TAIL_LINES} lines ===\n")
            content = header.encode("utf-8") + content
        repo_path = f"runs/{ts}_{summary_tag}_{window_id}.log"
        commit_msg = f"log: {window_id} {summary_tag} made={made}" + \
                    (f" error={error[:80]}" if error else "") + f" @ {ts}"
        url = _api_put(repo_path, content, token, commit_msg)
        if url:
            log(f"log_uploader: лог загружен: {url}", window_id, level="DEBUG")
        else:
            log(f"log_uploader: лог НЕ загружен (см. ошибки выше)",
                window_id, level="WARNING")
    else:
        log(f"log_uploader: файл лога не найден: {log_path}",
            window_id, level="WARNING")

    # ── 2. Debug PNG ───────────────────────────────────────────────────────
    pngs = _list_debug_pngs()
    if pngs:
        for name, full, size in pngs:
            try:
                with open(full, "rb") as f:
                    data = f.read()
                repo_path = f"debug/{window_id}/{name}"
                commit_msg = f"debug: {window_id} {name} @ {ts}"
                _api_put(repo_path, data, token, commit_msg)
            except Exception as e:
                log(f"log_uploader: PNG {name} не загружен: {e}",
                    window_id, level="WARNING")
        log(f"log_uploader: загружено PNG: {len(pngs)}", window_id, level="DEBUG")
    else:
        log("log_uploader: debug PNG не найдены", window_id, level="DEBUG")


def list_recent_runs(limit: int = 10) -> list:
    """
    Для диагностических целей: список последних прогонов в ветке bot-logs.
    Возвращает список путей в репо.
    """
    token = _load_token()
    if not token:
        return []
    url = f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}/contents/runs"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    try:
        r = requests.get(url, headers=headers, params={"ref": BRANCH}, timeout=10)
        if r.status_code == 200:
            items = r.json()
            return [it["path"] for it in items[:limit]]
    except Exception:
        pass
    return []


# ── CLI для тестирования без бота ─────────────────────────────────────────
if __name__ == "__main__":
    import sys
    wid = sys.argv[1] if len(sys.argv) > 1 else "test_window"
    print(f"Тестирую upload_run_logs для окна '{wid}'...")
    upload_run_logs(wid, made=0)
    print("Готово. Последние runs в репо:")
    for p in list_recent_runs(5):
        print(f"  - {p}")
