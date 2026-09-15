import asyncio
import threading
import ctypes
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from bot.clogger import log
from bot.delays import WAIT_BEFORE_START
from bot.manager import BotManager
from bot.utils import findAllWindows, getProfiles
from bot.constans import SUPPORTED_REZ
from bot.windows.settings_loader import load_settings

TARGET_W, TARGET_H = 400, 225  # автоподгон: рабочий размер окна

SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SetWindowPos = ctypes.windll.user32.SetWindowPos

# DPI-aware: чтобы Windows не врала в координатах при масштабе 125/150%
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _pos_is_sane(pos) -> bool:
    """Свёрнутые окна рапортуют позицию около -32000,-32000 — это мусор."""
    try:
        x, y = int(pos[0]), int(pos[1])
    except Exception:
        return False
    return x > -10000 and y > -10000


def _get_window_rect(hwnd):
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    r = RECT()
    ok = ctypes.windll.user32.GetWindowRect(ctypes.c_void_p(int(hwnd)), ctypes.byref(r))
    if not ok:
        return None
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def _try_autofix(window_info) -> bool:
    """
    Автоподгон v2: до 3 попыток вернуть окно к 400x225 на месте.
    True — окно подогнано, False — не вышло (пропускаем).
    Свёрнутые окна не трогаем вовсе.
    """
    pos = window_info.get("Position")
    if not _pos_is_sane(pos):
        log(f"Окно {window_info.get('Nickname')} свёрнуто/не на экране — пропускаю", level="WARNING")
        return False

    # FIX: window_info.get("ID") may return None if the window dict was
    # built without an HWND (e.g. findAllWindows returned a stale entry,
    # or the window vanished between enumerate and resize). int(None)
    # raises TypeError which kills start_seq mid-flight. Bail out cleanly.
    hwnd_raw = window_info.get("ID")
    if hwnd_raw is None:
        log(f"Окно {window_info.get('Nickname')}: нет HWND (ID is None) — пропускаю автоподгон",
            level="WARNING")
        return False
    try:
        hwnd = int(hwnd_raw)
    except (TypeError, ValueError):
        log(f"Окно {window_info.get('Nickname')}: HWND не парсится ({hwnd_raw!r}) — пропускаю автоподгон",
            level="WARNING")
        return False

    for attempt in range(1, 4):
        try:
            rect = _get_window_rect(hwnd)
            if rect is None:
                return False
            left, top, w, h = rect
            if w == TARGET_W and h == TARGET_H:
                return True  # уже в порядке (например, починилось ранее)

            SetWindowPos(
                ctypes.c_void_p(hwnd), None,
                left, top, TARGET_W, TARGET_H,
                SWP_NOZORDER | SWP_NOACTIVATE,
            )
        except Exception:
            return False

        time.sleep(0.8)

        rect = _get_window_rect(hwnd)
        if rect and rect[2] == TARGET_W and rect[3] == TARGET_H:
            return True

    return False


