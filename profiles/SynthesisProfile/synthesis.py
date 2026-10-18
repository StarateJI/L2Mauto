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

# Кнопка «Меню» — открывает всё: классы, агатионы, данжи, аук, почту и т.д.
# Одна кнопка для всего. Координаты в процентах от размера окна.
BTN_MENU = (0.953, 0.062)

# Кнопка закрытия (крестик)
BTN_CLOSE = (0.97, 0.03)


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
        wx, wy = window["Position"]
        rx = random.randint(-3, 3)
        ry = random.randint(-2, 2)
        x = int(ww * x_pct) + rx
        y = int(wh * y_pct) + ry
        await self._activate()
        await asyncio.sleep(0.2 + random.uniform(0, 0.15))
        # Передаём только СВОЁ окно, не весь словарь
        win_info = {self.window_id: window}
        log(f"Синтез: клик {label} ({x},{y}) offset=({rx},{ry}) "
            f"окно=({wx},{wy}) {ww}x{wh}", self.window_id)
        await self.mouse.click(win_info, x, y)
        await asyncio.sleep(0.3 + random.uniform(0.1, 0.3))

    async def _is_menu_open(self, wx, wy, ww, wh):
        """Проверить — открыто ли меню (template matching по ряду вкладок).

        Берём эталон (menu_tabs_template.png — ряд вкладок Класс→Артефакты),
        ищем его через cv2.matchTemplate в правой части экрана.
        Если найдено с max_val > 0.6 — меню открыто.

        Преимущества над яркостью:
          - не зависит от яркости локации (тёмная/яркая сцена — неважно)
          - ищет конкретный UI-элемент (иконки+текст вкладок),
            который есть ТОЛЬКО когда меню открыто
          - масштабо-независимо: перебираем 7 масштабов (0.6..1.6x)
            для разных разрешений окна

        Замер на скринах пользователя (catbox sj36q8.jpg):
          CLOSED: max_val=0.355  (< 0.6 → не найдено ✓)
          OPEN:   max_val=1.000  (> 0.6 → найдено ✓)
        """
        # Зона поиска: правая половина экрана (где появляется панель меню)
        sx1, sy1 = int(ww * 0.55), int(wh * 0.05)
        sx2, sy2 = int(ww * 0.99), int(wh * 0.40)
        screen = self._grab_window_rect(wx, wy, sx1, sy1, sx2 - sx1, sy2 - sy1)
        if screen is None:
            log("Синтез: _is_menu_open — не удалось снять скрин, "
                "считаем что закрыто", self.window_id, level="WARNING")
            return False

        # Загрузить эталон один раз и кешировать
        if not hasattr(self, "_menu_tabs_template"):
            try:
                tpl_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "menu_tabs_template.png")
                tpl = cv2.imread(tpl_path, cv2.IMREAD_GRAYSCALE)
                if tpl is None:
                    log(f"Синтез: НЕ ЗАГРУЖЕН template {tpl_path}",
                        self.window_id, level="ERROR")
                    self._menu_tabs_template = None
                else:
                    self._menu_tabs_template = tpl
                    log(f"Синтез: загружен template {tpl.shape[1]}x{tpl.shape[0]}",
                        self.window_id)
            except Exception as e:
                log(f"Синтез: ошибка загрузки template: {e}",
                    self.window_id, level="ERROR")
                self._menu_tabs_template = None

        if self._menu_tabs_template is None:
            # Fallback: brightness ratio (старый метод, менее надёжный)
            log("Синтез: нет template — fallback на яркость",
                self.window_id, level="WARNING")
            right_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
            r_mean = float(right_gray.mean())
            is_open = r_mean < 60
            log(f"Синтез: меню {'ОТКРЫТО' if is_open else 'ЗАКРЫТО'} "
                f"(fallback mean={r_mean:.0f})", self.window_id)
            return is_open

        screen_gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)
        tpl = self._menu_tabs_template

        # Перебор масштабов (окно может быть любого размера).
        # 4 масштаба — баланс между точностью и скоростью (~0.5-1с на вызов).
        best_val = 0.0
        best_scale = 1.0
        for scale in (0.85, 1.0, 1.15, 1.3):
            new_w = max(1, int(tpl.shape[1] * scale))
            new_h = max(1, int(tpl.shape[0] * scale))
            if new_w > screen_gray.shape[1] or new_h > screen_gray.shape[0]:
                continue
            scaled = cv2.resize(tpl, (new_w, new_h), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(screen_gray, scaled, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val > best_val:
                best_val = max_val
                best_scale = scale

        is_open = best_val > 0.6
        log(f"Синтез: меню {'ОТКРЫТО ✓' if is_open else 'ЗАКРЫТО ✗'} "
            f"(matchTemplate max_val={best_val:.3f} при scale={best_scale}, "
            f"порог 0.6)", self.window_id)
        return is_open

    async def _open_menu(self, wx, wy, ww, wh):
        """Убедиться, что меню открыто.

        1. Сначала проверяем — может меню уже открыто (не toggle-им его закрытым!).
        2. Если закрыто — кликаем Меню, ждём, проверяем.
        3. До 3 попыток. Если за 3 попытки не открылось — кликаем крестик (X),
           потом снова Меню (на случай что поверх висит диалог).
        """
        # 0. Может уже открыто?
        if await self._is_menu_open(wx, wy, ww, wh):
            log("Синтез: меню уже открыто — не кликаю Меню (не toggle-им)",
                self.window_id)
            return True

        for attempt in range(3):
            log(f"Синтез: меню закрыто — кликаю Меню (попытка {attempt + 1}/3)",
                self.window_id)
            await self._click_pct(*BTN_MENU, f"Меню (попытка {attempt + 1})")
            await asyncio.sleep(3 + random.uniform(0, 0.5))
            if await self._is_menu_open(wx, wy, ww, wh):
                log("Синтез: меню открылось ✓", self.window_id)
                return True
            log(f"Синтез: после клика меню всё ещё закрыто",
                self.window_id, level="WARNING")
            # Возможно поверх висит диалог/окно — кликнем крестик и повторим
            if attempt == 0:
                log("Синтез: пробую закрыть возможный диалог (X)",
                    self.window_id, level="WARNING")
                await self._click_pct(*BTN_CLOSE, "X (закрыть диалог)")
                await asyncio.sleep(2)
        log("Синтез: НЕ СМОГ открыть меню за 3 попытки",
            self.window_id, level="ERROR")
        return False

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

            if show_all_mean > 90:
                # Жмём «Показать все» / «Перейти к результату»
                log(f"Синтез: Показать все/Перейти (mean={show_all_mean:.0f})",
                    self.window_id)
                await self._click_pct(*BTN_SHOW_ALL, "Показать все/Перейти")
                await asyncio.sleep(1 + random.uniform(0, 0.3))
                continue

            # Проверяем — есть ли кнопка «Повтор»
            repeat_mean = self._check_brightness(wx, wy, ww, wh, *BTN_REPEAT)

            if repeat_mean > 20:
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
        2. Клик по подвкладке «Синтез» (один раз, не в цикле)
        3. Цикл: Автовыбор → проверка Синтез → Синтез → спам → Все
        4. Если Синтез тусклая → Выход → return (следующая категория)
        5. После Выхода — нажать Меню чтобы открыть вкладки для следующей категории
        """
        log(f"Синтез: === Категория: {category_name} ===", self.window_id)

        # 1. Клик по вкладке категории
        await self._click_pct(tab_x, tab_y, f"Вкладка {category_name}")
        await asyncio.sleep(1.5 + random.uniform(0, 0.3))

        # 2. Клик по подвкладке «Синтез» — ОДИН РАЗ, не в цикле
        await self._click_pct(*TAB_SYNTHESIS, "Вкладка Синтез")
        await asyncio.sleep(1)

        # Скриншот для дебага
        screen = self._grab_window_rect(wx, wy, 0, 0, ww, wh)
        if screen is not None:
            self._save_debug(f"synth_{category_name}_opened.png", screen)

        # 3. Главный цикл синтеза
        synth_round = 0
        while synth_round < 10:
            synth_round += 1
            log(f"Синтез: {category_name} — раунд {synth_round}", self.window_id)

            # Автовыбор
            await self._click_pct(*BTN_AUTO_SELECT, "Автовыбор")
            await asyncio.sleep(1 + random.uniform(0, 0.3))

            # Проверить — активна ли кнопка Синтез (после Автовыбора)
            if not await self._is_synthesize_active(wx, wy, ww, wh):
                log(f"Синтез: {category_name} — кнопка Синтез тусклая, "
                    f"нет материалов. Выхожу и перехожу к следующей категории.",
                    self.window_id)
                await self._click_pct(*BTN_EXIT, "Выход (нет материалов)")
                await asyncio.sleep(3)
                # Меню НЕ закрывается кнопкой Выход (закрывается только подокно синтеза).
                # Проверяем — если меню почему-то закрылось, открываем.
                if not await self._is_menu_open(wx, wy, ww, wh):
                    await self._click_pct(*BTN_MENU, "Меню (после Выхода)")
                    await asyncio.sleep(2)
                return

            # Синтез (нажать КНОПКУ, не вкладку)
            await self._click_pct(*BTN_SYNTHESIZE, "Синтез (кнопка)")
            await asyncio.sleep(3 + random.uniform(0, 0.5))

            # Спам «Показать все» / «Повтор» пока есть → Выход
            await self._spam_repeat(wx, wy, ww, wh)

            # Нажать «Все» (фильтр слева вверху) — сбросить выбор
            await self._click_pct(*BTN_ALL_FILTER, "Фильтр Все")
            await asyncio.sleep(1 + random.uniform(0, 0.3))

        log(f"Синтез: {category_name} — достигнут лимит раундов (10), "
            f"переходим к следующей категории.", self.window_id, level="WARNING")

        # Выйти из окна синтеза. Меню НЕ закрывается (только подокно).
        # Проверяем — если меню почему-то закрылось, открываем для следующей категории.
        await self._click_pct(*BTN_EXIT, "Выход из категории")
        await asyncio.sleep(3)
        if not await self._is_menu_open(wx, wy, ww, wh):
            await self._click_pct(*BTN_MENU, "Меню (после Выхода из категории)")
            await asyncio.sleep(2)

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
            _saved_pos = None  # позиция ДО maximize
            try:
                win = gw.getWindowsWithTitle(self.window_info[window_id]["Title"])[0]
                _saved_pos = (win.left, win.top, win.width, win.height)
                log(f"Синтез: сохранил позицию: {_saved_pos}", window_id)
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

            # 2. Нажать кнопку Меню — открывает вкладки.
            # Проверяем template matching'ом — если уже открыто, не кликаем (не toggle-им).
            from bot.methods.game import PartyDungeon
            game = PartyDungeon(self)

            if not await self._is_menu_open(wx, wy, ww, wh):
                await self._click_pct(*BTN_MENU, "Меню (было закрыто)")
                await asyncio.sleep(2)
            else:
                log("Синтез: меню уже открыто на старте — не кликаю",
                    window_id)

            # 3. Обойти все 5 категорий
            # После Выхода из каждой категории меню НЕ закрывается (закрывается только подокно
            # синтеза), поэтому повторно кликать Меню НЕ нужно.
            for cat_name, tab_x, tab_y in TAB_CATEGORIES:
                await self._process_category(
                    game, cat_name, tab_x, tab_y, wx, wy, ww, wh
                )

            # 5. Закрыть меню
            await self._click_pct(*BTN_CLOSE, "Закрыть")
            await asyncio.sleep(1)

            # 6. Restore окно на СОХРАНЁННУЮ позицию
            if maximize_done and _saved_pos:
                try:
                    win = gw.getWindowsWithTitle(self.window_info[window_id]["Title"])[0]
                    hwnd = win._hWnd
                    u.ShowWindow(ctypes.c_void_p(int(hwnd)), SW_RESTORE)
                    await asyncio.sleep(0.5)
                    sl, st, sw, sh = _saved_pos
                    u.SetWindowPos(ctypes.c_void_p(int(hwnd)), None,
                                   sl, st, sw, sh, 0x0004 | 0x0010)
                    await asyncio.sleep(0.5)
                    win = gw.getWindowsWithTitle(self.window_info[window_id]["Title"])[0]
                    self.window_info[window_id]["Position"] = (win.left, win.top)
                    self.window_info[window_id]["Width"] = win.width
                    self.window_info[window_id]["Height"] = win.height
                    log(f"Синтез: окно возвращено на ({win.left},{win.top}) {win.width}x{win.height}",
                        window_id)
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
