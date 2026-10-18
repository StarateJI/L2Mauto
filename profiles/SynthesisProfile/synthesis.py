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
BTN_REPEAT      = (0.598, 0.886)
BTN_EXIT        = (0.503, 0.891)

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
        is_active = mean > 30
        log(f"Синтез: кнопка 'Синтез' mean={mean:.0f} "
            f"{'АКТИВНА' if is_active else 'тусклая (нет материалов)'}",
            self.window_id)
        return is_active

    async def _spam_repeat(self, wx, wy, ww, wh):
        """
        Спамить 'Показать все' → 'Повтор' пока есть Повтор.
        Когда осталась только 'Выход' — нажать Выход.
        """
        for attempt in range(50):
            # Снимаем экран
            screen = self._grab_window_rect(wx, wy, 0, 0, ww, wh)
            if screen is None:
                await asyncio.sleep(1)
                continue

            gray = cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY)

            # Проверяем — есть ли кнопка «Повтор» (яркая)
            repeat_mean = self._check_brightness(wx, wy, ww, wh, *BTN_REPEAT)
            # Проверяем — есть ли кнопка «Показать все»
            show_all_mean = self._check_brightness(wx, wy, ww, wh, *BTN_SHOW_ALL)

            if show_all_mean > 30:
                # Жмём «Показать все»
                log(f"Синтез: Показать все (mean={show_all_mean:.0f})", self.window_id)
                await self._click_pct(*BTN_SHOW_ALL, "Показать все")
                await asyncio.sleep(1 + random.uniform(0, 0.3))
                continue

            if repeat_mean > 30:
                # Жмём «Повтор»
                log(f"Синтез: Повтор (mean={repeat_mean:.0f})", self.window_id)
                await self._click_pct(*BTN_REPEAT, "Повтор")
                await asyncio.sleep(1.5 + random.uniform(0, 0.5))
                continue

            # Нет ни «Показать все», ни «Повтор» — только «Выход»
            log("Синтез: остался только Выход — нажимаю", self.window_id)
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
        while True:
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

            # Спам «Показать все» → «Повтор» пока есть
            await self._spam_repeat(wx, wy, ww, wh)

            # Нажать «Все» (фильтр слева вверху)
            log(f"Синтез: {category_name} — нажимаю фильтр 'Все'", self.window_id)
            await self._click_pct(*BTN_ALL_FILTER, "Фильтр Все")
            await asyncio.sleep(0.5 + random.uniform(0, 0.2))

            # Снова Автовыбор + проверка
            await self._click_pct(*BTN_AUTO_SELECT, "Автовыбор (2-й раунд)")
            await asyncio.sleep(0.5 + random.uniform(0, 0.2))

            if not await self._is_synthesize_active(wx, wy, ww, wh):
                log(f"Синтез: {category_name} — кнопка Синтез тусклая после "
                    f"фильтра 'Все'. Переходим к следующей категории.",
                    self.window_id)
                return

            # Синтез + спам
            await self._click_pct(*BTN_SYNTHESIZE, "Синтез (кнопка, 2-й раунд)")
            await asyncio.sleep(2 + random.uniform(0, 0.5))
            await self._spam_repeat(wx, wy, ww, wh)

            # Снова «Все» и проверка
            await self._click_pct(*BTN_ALL_FILTER, "Фильтр Все (2-й раунд)")
            await asyncio.sleep(0.5 + random.uniform(0, 0.2))

            # Проверяем — есть ли ещё материалы
            await self._click_pct(*BTN_AUTO_SELECT, "Автовыбор (проверка)")
            await asyncio.sleep(0.5 + random.uniform(0, 0.2))

            if not await self._is_synthesize_active(wx, wy, ww, wh):
                log(f"Синтез: {category_name} — материалов больше нет. "
                    f"Переходим к следующей категории.", self.window_id)
                return

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

            # 2. Открыть главное меню
            from bot.methods.game import PartyDungeon
            game = PartyDungeon(self)

            if not await game.wait_and_click("main_menu_gui", timeout=7):
                log("Синтез: не открыл главное меню", window_id)
                return False
            await asyncio.sleep(1.5)

            # 3. Найти и нажать кнопку «Синтез» в главном меню
            # TODO: нужна CBT-координата или координата кнопки синтеза в меню
            # Пока кликаем по координате — нужно уточнить
            # Возможно через wait_and_click("synthesis_menu") если есть в CBT
            # Временно: кликаем в правую часть меню где обычно «Развитие»/«Синтез»
            await self._click_pct(0.85, 0.35, "Кнопка Синтез в меню")
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

            # 6. Усыпить окно
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

    async def on_stop(self):
        self.running = False
        await super().on_stop()
        for task in self._child_tasks:
            task.cancel()
        await asyncio.gather(*self._child_tasks, return_exceptions=True)

    def is_running(self) -> bool:
        return self.running