class ProfileController:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.bot_manager = BotManager()
            cls._instance.loop = asyncio.new_event_loop()
            cls._instance._capture_pool = ThreadPoolExecutor(max_workers=256, thread_name_prefix="cap")
            cls._instance.loop.set_default_executor(cls._instance._capture_pool)
            cls._instance.profiles = getProfiles()
            cls._instance._batch_cancel = threading.Event()
            threading.Thread(target=cls._instance.loop.run_forever, daemon=True).start()
        return cls._instance

    def cancel_batch(self):
        self._batch_cancel.set()

    def reset_batch_cancel(self):
        self._batch_cancel.clear()

    @property
    def batch_cancelled(self) -> bool:
        return self._batch_cancel.is_set()

    def _watch_future(self, fut, what: str):
        """Логирует ошибку, если фоновая задача умерла."""
        def _done(f):
            try:
                exc = f.exception()
                if exc:
                    log(f"{what}: {exc}", level="ERROR")
            except Exception:
                pass
        fut.add_done_callback(_done)

    def start_windows(self, profile_class, nicks, **kwargs):
        log(f"Запуск через {WAIT_BEFORE_START} сек. | {nicks}")

        async def start_seq():
            # FIX: batch may have been cancelled while we were waiting
            # WAIT_BEFORE_START seconds in call_later. Honour the cancel
            # instead of spawning bots whose batch was already aborted.
            if self._batch_cancel.is_set():
                log(f"start_seq: batch_cancel уже выставлен — скипаю запуск {nicks}",
                    level="WARNING")
                return
            windows = findAllWindows()
            tasks = []
            started = []
            for nick in nicks:
                if nick not in windows:
                    log(f"Окно {nick} не найдено, пропускаю", level="WARNING")
                    continue

                window_info = windows[nick]
                if window_info["Size"] not in SUPPORTED_REZ:
                    # автоподгон v2: до 3 попыток, честная проверка результата
                    ok = await asyncio.get_running_loop().run_in_executor(
                        None, _try_autofix, window_info
                    )
                    if ok:
                        refreshed = findAllWindows()
                        window_info = refreshed.get(nick, window_info)

                    if window_info["Size"] not in SUPPORTED_REZ:
                        log(
                            f"Окно {nick}: не удалось подогнать {window_info['Size']} -> {TARGET_W}x{TARGET_H} (3 попытки), пропускаю",
                            level="WARNING"
                        )
                        continue
                    log(f"Окно {nick}: подогнал размер до {window_info['Size']}")

                settings = load_settings(nick)

                task = asyncio.create_task(
                    self.bot_manager.start_bot(
                        profile_class, nick, window_info, settings, **kwargs
                    )
                )
                tasks.append(task)
                started.append(nick)

            if not started:
                log("Запуск не состоялся: ни одного подходящего окна", level="WARNING")
                return

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for nick, res in zip(started, results):
                if isinstance(res, Exception):
                    # ЛОВУШКА ДЛЯ СТЕКА: полный адрес падения при запуске
                    tb = "".join(traceback.format_exception(type(res), res, res.__traceback__))
                    log(f"Окно {nick} упало при запуске:\n{tb}", level="ERROR")

        def delayed():
            # FIX: WAIT_BEFORE_START has just elapsed. If the user hit
            # STOP (or another batch was cancelled) during the wait, do not
            # bother scheduling start_seq — it would just no-op via its
            # own check anyway, but skipping here avoids needless log spam
            # and a pointless run_in_executor hop.
            if self._batch_cancel.is_set():
                log(f"delayed: batch_cancel выставлен за время ожидания — скипаю {nicks}",
                    level="WARNING")
                return
            fut = asyncio.run_coroutine_threadsafe(start_seq(), self.loop)
            self._watch_future(fut, "Ошибка запуска окон")

        self.loop.call_soon_threadsafe(
            lambda: self.loop.call_later(WAIT_BEFORE_START, delayed)
        )

    def stop_windows(self, nicks):
        for nick in nicks:
            fut = asyncio.run_coroutine_threadsafe(
                self.bot_manager.stop_bot(nick),
                self.loop
            )
            self._watch_future(fut, f"Ошибка остановки {nick}")

    def get_runtime_info(self, nick):
        bot = self.bot_manager.get_bot(nick)
        if not bot:
            return None
        return getattr(bot, "runtime_data", None)

    def is_running(self, nick):
        return self.bot_manager.is_running(nick)

    def close_window(self, nick: str):
        fut = asyncio.run_coroutine_threadsafe(
            self.bot_manager.stop_bot(nick), self.loop
        )
        try:
            fut.result(timeout=3)
        except Exception as e:
            log(f"Остановка {nick} перед закрытием: {e}", level="WARNING")

        windows = findAllWindows()
        if nick not in windows:
            log(f"Окно для {nick} не найдено")
            return False

        hwnd = windows[nick]["ID"]
        if not ctypes.windll.user32.IsWindow(hwnd):
            log(f"HWND для {nick} недействителен")
            return False

        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        log(f"Окно {nick} закрыто")
        return True

    def stop_and_close(self, nicks):
        for nick in nicks:
            self.close_window(nick)
