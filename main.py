import warnings
warnings.filterwarnings("ignore", message=".*TypedStorage is deprecated.*")

import sys
import os
import datetime as _dt
import traceback as _tb

# ── ЛОВЕЦ КРАШЕЙ → crash.log ──────────────────────────────────────────────
# СТАВИТСЯ ПЕРВЫМ. Без него любой краш (Python в Qt-слоте или native-сегфолт
# от capture_rs.pyd / torch / ultralytics) уходит в stderr консоли и НЕ
# попадает в логи — именно поэтому "логи не загрузились на GitHub".
# crash.log лежит рядом с main.py. После краша — открой его и пришли.
_CRASH_LOG = os.path.join(os.getcwd(), "crash.log")

def _crash_header():
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as _f:
            _f.write(f"\n{'='*60}\n"
                     f"ЗАПУСК бота: {_dt.datetime.now():%Y-%m-%d %H:%M:%S}\n"
                     f"cwd: {os.getcwd()}\n{'='*60}\n")
    except Exception:
        pass

_crash_header()

# 1) native segfault → дамп Python-стека всех потоков в crash.log
_crash_fh = None
try:
    import faulthandler as _fh
    _crash_fh = open(_CRASH_LOG, "a", encoding="utf-8")
    _fh.enable(file=_crash_fh, all_threads=True)
except Exception:
    pass

# 2) необработанное Python-исключение (в т.ч. в Qt-слоте клика сценария)
def _crash_dump(_et, _ev, _tb_obj):
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as _f:
            _f.write(f"\n### PYTHON CRASH @ {_dt.datetime.now():%Y-%m-%d %H:%M:%S} ###\n")
            _tb.print_exception(_et, _ev, _tb_obj, file=_f)
            _f.write("### END CRASH ###\n")
    except Exception:
        pass
    _tb.print_exception(_et, _ev, _tb_obj)  # дублируем в консоль (cmd окно)

sys.excepthook = _crash_dump
# ── /ЛОВЕЦ КРАШЕЙ ─────────────────────────────────────────────────────────

# ── SELF-REPAIR: проверка критичных файлов при старте ─────────────────────
# Решает chicken-and-egg: если старый updater не скачал файл (забыл добавить
# в список), бот при старте проверит и докачает сам.
# Список синхронизирован с CRITICAL_FILES в bot/updater.py.
_SELF_REPAIR_FILES = [
    "gui/window_selector.py",      # v5.13.10 добавил, но забыл в FILES_TO_DOWNLOAD
    "gui/windows_selector.py",
    "gui/maingui.py",
    "bot/updater.py",
    "bot/controller.py",
    "bot/utils.py",
]

def _self_repair():
    """Докачать критичные файлы если их нет. Тихо, без UI."""
    missing = []
    for fp in _SELF_REPAIR_FILES:
        local = os.path.join(os.getcwd(), fp.replace("/", os.sep))
        if not os.path.exists(local):
            missing.append(fp)
    if not missing:
        return
    print(f"[self-repair] нет файлов: {missing} — докачиваю с GitHub...")
    try:
        import requests as _req
        raw_base = "https://raw.githubusercontent.com/StarateJI/L2Mauto/main/"
        for fp in missing:
            local = os.path.join(os.getcwd(), fp.replace("/", os.sep))
            os.makedirs(os.path.dirname(local), exist_ok=True)
            try:
                r = _req.get(raw_base + fp, timeout=15)
                if r.status_code == 200 and len(r.content) > 10:
                    with open(local, "wb") as f:
                        f.write(r.content)
                    print(f"[self-repair] OK: {fp} ({len(r.content)} bytes)")
                else:
                    print(f"[self-repair] FAIL: {fp} (HTTP {r.status_code})")
            except Exception as e:
                print(f"[self-repair] FAIL: {fp} ({e})")
    except Exception as e:
        print(f"[self-repair] не смог: {e}")

_self_repair()
# ── /SELF-REPAIR ───────────────────────────────────────────────────────────

# ── ФИКС memory allocation of 14745616 bytes failed ──────────────────────
# 14745616 = 2560×1440×4 (один фрейм фуллскрина). Это Rust-захват capture_rs.pyd
# пытается выделить буфер и падает на одном ПК.
# Решение: env var L2M_NO_RUST=1 — RustBackend.__init__ проверяет эту переменную
# и сразу поднимает BackendUnavailable → backend.py возьмёт mss как fallback.
# mss медленнее на ~50ms но не падает. Аукцион и так использует mss напрямую.
# Ставим ДО любого импорта bot.* чтобы RustBackend не инициализировался.
os.environ.setdefault("L2M_NO_RUST", "1")

from pathlib import Path
import asyncio
import PyQt5
from PyQt5.QtWidgets import QApplication
from qasync import QEventLoop

from gui.maingui import NedoGui
from gui.driver_error import show_message
from bot.utils import checkDriver

_refs = {}

async def main():
    gui = NedoGui(kb, m)
    gui.show()
    _refs['gui'] = gui

    loop = asyncio.get_running_loop()

    def _load_tg():
        from tgbot.bot import TgBot
        return TgBot

    TgBotCls = await loop.run_in_executor(None, _load_tg)
    tg = TgBotCls()
    tg.start_polling()
    _refs['tg'] = tg

    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    base = Path(PyQt5.__file__).resolve().parent
    plugs = base / "Qt5" / "plugins" / "platforms"
    
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugs)

    kb, m = checkDriver()
    app = QApplication(sys.argv)

    if m is None:
        show_message(critical=True)
        sys.exit(1)
    elif kb is None:
        show_message(critical=False)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    def _main_done(fut):
        try:
            if fut.cancelled():
                return
            exc = fut.exception()
            if exc:
                import traceback
                print(f"[main] task died: {exc}\n{traceback.format_exception(type(exc), exc, exc.__traceback__)}")
        except Exception:
            pass

    task = loop.create_task(main())
    task.add_done_callback(_main_done)

    def _on_quit():
        if not task.done():
            task.cancel()
    app.aboutToQuit.connect(_on_quit)

    with loop:
        loop.run_forever()
