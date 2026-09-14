import requests
import os
import zipfile
import io
import shutil
import configparser
import sys
import subprocess
from bot.clogger import log

VERSION_FILE = os.path.join(os.path.dirname(__file__), "version.txt")
REPO_VERSION = "https://raw.githubusercontent.com/StarateJI/L2Mauto/main/bot/version.txt"  # MY REPO
REPO_ZIP = "https://github.com/StarateJI/L2Mauto/archive/refs/heads/main.zip"  # MY REPO

def get_my_version():
    try:
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return "0.0.0"

def parse_version(v: str):
    return tuple(map(int, v.split(".")))

def _load_github_token() -> str | None:
    """Прочитать GitHub-токен из tg.ini [github] token (для приватных репо/более высокого rate limit)."""
    try:
        ini_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tg.ini")
        cp = configparser.ConfigParser()
        cp.read(ini_path, encoding="utf-8")
        if cp.has_section("github") and cp.has_option("github", "token"):
            tok = cp.get("github", "token").strip()
            return tok or None
    except Exception:
        pass
    return None

def needs_update() -> bool:
    """
    Сравнить локальную версию с remote. Возвращает True если есть обнова.
    Использует токен из tg.ini [github] если есть (приватные репо, rate limit).
    Логирует ошибки — больше не молчит в except.
    """
    try:
        local = parse_version(get_my_version())
        headers = {}
        tok = _load_github_token()
        if tok:
            headers["Authorization"] = f"token {tok}"
        # timeout 10 сек (было 2 — отваливалось на slow DNS)
        r = requests.get(REPO_VERSION, timeout=10, headers=headers)
        r.raise_for_status()
        remote_text = r.text.strip()
        if not remote_text:
            log("needs_update: пустой ответ от GitHub", level="WARNING")
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

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(root_dir):
            if any(skip in root for skip in ("backups", "logs")):
                continue
            for file in files:
                path = os.path.join(root, file)
                rel_path = os.path.relpath(path, root_dir)
                zipf.write(path, rel_path)

    log(f"Сделан бэкап текущей версии в {archive_path}")
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

REM Ждём пока старый Python полностью закроется
timeout /t 3 /nobreak >nul

REM ---- Шаг 1: .pyd/.dll (rename old -> copy new) ----
{pyd_block}

REM ---- Шаг 2: settings/ (copy only if missing) ----
{settings_block}

REM ---- Шаг 3: остальные файлы (overwrite) ----
xcopy "{temp_dir}\\*" "{root_dir}\\" /e /y /i >nul

REM ---- Шаг 4: cleanup ----
rd /s /q "{temp_dir}" 2>nul

REM Установим зависимости если есть requirements.txt
if exist "{root_dir}\\requirements.txt" (
    "{python_exe}" -m pip install -r "{root_dir}\\requirements.txt"
)

REM Удаляем себя
del "%~f0" 2>nul

REM ---- Шаг 5: запускаем бота ----
cd /d "{root_dir}"
start "" "{python_exe}" "{main_py}"
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

        r = requests.get(REPO_ZIP, timeout=30)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))

        temp_dir = os.path.join(root_dir, "temp_update")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)

        z.extractall(temp_dir)
        main_repo = os.path.join(temp_dir, "L2Mauto-main")

        # Раскрываем содержимое L2Mauto-main/ в корень temp_dir
        if os.path.isdir(main_repo):
            for item in os.listdir(main_repo):
                src = os.path.join(main_repo, item)
                dst = os.path.join(temp_dir, item)
                if os.path.exists(dst):
                    if os.path.isdir(dst):
                        shutil.rmtree(dst)
                    else:
                        os.remove(dst)
                shutil.move(src, dst)
            try:
                os.rmdir(main_repo)
            except OSError:
                pass  # папка может быть непустой если были скрытые файлы

        # Очистка старых .pyd.old / .dll.old от прошлых обнов
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
        sys.exit(0)

    except Exception as e:
        log(f"Обнова бахнула: {e}")
        import traceback
        log(traceback.format_exc(), level="ERROR")
        sys.exit(1)