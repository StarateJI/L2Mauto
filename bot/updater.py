import requests
import os
import zipfile
import io
import shutil
import configparser
import sys
import subprocess
import time
from bot.clogger import log

VERSION_FILE = os.path.join(os.path.dirname(__file__), "version.txt")

# Список URL для проверки версии:
# 1. raw.githubusercontent.com — оригинал, свежая версия
# 2. cdn.jsdelivr.net — CDN (не лимитируется)
# api.github.com УБРАН — давал 403 rate limit
REPO_VERSION_URLS = [
    "https://raw.githubusercontent.com/StarateJI/L2Mauto/main/bot/version.txt",
]
REPO_ZIP = "https://github.com/StarateJI/L2Mauto/archive/refs/heads/main.zip"

# Зеркала ZIP — если github.com не отвечает, пробуем другие.
REPO_ZIP_MIRRORS = [
    "https://github.com/StarateJI/L2Mauto/archive/refs/heads/main.zip",
    "https://codeload.github.com/StarateJI/L2Mauto/zip/refs/heads/main",
    "https://cdn.jsdelivr.net/gh/StarateJI/L2Mauto@main",
]

def get_my_version():
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "0.0.0"

def parse_version(v: str):
    return tuple(map(int, v.split(".")))

def _load_github_token() -> str | None:
    """Прочитать GitHub-токен. Приоритет:
    1. tg.ini [github] token
    2. Встроенный XOR-токен из log_uploader.py (тот же что для загрузки логов)
    """
    # 1. tg.ini
    try:
        ini_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tg.ini")
        cp = configparser.ConfigParser()
        cp.read(ini_path, encoding="utf-8")
        if cp.has_section("github") and cp.has_option("github", "token"):
            tok = cp.get("github", "token").strip()
            if tok and len(tok) > 10:
                return tok
    except Exception:
        pass

    # 2. Встроенный XOR-токен (как в log_uploader.py)
    try:
        from bot.log_uploader import _decode_xor
        tok = _decode_xor()
        if tok and len(tok) > 10:
            return tok
    except Exception:
        pass

    return None

def _fetch_remote_version() -> str | None:
    """
    Попробовать получить remote версию из нескольких источников.
    Возвращает строку с версией или None если все источники упали.

    Сравнивает версии из всех источников и берёт МАКСИМАЛЬНУЮ —
    так мы не зависим от того что jsdelivr закешировал старую версию.
    """
    headers = {
        "Cache-Control": "no-cache, no-store, max-age=0",
        "Pragma": "no-cache",
    }
    tok = _load_github_token()
    if tok:
        headers["Authorization"] = f"token {tok}"

    # Cache-buster — уникальный URL для каждого запроса
    cache_buster = f"?ts={int(time.time())}"

    versions_found: list[tuple[int, str, str]] = []  # (порядок, источник, версия)

    for url in REPO_VERSION_URLS:
        try:
            # raw / jsdelivr — простой текст (api.github.com убран)
            full_url = url + cache_buster
            r = requests.get(full_url, timeout=5, headers=headers)
            r.raise_for_status()
            content = r.text.strip()
            if content and content[0].isdigit():
                src = "jsdelivr" if "jsdelivr" in url else "raw"
                versions_found.append((len(versions_found), src, content))
                log(f"needs_update: {src} → {content}", level="DEBUG")
        except Exception as e:
            src = "jsdelivr" if "jsdelivr" in url else "raw"
            log(f"needs_update: {src} failed: {type(e).__name__}: {e}",
                level="DEBUG")
            continue

    if not versions_found:
        return None

    # Взять МАКСИМАЛЬНУЮ версию из всех полученных — чтобы закешированный
    # jsdelivr не блокировал обновление если raw уже отдаёт новую.
    def _vk(v: str):
        try:
            return tuple(int(x) for x in v.split("."))
        except Exception:
            return (0, 0, 0)

    best = max(versions_found, key=lambda x: _vk(x[2]))
    log(f"needs_update: лучший источник {best[1]} → {best[2]} "
        f"(из {len(versions_found)})", level="DEBUG")
    return best[2]


