import asyncio
import os
import random

import mss
import cv2
import numpy as np

from bot.clogger import log
from profiles.base import BaseProfile
from bot.windows.runtime import RuntimeData
from bot.events.enums import BotState, NotifyLevel


# ── Координаты (проценты от размера окна) ──────────────────────────────────
# Получены от пользователя (фуллскрин 2560×1440)

# Вкладки категорий (сверху)
TAB_CATEGORIES = [
    ("Класс",       0.724, 0.197),
    ("Агатионы",    0.766, 0.201),
    ("Облик",       0.810, 0.201),
    ("Транспорт",   0.860, 0.198),
    ("Артефакты",   0.905, 0.198),
]

# Вкладка «Синтез» (подвкладка внутри категории)
TAB_SYNTHESIS = (0.423, 0.160)

# Кнопки внизу
BTN_AUTO_SELECT = (0.576, 0.879)
BTN_SYNTHESIZE  = (0.802, 0.886)
BTN_SHOW_ALL    = (0.504, 0.883)
BTN_REPEAT      = (0.602, 0.913)
BTN_EXIT        = (0.503, 0.913)

# Фильтр «Все» (слева вверху)
BTN_ALL_FILTER  = (0.040, 0.256)

# Кнопка закрытия меню (крестик) — правый верхний угол
BTN_CLOSE_MENU  = (0.97, 0.03)


