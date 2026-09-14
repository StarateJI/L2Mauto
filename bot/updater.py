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

def update():
    try:
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        backup()

        r = requests.get(REPO_ZIP, timeout=10)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))

        temp_dir = os.path.join(root_dir, "temp_update")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        os.makedirs(temp_dir, exist_ok=True)

        z.extractall(temp_dir)
        main_repo = os.path.join(temp_dir, "L2Mauto-main")  # MY REPO: имя папки из zip

        _cleanup(root_dir)

        for root, dirs, files in os.walk(main_repo):
            for file in files:
                rel_path = os.path.relpath(os.path.join(root, file), main_repo)
                dst_path = os.path.join(root_dir, rel_path)

                if file.endswith(".pyd") or file.endswith(".dll"):
                    if os.path.exists(dst_path):
                        old_path = dst_path + ".old"
                        try:
                            if os.path.exists(old_path):
                                os.remove(old_path)
                        except Exception:
                            pass
                        try:
                            os.rename(dst_path, old_path)
                        except Exception as e:
                            log(f"pyd rename failed for {rel_path}: {e}")
                            continue
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    try:
                        shutil.copy2(os.path.join(root, file), dst_path)
                    except Exception as e:
                        log(f"pyd copy failed for {rel_path}: {e}")
                    continue

                if "settings" in rel_path.split(os.sep):
                    if not os.path.exists(dst_path):
                        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                        shutil.copy2(os.path.join(root, file), dst_path)
                    continue

                if dst_path.endswith(".ini") and os.path.exists(dst_path):
                    ini(dst_path, os.path.join(root, file))
                    continue

                # MY RULE: delays.py и misc.py НЕ мержим — ставим из обновы как есть.
                # Наши тайминги = часть бота, одинаковые на всех ПК. (merge-ветки удалены)

                os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                shutil.copy2(os.path.join(root, file), dst_path)

        shutil.rmtree(temp_dir)

        req_path = os.path.join(root_dir, "requirements.txt")
        if os.path.exists(req_path):
            install_req(req_path)

        log("Накатил обнову, рестарчусь")

        try:
            ppath = sys.executable

            if not os.path.exists(ppath):
                ppath = shutil.which("python") or shutil.which(
                    "python3") or ppath

            log(f"Рестарт через: {ppath}")
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            bot = os.path.join(root, "main.py")

            clean = os.environ.copy()
            # ebat costyl
            for bad in ("PYTHONHOME", "PYTHONEXECUTABLE", "PYTHONPATH"):
                clean.pop(bad, None)

            subprocess.Popen([ppath, bot] + sys.argv[1:], env=clean)
            print("NE TROGAI NI4EGO")
            sys.exit(0)

        except Exception as e:
            log(f"Не смог рестартануть: {e}")
            sys.exit(1)

    except Exception as e:
        log(f"Обнова бахнула: {e}")
        sys.exit(1)