def needs_update() -> bool:
    """
    Сравнить локальную версию с remote. Возвращает True если есть обнова.
    Пробует 3 источника: jsdelivr CDN → raw.githubusercontent → GitHub API.
    Если все упали — возвращает False (не блокируем бота).
    """
    try:
        local = parse_version(get_my_version())
        remote_text = _fetch_remote_version()
        if not remote_text:
            log("needs_update: все источники версии упали — пропускаю проверку",
                level="WARNING")
            return False
        remote = parse_version(remote_text)
        has_update = remote > local
        log(f"needs_update: local={local} remote={remote} -> has_update={has_update}")
        return has_update
    except Exception as e:
        log(f"needs_update: ошибка проверки обновы: {type(e).__name__}: {e}",
            level="WARNING")
        return False

def backup():
    version = get_my_version()
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    backups_dir = os.path.join(root_dir, "backups")
    os.makedirs(backups_dir, exist_ok=True)
    archive_path = os.path.join(backups_dir, f"update_backup_{version}.zip")

    # ЛЁГКИЙ backup — только .py файлы (без скринов, temp_update, .git, debug)
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in
                       ("backups", "logs", "temp_update", ".git",
                        "debug", "__pycache__", "screenshots")]
            for file in files:
                if not file.endswith((".py", ".txt", ".ini", ".bat",
                                       ".json", ".toml", ".md")):
                    continue
                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, root_dir)
                try:
                    zipf.write(path, rel_path)
                except Exception:
                    pass

    log(f"Сделан лёгкий бэкап .py в {archive_path}")
    return archive_path

def _cleanup(root_dir: str) -> None:
    for root, dirs, files in os.walk(root_dir):
        if any(skip in root for skip in ("backups", "logs", "temp_update", ".git")):
            continue
        for file in files:
            if file.endswith(".pyd.old") or file.endswith(".dll.old"):
                try:
                    os.remove(os.path.join(root, file))
                except Exception:
                    pass


def install_req(req_path):
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_path])
        log(f"Установил зависимости: {req_path}")
    except Exception as e:
        log(f"Ошибка при установке зависимостей: {e}")

def ini(local_path, new_path):
    config_local = configparser.ConfigParser()
    config_new = configparser.ConfigParser()
    config_local.read(local_path, encoding="utf-8")
    config_new.read(new_path, encoding="utf-8")

    for section in config_new.sections():
        if not config_local.has_section(section):
            config_local.add_section(section)
        for key, val in config_new.items(section):
            if not config_local.has_option(section, key):
                config_local.set(section, key, val)

    with open(local_path, "w", encoding="utf-8") as f:
        config_local.write(f)