class Synthesis(BaseProfile):
    """Синтез — автоматический синтез предметов по 5 категориям."""

    def __init__(self, window_info, settings=None):
        super().__init__(window_info, settings=settings)
        self.runtime_data = RuntimeData(current_state=BotState.AFK)

    def profile_version(self):
        return "1.0.0"

    def profile_name(self):
        return "Synthesis"

    # ── Утилиты захвата ──────────────────────────────────────────────────
    def _grab_window_rect(self, wx, wy, x_rel, y_rel, w, h):
        monitor = {"left": wx + x_rel, "top": wy + y_rel, "width": w, "height": h}
        try:
            shot = mss.mss().grab(monitor)
            arr = np.array(shot)
            return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
        except Exception:
            try:
                local_sct = mss.mss()
                shot = local_sct.grab(monitor)
                arr = np.array(shot)
                local_sct.close()
                return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
            except Exception:
                return None

    def _save_debug(self, name, img):
        try:
            out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(out_dir, name)
            cv2.imwrite(path, img)
            log(f"Синтез: сохранён {name}", self.window_id)
        except Exception as e:
            log(f"Синтез: не удалось сохранить {name}: {e}", self.window_id, level="WARNING")

    async def _click_pct(self, x_pct, y_pct, label=""):
        """Клик по процентам от размера окна + рандомизация ±3px (анти-бан)."""
        window = self.window_info[self.window_id]
        ww = window["Width"]
        wh = window["Height"]
        rx = random.randint(-3, 3)
        ry = random.randint(-2, 2)
        x = int(ww * x_pct) + rx
        y = int(wh * y_pct) + ry
        await self._activate()
        await asyncio.sleep(0.2 + random.uniform(0, 0.15))
        log(f"Синтез: клик {label} ({x},{y}) offset=({rx},{ry})", self.window_id)
        await self.mouse.click(self.window_info, x, y)
        await asyncio.sleep(0.3 + random.uniform(0.1, 0.3))

    def _check_brightness(self, wx, wy, ww, wh, x_pct, y_pct):
        """Проверить яркость зоны — для определения активности кнопки."""
        x = int(ww * x_pct)
        y = int(wh * y_pct)
        zone = self._grab_window_rect(wx, wy, x - 15, y - 10, 30, 20)
        if zone is None:
            return 0
        gray = cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY)
        return float(gray.mean())

    async def _is_synthesize_active(self, wx, wy, ww, wh):
        """Проверить — активна ли кнопка Синтез (не тусклая)."""
        mean = self._check_brightness(wx, wy, ww, wh, *BTN_SYNTHESIZE)
        is_active = mean > 90
        log(f"Синтез: кнопка 'Синтез' mean={mean:.0f} "
            f"{'АКТИВНА' if is_active else 'тусклая (нет материалов)'}",
            self.window_id)
        return is_active

    async def _spam_repeat(self, wx, wy, ww, wh):
        """
        Спам: Показать все/Перейти к результату → Повтор → ...
        Пока есть Повтор — жмём. Если Повтор исчез — Выход.
        «Показать все» и «Перейти к результату» — одна и та же кнопка (BTN_SHOW_ALL).
        """
        for attempt in range(50):
            # Проверяем — есть ли кнопка «Показать все»/«Перейти к результату»
            show_all_mean = self._check_brightness(wx, wy, ww, wh, *BTN_SHOW_ALL)

            if show_all_mean > 30:
                # Жмём «Показать все» / «Перейти к результату»
                log(f"Синтез: Показать все/Перейти (mean={show_all_mean:.0f})",
                    self.window_id)
                await self._click_pct(*BTN_SHOW_ALL, "Показать все/Перейти")
                await asyncio.sleep(1 + random.uniform(0, 0.3))
                continue

            # Проверяем — есть ли кнопка «Повтор»
            repeat_mean = self._check_brightness(wx, wy, ww, wh, *BTN_REPEAT)

            if repeat_mean > 30:
                # Жмём «Повтор»
                log(f"Синтез: Повтор (mean={repeat_mean:.0f})", self.window_id)
                await self._click_pct(*BTN_REPEAT, "Повтор")
                await asyncio.sleep(2 + random.uniform(0, 0.5))
                continue

            # Нет ни «Показать все», ни «Повтор» — только «Выход»
            log("Синтез: Повтор исчез — нажимаю Выход", self.window_id)
            await self._click_pct(*BTN_EXIT, "Выход")
            await asyncio.sleep(1)
            return True

        log("Синтез: слишком много попыток спама — выхожу",
            self.window_id, level="WARNING")
        await self._click_pct(*BTN_EXIT, "Выход (timeout)")
        return False

    async def _process_category(self, game, category_name, tab_x, tab_y,
                                  wx, wy, ww, wh):
        """
        Обработать одну категорию (Класс, Агатионы, ...).
        1. Клик по вкладке категории
        2. Клик по подвкладке «Синтез»
        3. Цикл: Автовыбор → Синтез → спам Повтор/Показать все → Выход
        4. Клик «Все» (фильтр) → повтор
        5. Пока Синтез активна — повторяем
        """
        log(f"Синтез: === Категория: {category_name} ===", self.window_id)

        # 1. Клик по вкладке категории
        await self._click_pct(tab_x, tab_y, f"Вкладка {category_name}")
        await asyncio.sleep(1)

        # 2. Клик по подвкладке «Синтез»
        await self._click_pct(*TAB_SYNTHESIS, "Вкладка Синтез")
        await asyncio.sleep(1)

        # Скриншот для дебага
        screen = self._grab_window_rect(wx, wy, 0, 0, ww, wh)
        if screen is not None:
            self._save_debug(f"synth_{category_name}_opened.png", screen)

        # 3. Главный цикл синтеза
        synth_round = 0
        while synth_round < 10:  # максимум 10 раундов на категорию
            synth_round += 1
            log(f"Синтез: {category_name} — раунд {synth_round}", self.window_id)

            # Автовыбор
            await self._click_pct(*BTN_AUTO_SELECT, "Автовыбор")
            await asyncio.sleep(0.5 + random.uniform(0, 0.2))

            # Проверить — активна ли кнопка Синтез
            if not await self._is_synthesize_active(wx, wy, ww, wh):
                log(f"Синтез: {category_name} — кнопка Синтез тусклая, "
                    f"нет материалов. Переходим к следующей категории.",
                    self.window_id)
                return

            # Синтез (нажать кнопку)
            await self._click_pct(*BTN_SYNTHESIZE, "Синтез (кнопка)")
            await asyncio.sleep(2 + random.uniform(0, 0.5))

            # Спам «Показать все» → «Повтор» пока есть → Выход
            await self._spam_repeat(wx, wy, ww, wh)

            # Нажать «Все» (фильтр слева вверху) — сбросить выбор
            log(f"Синтез: {category_name} — нажимаю фильтр 'Все'", self.window_id)
            await self._click_pct(*BTN_ALL_FILTER, "Фильтр Все")
            await asyncio.sleep(0.5 + random.uniform(0, 0.2))

        log(f"Синтез: {category_name} — достигнут лимит раундов (10), "
            f"переходим к следующей категории.", self.window_id, level="WARNING")

    async def main_loop(self):
        try:
            window_id = self.window_id
            window = self.window_info[window_id]
            wx, wy = window["Position"]
            ww, wh = window["Width"], window["Height"]

            log(f"Синтез: старт (окно {ww}x{wh})", window_id)

            # Очистка старых debug PNG
            try:
                out_dir = os.path.dirname(os.path.abspath(__file__))
                for fname in os.listdir(out_dir):
                    if fname.startswith("synth_") and fname.endswith(".png"):
                        try:
                            os.remove(os.path.join(out_dir, fname))
                        except Exception:
                            pass
            except Exception:
                pass

            # 1. Выйти из сна
            await self._wake_up(max_attempts=3)

            # 1b. Maximize окно (как аук) — координаты замерялись в фуллскрине
            import ctypes
            import pygetwindow as gw
            u = ctypes.windll.user32
            SW_RESTORE = 9
            MONITOR_DEFAULTTOPRIMARY = 1
            maximize_done = False
            try:
                win = gw.getWindowsWithTitle(self.window_info[window_id]["Title"])[0]
                hwnd = win._hWnd
                log(f"Синтез: окно ДО maximize: {win.width}x{win.height} isMaximized={win.isMaximized}", window_id)
                if win.isMaximized:
                    u.ShowWindow(ctypes.c_void_p(int(hwnd)), SW_RESTORE)
                    await asyncio.sleep(0.4)
                from ctypes import wintypes
                MONITORINFO = type('MONITORINFO', (ctypes.Structure,), {
                    '_fields_': [('cbSize', ctypes.c_uint32),
                                 ('rcMonitor', wintypes.RECT),
                                 ('rcWork', wintypes.RECT),
                                 ('dwFlags', ctypes.c_uint32)],
                })
                hmon = u.MonitorFromWindow(wintypes.HWND(hwnd),
                                           ctypes.c_uint32(MONITOR_DEFAULTTOPRIMARY))
                mi = MONITORINFO()
                mi.cbSize = ctypes.sizeof(MONITORINFO)
                u.GetMonitorInfoW(wintypes.HMONITOR(hmon), ctypes.byref(mi))
                mx, my = mi.rcWork.left, mi.rcWork.top
                mw = mi.rcWork.right - mi.rcWork.left
                mh = mi.rcWork.bottom - mi.rcWork.top
                log(f"Синтез: монитор рабочая область {mw}x{mh} на ({mx},{my})", window_id)
                u.SetWindowPos(wintypes.HWND(hwnd), None, mx, my, mw, mh,
                               0x0004 | 0x0010)
                await asyncio.sleep(1.5)
                # Перечитать размер
                win = gw.getWindowsWithTitle(self.window_info[window_id]["Title"])[0]
                self.window_info[window_id]["Position"] = (win.left, win.top)
                self.window_info[window_id]["Width"] = win.width
                self.window_info[window_id]["Height"] = win.height
                wx, wy = win.left, win.top
                ww, wh = win.width, win.height
                log(f"Синтез: окно ПОСЛЕ maximize: {ww}x{wh} на ({wx},{wy})", window_id)
                maximize_done = True
            except Exception as e:
                log(f"Синтез: maximize не сработал: {e}", window_id, level="WARNING")

            # 2. Открыть главное меню
            from bot.methods.game import PartyDungeon
            game = PartyDungeon(self)

            if not await game.wait_and_click("main_menu_gui", timeout=7):
                log("Синтез: не открыл главное меню", window_id)
                return False
            await asyncio.sleep(1.5)

            # 3. Найти и нажать кнопку «Синтез» в главном меню
            await self._click_pct(0.953, 0.060, "Кнопка Синтез в меню")
            await asyncio.sleep(2)

            screen = self._grab_window_rect(wx, wy, 0, 0, ww, wh)
            if screen is not None:
                self._save_debug("synth_menu_opened.png", screen)

            # 4. Обойти все 5 категорий
            for cat_name, tab_x, tab_y in TAB_CATEGORIES:
                await self._process_category(
                    game, cat_name, tab_x, tab_y, wx, wy, ww, wh
                )

            # 5. Закрыть меню
            await self._click_pct(*BTN_CLOSE_MENU, "Закрыть меню")
            await asyncio.sleep(1)

            # 6. Restore окно
            if maximize_done:
                try:
                    win = gw.getWindowsWithTitle(self.window_info[window_id]["Title"])[0]
                    hwnd = win._hWnd
                    u.ShowWindow(ctypes.c_void_p(int(hwnd)), SW_RESTORE)
                    await asyncio.sleep(0.5)
                    u.SetWindowPos(ctypes.c_void_p(int(hwnd)), None,
                                   0, 40, 400, 225, 0x0004 | 0x0010)
                    await asyncio.sleep(0.5)
                    win = gw.getWindowsWithTitle(self.window_info[window_id]["Title"])[0]
                    self.window_info[window_id]["Position"] = (win.left, win.top)
                    self.window_info[window_id]["Width"] = win.width
                    self.window_info[window_id]["Height"] = win.height
                    log(f"Синтез: окно восстановлено {win.width}x{win.height}", window_id)
                except Exception as e:
                    log(f"Синтез: restore не сработал: {e}", window_id, level="WARNING")

            # 7. Усыпить окно
            if not await self.energo.is_on():
                await self.energo.turn_on()
                await asyncio.sleep(1)

            log("Синтез: завершено, окно в сне", window_id)
            self.notify(NotifyLevel.INFO, "Синтез: все категории обработаны")
            return True

        except asyncio.CancelledError:
            log("Синтез: остановлен вручную", self.window_id)
            raise
        except Exception as e:
            log(f"Синтез: ошибка: {e}", self.window_id, level="ERROR")
            import traceback
            log(traceback.format_exc(), self.window_id, level="ERROR")
            return False
        finally:
            # Залить логи в bot-logs
            try:
                from bot.log_uploader import upload_run_logs
                import asyncio as _aio
                _aio.get_event_loop().run_in_executor(
                    None, upload_run_logs, self.window_id, 0, None
                )
            except Exception:
                pass

    async def on_stop(self):
        self.running = False
        await super().on_stop()
        for task in self._child_tasks:
            task.cancel()
        await asyncio.gather(*self._child_tasks, return_exceptions=True)

    def is_running(self) -> bool:
        return self.running
