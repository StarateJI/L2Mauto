import warnings
warnings.filterwarnings("ignore", message=".*TypedStorage is deprecated.*")

import sys
import os

# ── ФИКС memory allocation of 14745616 bytes failed ──────────────────────
# 14745616 = 2560×1440×4 (один фрейм фуллскрина). Это Rust-захват capture_rs.pyd
# пытается выделить буфер. На одном ПК падает. Отключаем Rust, оставляем mss.
# mss медленнее на ~50ms но не падает. В аукционе уже используется mss напрямую.
# Ставим ДО любого импорта bot.* чтобы RustBackend не инициализировался.
os.environ.setdefault("L2M_CAPTURE_BACKEND", "mss")

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