def _write_apply_bat(root_dir: str, temp_dir: str) -> str:
    """
    Создаёт apply_update.bat — он копирует файлы ПОСЛЕ закрытия текущего
    процесса Python. Решает 'Permission denied' на залоченных .pyd файлах.

    Возвращает путь к созданному bat-файлу.
    """
    python_exe = sys.executable
    if not os.path.exists(python_exe):
        python_exe = shutil.which("python") or shutil.which("python3") or "python"

    main_py = os.path.join(root_dir, "main.py")

    bat_path = os.path.join(root_dir, "apply_update.bat")

    # ── Шаг 1: Собираем список .pyd/.dll (нужны special handling) ────────
    pyd_lines = []
    for root, dirs, files in os.walk(temp_dir):
        for f in files:
            if f.endswith(".pyd") or f.endswith(".dll"):
                src = os.path.join(root, f).replace("/", "\\")
                rel = os.path.relpath(os.path.join(root, f), temp_dir).replace("/", "\\")
                dst = os.path.join(root_dir, rel).replace("/", "\\")
                old = (dst + ".old").replace("/", "\\")
                pyd_lines.append(f"""
REM Handle {rel}
if exist "{old}" del /f /q "{old}"
if exist "{dst}" rename "{dst}" "{os.path.basename(dst)}.old"
if not exist "{os.path.dirname(dst)}" mkdir "{os.path.dirname(dst)}"
copy /y "{src}" "{dst}" >nul
""")

    # ── Шаг 2: Обрабатываем settings/ (НЕ перезаписываем существующие) ───
    settings_lines = []
    for root, dirs, files in os.walk(temp_dir):
        parts = os.path.relpath(root, temp_dir).split(os.sep)
        if "settings" not in parts:
            continue
        for f in files:
            src = os.path.join(root, f).replace("/", "\\")
            rel = os.path.relpath(os.path.join(root, f), temp_dir).replace("/", "\\")
            dst = os.path.join(root_dir, rel).replace("/", "\\")
            settings_lines.append(f"""
REM settings: copy only if missing
if not exist "{dst}" (
    if not exist "{os.path.dirname(dst)}" mkdir "{os.path.dirname(dst)}"
    copy /y "{src}" "{dst}" >nul
)
""")

    # ── Шаг 3: Обрабатываем .ini (merge) ────────────────────────────────
    # .ini merge делаем заранее в Python, а в bat просто копируем результат
    for root, dirs, files in os.walk(temp_dir):
        for f in files:
            if f.endswith(".ini"):
                src = os.path.join(root, f)
                rel = os.path.relpath(src, temp_dir)
                dst = os.path.join(root_dir, rel)
                if os.path.exists(dst):
                    # merge — добавляем недостающие секции/ключи
                    try:
                        ini(dst, src)
                        # После merge в dst — не нужно копировать из temp
                        # Удаляем из temp чтобы xcopy не перезаписал
                        os.remove(src)
                    except Exception as e:
                        log(f"ini merge failed for {rel}: {e}")

    # ── Шаг 4: Собираем bat ──────────────────────────────────────────────
    pyd_block = "".join(pyd_lines)
    settings_block = "".join(settings_lines)

    bat_content = f"""@echo off
chcp 65001 >nul
title Applying L2Mauto update...

REM ============================================================
REM L2Mauto updater — apply_update.bat
REM Копирует файлы ПОСЛЕ закрытия Python (чтобы .pyd разлочился)
REM ============================================================

REM Логируем всё в apply_update.log для диагностики
echo === apply_update.bat started at %DATE% %TIME% === > "{root_dir}\\apply_update.log"
echo Working dir: {root_dir} >> "{root_dir}\\apply_update.log"
echo Python: {python_exe} >> "{root_dir}\\apply_update.log"

REM Ждём пока старый Python полностью закроется (отпустит .pyd и .py)
echo Waiting 5 sec for Python to exit... >> "{root_dir}\\apply_update.log"
timeout /t 5 /nobreak >nul
REM Принудительно убиваем ВСЕ python.exe процессы
taskkill /f /im python.exe 2>nul
taskkill /f /im pythonw.exe 2>nul
timeout /t 2 /nobreak >nul
REM Проверяем что python точно мёртв
tasklist /fi "imagename eq python.exe" 2>nul | find /i "python.exe" >nul
if not errorlevel 1 (
    echo WARNING: python.exe still running! Force kill again... >> "{root_dir}\\apply_update.log"
    taskkill /f /im python.exe 2>nul
    timeout /t 3 /nobreak >nul
)

REM ---- Шаг 1: .pyd/.dll (rename old -> copy new) ----
echo Step 1: copy .pyd/.dll files... >> "{root_dir}\\apply_update.log"
{pyd_block}

REM ---- Шаг 2: settings/ (copy only if missing) ----
echo Step 2: copy settings (if missing)... >> "{root_dir}\\apply_update.log"
{settings_block}

REM ---- Шаг 3: остальные файлы (overwrite) ----
echo Step 3: xcopy other files... >> "{root_dir}\\apply_update.log"
xcopy "{temp_dir}\\*" "{root_dir}\\" /e /y /i /f >> "{root_dir}\\apply_update.log" 2>&1
echo Step 3 done. >> "{root_dir}\\apply_update.log"

REM ---- Шаг 3b: удаляем __pycache__ чтобы Python не использовал старый .pyc ----
echo Step 3b: cleanup __pycache__... >> "{root_dir}\\apply_update.log"
attrib -r -s -h "{root_dir}\\__pycache__" 2>nul
rd /s /q "{root_dir}\\__pycache__" 2>nul
for /d %%D in ("{root_dir}\\*") do (
    if exist "%%D\\__pycache__" rd /s /q "%%D\\__pycache__" 2>nul
    for /d %%E in ("%%D\\*") do (
        if exist "%%E\\__pycache__" rd /s /q "%%E\\__pycache__" 2>nul
        for /d %%F in ("%%E\\*") do (
            if exist "%%F\\__pycache__" rd /s /q "%%F\\__pycache__" 2>nul
        )
    )
)
echo Step 3b done. >> "{root_dir}\\apply_update.log"

REM ---- Шаг 3c: Проверяем что YOLOv8 модель на месте ----
echo Step 3c: check YOLOv8 model... >> "{root_dir}\\apply_update.log"
if not exist "{root_dir}\\bot\\models\\item_detector.pt" (
    echo WARNING: item_detector.pt not found! >> "{root_dir}\\apply_update.log"
    if not exist "{root_dir}\\bot\\models" mkdir "{root_dir}\\bot\\models"
    REM Пробуем скачать с GitHub
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/StarateJI/L2Mauto/raw/main/bot/models/item_detector.pt' -OutFile '{root_dir}\\bot\\models\\item_detector.pt'" >> "{root_dir}\\apply_update.log" 2>&1
    if exist "{root_dir}\\bot\\models\\item_detector.pt" (
        echo item_detector.pt downloaded successfully. >> "{root_dir}\\apply_update.log"
    ) else (
        echo ERROR: Failed to download item_detector.pt! >> "{root_dir}\\apply_update.log"
    )
) else (
    echo item_detector.pt OK. >> "{root_dir}\\apply_update.log"
)

REM ---- Шаг 4: cleanup ----
echo Step 4: cleanup temp_dir... >> "{root_dir}\\apply_update.log"
rd /s /q "{temp_dir}" 2>nul

REM ---- Шаг 5: запускаем бота СРАЗУ (не ждём pip install) ----
echo Step 5: starting bot... >> "{root_dir}\\apply_update.log"
cd /d "{root_dir}"
start "" "{python_exe}" "{main_py}"
echo Bot started at %DATE% %TIME% >> "{root_dir}\\apply_update.log"

REM ---- Шаг 6: pip install в фоне (НЕ блокирует запуск бота) ----
echo Step 6: pip install (background)... >> "{root_dir}\\apply_update.log"
if exist "{root_dir}\\requirements.txt" (
    start "" /b "{python_exe}" -m pip install -r "{root_dir}\\requirements.txt"
)

REM Удаляем себя (apply_update.bat)
del "%~f0" 2>nul
exit
"""
    with open(bat_path, "w", encoding="cp1251", errors="replace") as f:
        f.write(bat_content)
    log(f"Создан apply_update.bat: {bat_path}")
    return bat_path


def update():
    try:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        backup()
        log("Обнова: бэкап сделан, качаю файлы по отдельности...", level="INFO")

        # GitHub кеширует ZIP (194MB из-за старой истории).
        # Вместо ZIP — скачиваем только изменённые файлы через raw URLs.
        import time as _time
        
        # Список файлов для скачивания (относительно корня репо)
        FILES_TO_DOWNLOAD = [
            "bot/version.txt",
            "bot/updater.py",
            "bot/clogger.py",
            "bot/constans.py",
            "bot/controller.py",
            "bot/delays.py",
            "bot/limits.py",
            "bot/log_uploader.py",
            "bot/manager.py",
            "bot/misc.py",
            "bot/utils.py",
            "bot/windows_memory.py",
            "bot/yolo_detector.py",
            "bot/ocr.py",
            "bot/vlm.py",
            "bot/methods/game/__init__.py",
            "bot/methods/game/_base.py",
            "bot/methods/game/auction.py",
            "bot/methods/game/claims.py",
            "bot/methods/game/combat.py",
            "bot/methods/game/energo.py",
            "bot/methods/game/errors.py",
            "bot/methods/game/party_dungeon.py",
            "bot/methods/game/scheduler.py",
            "bot/methods/game/teleport.py",
            "bot/methods/game/town.py",
            "bot/methods/base.py",
            "bot/methods/other.py",
            "bot/cbt/cbt.py",
            "bot/events/checker.py",
            "bot/events/enums.py",
            "bot/events/events.py",
            "bot/capture/__init__.py",
            "bot/capture/backend.py",
            "bot/capture/hwnd.py",
            "bot/capture/mss_backend.py",
            "bot/capture/rust_backend.py",
            "bot/alchemy/alch_cons.py",
            "bot/alchemy/alch_utils.py",
            "bot/alchemy/main_alch.py",
            "bot/alchemy/mini_alch.py",
            "profiles/base.py",
            "profiles/event_driven.py",
            "profiles/Auction/auction.py",
            "profiles/Dungeon/dungeon.py",
            "profiles/PvPDodge/pvp.py",
            "profiles/Rewards/rewards.py",
            "profiles/Scheduler/scheduler.py",
            "profiles/Buyer/buyer.py",
            "profiles/MainAlchemy/main_alch.py",
            "gui/maingui.py",
            "gui/single.py",
            "gui/cache.py",
            "main.py",
            "requirements.txt",
        ]

        temp_dir = os.path.join(root_dir, "temp_update")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)

        raw_base = "https://raw.githubusercontent.com/StarateJI/L2Mauto/main/"
        downloaded = 0
        failed = []

        for filepath in FILES_TO_DOWNLOAD:
            url = raw_base + filepath
            local_path = os.path.join(temp_dir, filepath.replace("/", os.sep))
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            try:
                r = requests.get(url, timeout=(8, 30))
                if r.status_code == 200:
                    with open(local_path, "wb") as f:
                        f.write(r.content)
                    downloaded += 1
                    if downloaded % 10 == 0:
                        log(f"Обнова: скачано {downloaded}/{len(FILES_TO_DOWNLOAD)} файлов", level="DEBUG")
                else:
                    failed.append(filepath)
            except Exception as e:
                failed.append(filepath)
                log(f"Обнова: не скачал {filepath}: {e}", level="WARNING")
            _time.sleep(0.1)  # не забиваем канал

        log(f"Обнова: скачано {downloaded}/{len(FILES_TO_DOWNLOAD)} файлов, "
            f"ошибок: {len(failed)}", level="INFO")
        if failed:
            log(f"Обнова: НЕ скачаны: {failed}", level="WARNING")

        # _write_apply_bat + запуск

        # Очистка старых .pyd.old / .dll.old
        _cleanup(root_dir)

        # ── НОВЫЙ ПОДХОД: apply_update.bat ──────────────────────────────
        # Старый подход падал с 'Permission denied' — Windows блокирует
        # залоченный .pyd (его использует текущий процесс Python).
        # Теперь: создаём bat, который:
        #   1. ждёт 3 сек (пока текущий Python закроется)
        #   2. копирует .pyd (уже разлочен)
        #   3. копирует остальные файлы (с учётом settings/, .ini merge)
        #   4. перезапускает main.py
        # А текущий процесс сразу делает sys.exit(0) после запуска bat.
        bat_path = _write_apply_bat(root_dir, temp_dir)

        log("Накатил обнпату через apply_update.bat, закрываюсь для рестарта...")

        clean = os.environ.copy()
        for bad in ("PYTHONHOME", "PYTHONEXECUTABLE", "PYTHONPATH"):
            clean.pop(bad, None)

        # detached process — bat живёт независимо от Python
        subprocess.Popen(
            ["cmd.exe", "/c", bat_path],
            cwd=root_dir,
            env=clean,
            creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
        )

        print("NE TROGAI NI4EGO - APPLYING UPDATE")
        # os._exit а не sys.exit — потому что update() вызывается из QThread
        # и sys.exit(0) в QThread не завершает процесс, а зависает.
        import os as _os
        _os._exit(0)

    except Exception as e:
        log(f"Обнова бахнула: {e}")
        import traceback
        log(traceback.format_exc(), level="ERROR")
        import os as _os
        _os._exit(1)