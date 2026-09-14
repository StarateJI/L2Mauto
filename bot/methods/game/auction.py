"""
Auction relist module.

Снимает лот с продажи -> находит предмет в инвентаре (SIFT) ->
ставит обратно с ценой "минус 1 от текущей минимальной".

Окно работает в 1280x720 на (100,100). НЕ 2560x1440 — там баг CEF:
SetWindowPos не вызывает WM_SIZE для HTML-overlay, кнопка ОК
"видна но не кликается". Через resizeTo+moveTo всё работает.

Все координаты — window-relative (window=1280x720).
mouse.click(self.window_info, x, y) сам добавит window["Position"].
"""
import asyncio
import os
import time
from typing import Optional, Tuple

import cv2
import mss
import numpy as np
import pytesseract

from bot.clogger import log
from bot.delays import DELAY_WAIT_AUCTION
from bot.methods.base import parseCBT
from bot.methods.game._base import GameAction


# ── Tesseract (ставится отдельно, дефолтный путь UB Mannheim) ─────────────
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ── mss singleton: открывается ОДИН раз, не на каждый захват ───────────────
_sct = mss.MSS()

# ── Рабочий размер окна ───────────────────────────────────────────────────
WORK_W, WORK_H = 1280, 720
# Две позиции для пачки из 2 окон на мониторе 2560×1440:
#   окно 1: (0, 40) — левая половина (y=40 — Windows не даёт y=0 из-за title bar)
#   окно 2: (1280, 40) — правая половина
# _resize_work сам выберет свободную позицию через findAllWindows().
WORK_POSITIONS = [(0, 40), (1280, 40)]
# Допуск по позиции при проверке: Windows может сместить окно на ±10px
POSITION_TOLERANCE = 15
REST_W, REST_H = 400, 225  # вернуть обратно после работы

# ── UI кнопки (window-relative, 1280x720) ─────────────────────────────────
BTN_TAB_SELL = (282, 117)        # вкладка "Продажа"
BTN_CANCEL_LOT = (867, 238)      # "Отмена лота" на первой строке
BTN_OK_CANCEL = (728, 510)       # оранжевая "ОК" в окне подтверждения отмены
BTN_OK_PRICE = (750, 625)        # "ОК" в окне ввода цены
BTN_ADD = (729, 510)             # "Добавить" (ставит лот на продажу)
BTN_CLOSE = (1218, 46)           # крестик (закрыть аук/меню)
BTN_FIELD_PRICE = (576, 547)     # центр поля "Общая цена" — кликнуть перед вводом

# ── Зоны захвата (window-relative) ────────────────────────────────────────
# ⚠️ ФИКС: раньше было (170, 277, 83, 77) — это захватывало ТЕКСТ названия
# шлема, а не саму иконку! SIFT искал текст в инвентаре — 0 совпадений.
# Из переписки: LOT_ICON был (80, 195, 67, 61). Расширил до 80×70 с запасом.
# Это та самая иконка, что в инвентаре и в окне подтверждения — одинаковая.
LOT_SEARCH = (75, 190, 80, 70)

# Зона инвентаря — расширенная (+40px вниз), чтобы предмет в самом низу
# последней страницы тоже попадал в кадр.
INV_SCAN = (915, 173, 345, 424)

# Зона OCR "Текущая минимальная цена"
ZONE_PRICE = (868, 306, 80, 20)

# Зона статуса первого лота: где написано «Продаётся» или «3д23ч» (таймер).
# По VLM-анализу скриншота: текст статуса находится СТРОГО НАД кнопкой
# «Отмена» (867,238), выровнен по центру. Зона: ширина 140px, центр X=867.
# Y = 190..225 (строго над кнопкой, на той же строке что и название лота).
STATUS_ZONE = (797, 190, 140, 35)

# Зона проверки окна подтверждения (оранжевая кнопка ОК)
OK_CHECK_ZONE = (700, 480, 60, 60)

# ── Калькулятор (3x4 numpad) ──────────────────────────────────────────────
# База: "5" на (778, 521). Шаг 40px по обеим осям.
CALC_DIGITS = {
    '0': (778, 602),
    '1': (738, 562),
    '2': (778, 562),
    '3': (819, 562),
    '4': (738, 521),
    '5': (778, 521),
    '6': (819, 521),
    '7': (738, 481),
    '8': (778, 481),
    '9': (819, 481),
}

# ── Свайп инвентаря ───────────────────────────────────────────────────────
INV_CX = 1187      # X центра свайпа (над ячейками, не цепляет предметы)
SWIPE_STEP = 130   # px за один свайп (клетка ~68px, 130 = ~2 строки)

# ── Тайминги (секунды) — ускорены в 5.0.7 ────────────────────────────────
T_CONFIRM_SETTLE = 1.5    # было 3.0 — анимация окна подтверждения
T_ITEM_WINDOW = 2.5       # было 4.0 — прогрузка окна цены после клика по предмету
T_PAGE_LOAD = 1.5         # было 3.0 — пауза после свайпа страницы
LONG_PAUSE = 2.5          # было 4.0 — после выставления лота

# ── SIFT ──────────────────────────────────────────────────────────────────
# SIFT оставлен как fallback. Основной метод теперь — multi-scale
# template matching в _find_item (надёжнее для одинаковых иконок).
SIFT_THRESHOLD = 3
CLUSTER_RADIUS = 50
LOWE_RATIO = 0.75      # Lowe ratio test для BFMatcher

# ── Template Matching ─────────────────────────────────────────────────────
# Порог корреляции (0..1). 0.75 = высокая уверенность. Если предмет на странице
# есть — matchTemplate даст >0.9. Если нет — <0.4. Нет серой зоны.
TM_THRESHOLD = 0.75
# Масштабы для multi-scale (иконка в инвентаре может быть чуть другого размера)
TM_SCALES = [0.85, 0.92, 1.0, 1.08, 1.15]

# ── Лимиты ────────────────────────────────────────────────────────────────
SCAN_PAGES = 5          # страниц инвентаря (предмет падает в КОНЕЦ)
MAX_OK_RETRIES = 4      # попыток кликнуть ОК отмены
MAX_ITEMS = 10          # максимум предметов за один прогон


class Auction(GameAction):
    """Перестановка лотов аукциона: снять -> найти -> выставить с ценой min-1."""

    # ──────────────────────────────────────────────────────────────────────
    # ТОЧКА ВХОДА (вызывается из profiles/Auction/auction.py и pvp.py)
    # ──────────────────────────────────────────────────────────────────────
    async def reregister(self) -> bool:
        """
        Снять все лоты с продажи и переставить их с ценой минус 1 от минималки.
        Возвращает True если хотя бы один предмет переставлен.

        ВАЖНО: всё обёрнуто в try/finally — даже если бот упал, в finally
        вызываются _resize_back (вернуть окно), BTN_CLOSE (закрыть аук),
        notify_screenshot (слать скрин в TG) и upload_run_logs (логи в GitHub).
        """
        log("Аук: запущен relist (снять+найти+поставить)", self.window_id)
        made = 0
        last_error: Optional[Exception] = None
        resize_done = False  # чтобы в finally знать — надо ли возвращать размер

        try:
            # 1. Разбудить окно — выйти из энерго
            try:
                if await self.profile.energo.is_on():
                    await self.profile.energo.turn_off()
            except Exception as e:
                log(f"Аук: энерго-выход не удался: {e}", self.window_id, level="WARNING")

            # 2. Открыть главное меню (CBT-кнопка, маленькое окно 400x225)
            if not await self.wait_and_click("main_menu_gui", timeout=7):
                log("Не удалось открыть главное меню В АУКЕ", self.window_id)
                return False

            # 3. Открыть аукцион (CBT-кнопка)
            if not await self.wait_and_click("auction_menu", timeout=4):
                log("Не удалось ткнуть по auction_menu", self.window_id)
                await self.wait_and_click("main_menu_gui", timeout=3)
                return False

            await asyncio.sleep(0.3)

            # 4. Дождаться загрузки аукциона (пиксель auction_nalog, до 60с)
            if not await self._wait_auction_loaded(timeout=60):
                log("Чет пошло не так, не прогрузился аук =( Пробую выйти в меню", self.window_id)
                await self.wait_and_click("main_menu_gui", timeout=1)
                return False

            log("Аук: загрузился", self.window_id)

            # 5. Развернуть окно в рабочий размер 1280x720 на (100,100)
            if not await self._resize_work():
                log("Аук: не удалось установить рабочий размер — СТОП",
                    self.window_id, level="ERROR")
                await self.wait_and_click("main_menu_gui", timeout=1)
                return False
            resize_done = True

            # 6. Кликнуть вкладку "Продажа"
            await self._click(*BTN_TAB_SELL)
            await asyncio.sleep(3)
            log("Аук: вкладка Продажа открыта", self.window_id)

            # 7. Цикл по предметам
            for i in range(1, MAX_ITEMS + 1):
                log(f"Аук: предмет {i}/{MAX_ITEMS}", self.window_id)
                result = await self._one_item_cycle()
                if result == 'ok':
                    made += 1
                    log(f"Аук: предмет {i} переставлен", self.window_id)
                elif result == 'empty':
                    log(f"Аук: лотов больше нет на странице (предмет {i})", self.window_id)
                    break
                else:  # 'error'
                    log(f"Аук: ошибка на предмете {i} — стоп, сделано {made}",
                        self.window_id, level="ERROR")
                    break

        except asyncio.CancelledError:
            # Пользователь нажал СТОП ВСЕ. finally всё равно выполнится —
            # окно вернётся, аук закроется, логи уйдут в GitHub.
            last_error = RuntimeError("Stopped by user (CancelledError)")
            log("Аук: стопнут пользователем (CancelledError) — запускаю finally",
                self.window_id, level="WARNING")
            made = 0
            # НЕ reraise — finally выполнится, бот вернёт окно и шлёт логи

        except Exception as e:
            last_error = e
            import traceback
            tb = traceback.format_exc()
            log(f"Аук: УПАЛ с исключением: {e}\n{tb}", self.window_id, level="ERROR")
            made = 0

        finally:
            # ── ВСЁ что ниже — выполняется ВСЕГДА ──────────────────────────
            # Даже если бот упал, даже если пользователь стопнул (CancelledError).

            # 8. Вернуть размер окна (если увеличивали)
            if resize_done:
                try:
                    await self._resize_back()
                except Exception as e:
                    log(f"Аук: не удалось вернуть размер окна: {e}",
                        self.window_id, level="WARNING")

            # 9. Закрыть аук/меню (всегда — аук не должен остаться открытым)
            try:
                await self._click(*BTN_CLOSE)
                await asyncio.sleep(3)
                log("Аук: аук закрыт", self.window_id)
            except Exception as e:
                log(f"Аук: не удалось закрыть аук: {e}", self.window_id, level="WARNING")

            # 10. Уведомление в TG
            try:
                if made > 0:
                    self.profile.notify("info", f"Аук: переставлено лотов {made}")
                    log(f"Аук: готово, переставлено {made}", self.window_id)
                elif last_error is not None:
                    self.profile.notify("error",
                                      f"Аук: УПАЛ с ошибкой: {last_error}")
                    # Слать скрин в TG — для диагностики
                    try:
                        self.profile.notify_screenshot(
                            f"Аук упал: {last_error}", level="error")
                    except Exception:
                        pass
                else:
                    self.profile.notify("warning",
                                      "Аук: не удалось переставить ни один лот")
            except Exception as e:
                log(f"Аук: не удалось отправить TG-уведомление: {e}",
                    self.window_id, level="WARNING")

            # 11. Загрузить логи + debug PNG в GitHub (ветка bot-logs)
            #     ВСЕГДА — независимо от результата. Если бот упал, тем более
            #     важно чтобы логи ушли в GitHub.
            try:
                from bot.log_uploader import upload_run_logs
                upload_run_logs(self.window_id, made=made,
                              error=str(last_error) if last_error else None)
            except Exception as e:
                log(f"Аук: log_uploader не сработал: {e}",
                    self.window_id, level="WARNING")

        return made > 0

    # ──────────────────────────────────────────────────────────────────────
    # РАЗМЕР ОКНА
    # ──────────────────────────────────────────────────────────────────────
    async def _resize_work(self) -> bool:
        """
        Установить окно в 1280x720. До 3 попыток.
        Авто-выбор позиции: проверяет какие из WORK_POSITIONS уже заняты
        другим окном L2M (через findAllWindows) и занимает первую свободную.
        Это позволяет двум ботам в пачке работать рядом, не перекрывая друг друга.
        """
        import ctypes
        import pygetwindow as gw

        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SetWindowPos = ctypes.windll.user32.SetWindowPos

        # Сохраняем исходную позицию ДО изменений (один раз за весь цикл)
        if not hasattr(self.profile, '_au_saved_pos') or self.profile._au_saved_pos is None:
            try:
                win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
                self.profile._au_saved_pos = (win.left, win.top, win.width, win.height)
                log(f"Аук: сохранил позицию окна до resize: "
                    f"({win.left},{win.top}) {win.width}x{win.height}",
                    self.window_id)
            except Exception as e:
                log(f"Аук: не удалось сохранить позицию: {e}",
                    self.window_id, level="WARNING")

        # ── Авто-выбор позиции ─────────────────────────────────────────────
        # Найти свободную из WORK_POSITIONS: проверяем все окна L2M, если
        # какое-то уже стоит 1280x720 в позиции — считаем её занятой.
        chosen_pos: Optional[Tuple[int, int]] = None
        try:
            from bot.utils import findAllWindows as _findAll
            all_wins = _findAll()
            occupied: set = set()
            my_title = self.window_info[self.window_id]["Title"]
            for nick, info in all_wins.items():
                # Свой заголовок не считаем занятым
                if info.get("Title") == my_title:
                    continue
                w, h = info.get("Width", 0), info.get("Height", 0)
                if w == WORK_W and h == WORK_H:
                    pos = (info.get("Position", (0, 0))[0],
                           info.get("Position", (0, 0))[1])
                    occupied.add(pos)
            for pos in WORK_POSITIONS:
                if pos not in occupied:
                    chosen_pos = pos
                    break
            if chosen_pos is None:
                # Все заняты — берём первую (перекрытие, но не падаем)
                chosen_pos = WORK_POSITIONS[0]
                log(f"Аук: все рабочие позиции заняты, использую {chosen_pos} "
                    f"(возможно перекрытие)", self.window_id, level="WARNING")
            else:
                log(f"Аук: выбрал позицию {chosen_pos} (занято: {occupied})",
                    self.window_id)
        except Exception as e:
            log(f"Аук: не удалось проверить занятость позиций: {e}, "
                f"использую {WORK_POSITIONS[0]}", self.window_id, level="WARNING")
            chosen_pos = WORK_POSITIONS[0]

        for attempt in range(1, 4):
            try:
                win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
                try:
                    win.restore()
                except Exception:
                    pass
                if win.isMaximized:
                    try:
                        win.unmaximize()
                    except Exception:
                        pass
                await asyncio.sleep(0.3)

                win.moveTo(*chosen_pos)
                await asyncio.sleep(0.2)
                win.resizeTo(WORK_W, WORK_H)
                await asyncio.sleep(0.5)

                hwnd = win._hWnd
                SetWindowPos(
                    ctypes.c_void_p(int(hwnd)), None,
                    chosen_pos[0], chosen_pos[1], WORK_W, WORK_H,
                    SWP_NOZORDER | SWP_NOACTIVATE,
                )
                await asyncio.sleep(0.4)

                win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
                # Проверка с допуском POSITION_TOLERANCE — Windows иногда
                # смещает окно на несколько пикселей (title bar snapping)
                size_ok = (win.width == WORK_W and win.height == WORK_H)
                pos_ok = (abs(win.left - chosen_pos[0]) <= POSITION_TOLERANCE and
                          abs(win.top - chosen_pos[1]) <= POSITION_TOLERANCE)
                if size_ok and pos_ok:
                    log(f"Аук: окно в рабочем размере (попытка {attempt}) "
                        f"на ({win.left},{win.top})", self.window_id)
                    self.window_info[self.window_id]["Position"] = (win.left, win.top)
                    self.window_info[self.window_id]["Width"] = win.width
                    self.window_info[self.window_id]["Height"] = win.height
                    self.window_info[self.window_id]["Size"] = f"{win.width}x{win.height}"
                    # Сохранить выбранную позицию для лога в _resize_back
                    self.profile._au_chosen_pos = chosen_pos
                    return True
                else:
                    log(f"Аук: resize не совпал: got ({win.left},{win.top}) "
                        f"{win.width}x{win.height}, wanted {chosen_pos} "
                        f"{WORK_W}x{WORK_H}, retry",
                        self.window_id, level="WARNING")
            except Exception as e:
                log(f"Аук: resize попытка {attempt} неудача: {e}",
                    self.window_id, level="WARNING")

        log("Аук: РАЗМЕР НЕ ВСТАЛ — СТОП", self.window_id, level="ERROR")
        return False

    async def _resize_back(self) -> None:
        """Вернуть окно в исходное положение (сохранённое до resize_work)."""
        import pygetwindow as gw

        saved = getattr(self.profile, '_au_saved_pos', None)
        if saved:
            left, top, w, h = saved
            # Сбросить флаг — следующий прогон сохранит заново
            self.profile._au_saved_pos = None
        else:
            left, top, w, h = 0, 40, REST_W, REST_H

        try:
            win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
            # Сначала moveTo в нужное место, потом resize — иначе resizeTo может
            # «зацепить» позицию другого окна.
            win.moveTo(left, top)
            await asyncio.sleep(0.2)
            win.resizeTo(w, h)
            await asyncio.sleep(0.4)

            self.window_info[self.window_id]["Position"] = (win.left, win.top)
            self.window_info[self.window_id]["Width"] = win.width
            self.window_info[self.window_id]["Height"] = win.height
            self.window_info[self.window_id]["Size"] = f"{win.width}x{win.height}"
            log(f"Аук: окно возвращено {win.width}x{win.height} на ({win.left},{win.top})",
                self.window_id)
        except Exception as e:
            log(f"Аук: не удалось вернуть размер окна: {e}",
                self.window_id, level="WARNING")

    # ──────────────────────────────────────────────────────────────────────
    # ОЖИДАНИЕ ЗАГРУЗКИ АУКЦИОНА
    # ──────────────────────────────────────────────────────────────────────
    async def _wait_auction_loaded(self, timeout: int = 60) -> bool:
        """Ждать пиксель auction_nalog. До timeout секунд, проверка каждые 3с."""
        xy, rgb = parseCBT("auction_nalog", profile=self.profile)
        if xy is None:
            log("Аук: auction_nalog не найден в CBT", self.window_id, level="ERROR")
            return False

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if await self.profile.check_pixel(xy, rgb, timeout=1, thr=4):
                    return True
            except Exception:
                pass
            await asyncio.sleep(3)
        return False

    # ──────────────────────────────────────────────────────────────────────
    # ЗАХВАТ ЭКРАНА (window-relative)
    # ──────────────────────────────────────────────────────────────────────
    def _grab(self, rect: Tuple[int, int, int, int]) -> np.ndarray:
        """
        Захват зоны rect=(x, y, w, h) в window-relative координатах.
        Возвращает BGR ndarray. mss отдаёт BGRA — конвертируем.
        """
        win = self.window_info[self.window_id]
        wx, wy = win["Position"]
        x, y, w, h = rect
        monitor = {"left": wx + x, "top": wy + y, "width": w, "height": h}
        shot = _sct.grab(monitor)
        arr = np.array(shot)  # BGRA
        return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)

    async def _save_debug(self, name: str, img: np.ndarray) -> None:
        """Сохранить PNG рядом с auction.py для отладки."""
        try:
            out_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(out_dir, name)
            cv2.imwrite(path, img)
            log(f"Аук: сохранён {name}", self.window_id)
        except Exception as e:
            log(f"Аук: не удалось сохранить {name}: {e}", self.window_id, level="WARNING")

    # ──────────────────────────────────────────────────────────────────────
    # КЛИКИ
    # ──────────────────────────────────────────────────────────────────────
    async def _click(self, x: int, y: int) -> None:
        """Клик по window-relative координатам через очередь мыши."""
        await self.mouse.click(self.window_info, x, y)

    async def _swipe_inventory(self, direction: str) -> None:
        """
        Свайп инвентаря. direction='down' — следующая страница, 'up' — назад.

        Генерирует ~20 промежуточных точек между start и end — swipe
        получается медленным и плавным. Старый вариант с 2 точками делал
        FLICK (быстрый резкий жест) и эластичный скролл Lineage2M улетал
        далеко за пределы («сразу в самый низ»).
        """
        cx = INV_CX
        top_y = INV_SCAN[1] + 20
        bot_y = INV_SCAN[1] + INV_SCAN[3] - 20

        if direction == "down":
            # контент едет ВВЕРХ (видим нижние предметы): мышь снизу вверх
            start_y, end_y = bot_y, top_y
        else:  # 'up'
            # контент едет ВНИЗ (видим верхние предметы): мышь сверху вниз
            start_y, end_y = top_y, bot_y

        # Плавный свайп: 20 шагов по 0.04с = ~0.8с на весь свайп.
        # Никакого flick — игра скроллит ровно на SWIPE_STEP px.
        N_STEPS = 20
        STEP_DELAY = 0.04
        points = []
        for i in range(N_STEPS + 1):
            t = i / N_STEPS
            y = int(start_y + (end_y - start_y) * t)
            points.append((cx, y))

        await self.mouse.swipe(self.window_info, points,
                               delay_points=STEP_DELAY, no_curve=True)
        log(f"Аук: свайп инвентаря {direction} ({len(points)} точек, "
            f"{start_y}->{end_y})", self.window_id)
        await asyncio.sleep(T_PAGE_LOAD)

    # ──────────────────────────────────────────────────────────────────────
    # ОКНО ПОДТВЕРЖДЕНИЯ
    # ──────────────────────────────────────────────────────────────────────
    def _orange_at(self, x: int, y: int, w: int = 60, h: int = 60) -> bool:
        """Проверка оранжевых пикселей в зоне (оранжевая кнопка ОК)."""
        try:
            img = self._grab((x, y, w, h))
            # Оранжевый: R высокий, G средний, B низкий
            b, g, r = cv2.split(img)
            mask = (r > 180) & (g > 80) & (g < 180) & (b < 80)
            return int(np.sum(mask)) > 50  # хотя бы 50 оранжевых пикселей
        except Exception:
            return False

    def _confirm_window_visible(self) -> bool:
        """Окно подтверждения отмены видно (оранжевая кнопка ОК на месте)."""
        return self._orange_at(*OK_CHECK_ZONE)

    # ──────────────────────────────────────────────────────────────────────
    # СНЯТИЕ ЛОТА
    # ──────────────────────────────────────────────────────────────────────
    def _is_status_prodano(self) -> bool:
        """
        Проверить, что первый лот в статусе «Продаётся» (только что переставлен).
        Возвращает True если OCR нашёл слово «продаётся»/«продается» в STATUS_ZONE.
        Такие лоты НЕ трогаем — иначе вечный цикл: снять → поставить → «Продаётся» → снять...
        """
        try:
            img = self._grab(STATUS_ZONE)
            # Сохраняем для отладки — пользователь увидит попадает ли зона в текст
            import cv2
            import os
            debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "au_status.png")
            cv2.imwrite(debug_path, img)
            # OCR с увеличением x2 — текст мелкий, надо подсунуть крупнее
            h, w = img.shape[:2]
            big = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
            # PSM 7 = одна строка текста
            text = pytesseract.image_to_string(
                gray,
                lang="rus+eng",
                config="--psm 7",
            ).strip().lower()
            log(f"Аук: статус лота OCR: '{text}'", self.window_id, level="DEBUG")

            # Если OCR словил «отме» (кусок «Отмена») — зона сползла на кнопку,
            # проверка ненадёжна. Логируем, но не блокируем.
            if "отме" in text and "прода" not in text:
                log("Аук: OCR словил 'Отмена' — зона сползла на кнопку, "
                    "проверка статуса пропущена (не блокирую)",
                    self.window_id, level="WARNING")
                return False

            # Проверяем ключевые слова (с буквой ё и без)
            return ("продаёт" in text or "продает" in text or "продаю" in text
                    or "продажа" in text or "продаё" in text or "продае" in text)
        except Exception as e:
            log(f"Аук: OCR статуса не удался: {e}", self.window_id, level="WARNING")
            return False  # Если OCR упал — не блокируем, продолжаем

    async def _cancel_lot(self) -> bool:
        """Клик 'Отмена лота' и ожидание окна подтверждения."""
        for attempt in range(1, 3):
            await self._click(*BTN_CANCEL_LOT)
            log(f"Аук: клик Отмена лота ({attempt}/2) {BTN_CANCEL_LOT}", self.window_id)
            await asyncio.sleep(1.5)
            if self._confirm_window_visible():
                log("Аук: окно подтверждения появилось", self.window_id)
                return True
        log("Аук: окно подтверждения НЕ появилось", self.window_id, level="WARNING")
        return False

    async def _click_ok_cancel(self) -> bool:
        """Клик ОК в окне подтверждения. До 4 попыток."""
        for attempt in range(1, MAX_OK_RETRIES + 1):
            await self._click(*BTN_OK_CANCEL)
            log(f"Аук: клик ОК отмены ({attempt}/{MAX_OK_RETRIES}) {BTN_OK_CANCEL}",
                self.window_id)
            await asyncio.sleep(T_CONFIRM_SETTLE)
            if not self._confirm_window_visible():
                log(f"Аук: ОК сработал с попытки {attempt}", self.window_id)
                return True
        log("Аук: ОК НЕ сработал за все попытки", self.window_id, level="ERROR")
        return False

    # ──────────────────────────────────────────────────────────────────────
    # OCR ЦЕНЫ
    # ──────────────────────────────────────────────────────────────────────
    def _ocr_price(self) -> Optional[int]:
        """
        OCR 'Текущая минимальная цена' из ZONE_PRICE.
        Возвращает int или None.
        """
        try:
            img = self._grab(ZONE_PRICE)
            # Увеличиваем x4 — OCR любит крупные буквы
            h, w = img.shape[:2]
            big = cv2.resize(img, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
            # Ч/б + инверсия (tesseract лучше читает чёрный текст на белом)
            gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
            inv = cv2.bitwise_not(gray)
            # Жёсткий контраст
            _, thr = cv2.threshold(inv, 128, 255, cv2.THRESH_BINARY)

            # PSM 7 = одна строка, whitelist = цифры
            text = pytesseract.image_to_string(
                thr,
                config="--psm 7 -c tessedit_char_whitelist=0123456789",
            ).strip()
            # Убираем запятые/пробелы (12,500 -> 12500)
            digits = text.replace(",", "").replace(" ", "").replace(".", "")
            # Срезаем ведущие нули (00181 -> 181, но "0" оставляем как 0)
            digits = digits.lstrip('0') or '0'
            if not digits.isdigit():
                log(f"Аук: OCR вернул не цифры: '{text}'", self.window_id, level="WARNING")
                return None
            price = int(digits)
            log(f"Аук: OCR цена = {price} (raw='{text}')", self.window_id)
            return price
        except Exception as e:
            log(f"Аук: OCR цена не удался: {e}", self.window_id, level="WARNING")
            return None

    async def _type_price(self, price_str: str) -> None:
        """
        Ввести цену кликами по калькулятору.
        Сначала клик по полю 'Общая цена' (фокус), потом цифры по очереди.
        """
        # Фокус на поле "Общая цена" (иначе цифры уйдут в "Количество")
        await self._click(*BTN_FIELD_PRICE)
        await asyncio.sleep(0.4)

        for digit in price_str:
            coord = CALC_DIGITS.get(digit)
            if coord is None:
                log(f"Аук: неизвестная цифра '{digit}' — пропускаю",
                    self.window_id, level="WARNING")
                continue
            await self._click(*coord)
            await asyncio.sleep(0.15)
        log(f"Аук: введена цена {price_str}", self.window_id)

    # ──────────────────────────────────────────────────────────────────────
    # SIFT — поиск предмета в инвентаре
    # ──────────────────────────────────────────────────────────────────────
    def _sift_match(self, sample_gray: np.ndarray,
                    page_gray: np.ndarray) -> Tuple[Optional[Tuple[float, float]], int, int]:
        """
        SIFT-сравнение sample и page.
        Возвращает (центр_кластера, размер_кластера, всего_совпадений).
        center=None если кластер не найден.
        """
        sift = cv2.SIFT_create()
        kp1, des1 = sift.detectAndCompute(sample_gray, None)
        kp2, des2 = sift.detectAndCompute(page_gray, None)

        if des1 is None or des2 is None or len(des1) < 1 or len(des2) < 1:
            return None, 0, 0

        bf = cv2.BFMatcher()
        raw = bf.knnMatch(des1, des2, k=2)

        # Lowe ratio test
        good = []
        for pair in raw:
            if len(pair) == 2:
                m, n = pair
                if m.distance < LOWE_RATIO * n.distance:
                    good.append(m)

        if not good:
            return None, 0, 0

        # Кластеризация: для каждой точки считаем соседей в радиусе
        pts = np.array([kp2[m.trainIdx].pt for m in good], dtype=np.float32)
        best_cluster_size = 0
        best_center = None
        for p in pts:
            d = np.linalg.norm(pts - p, axis=1)
            cluster = pts[d <= CLUSTER_RADIUS]
            if len(cluster) > best_cluster_size:
                best_cluster_size = len(cluster)
                best_center = cluster.mean(axis=0)

        if best_center is None:
            return None, 0, len(good)
        return (float(best_center[0]), float(best_center[1])), best_cluster_size, len(good)

    def _match_template(self, sample_gray: np.ndarray,
                        page_gray: np.ndarray) -> Tuple[Optional[Tuple[int, int]], float, float, float]:
        """
        Multi-scale template matching. Перебирает масштабы, берёт лучший.
        Возвращает (center, best_score, scale, angle_or_0).
        center — координаты в page_gray (не INV_SCAN-relative).
        score в диапазоне 0..1.
        """
        best_score = 0.0
        best_loc: Optional[Tuple[int, int]] = None
        best_scale = 1.0
        h_sample, w_sample = sample_gray.shape[:2]

        for scale in TM_SCALES:
            new_w = int(w_sample * scale)
            new_h = int(h_sample * scale)
            if new_w < 5 or new_h < 5:
                continue
            if new_w > page_gray.shape[1] or new_h > page_gray.shape[0]:
                continue
            scaled = cv2.resize(sample_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
            try:
                result = cv2.matchTemplate(page_gray, scaled, cv2.TM_CCOEFF_NORMED)
            except cv2.error:
                continue
            _, max_val, _, max_loc = cv2.minMaxLoc(result)
            if max_val > best_score:
                best_score = max_val
                best_loc = (int(max_loc[0]) + new_w // 2,
                            int(max_loc[1]) + new_h // 2)
                best_scale = scale

        if best_loc is None or best_score < TM_THRESHOLD:
            return None, best_score, best_scale, 0.0
        return best_loc, best_score, best_scale, 0.0

    async def _find_item(self, sample_gray: np.ndarray) -> Optional[Tuple[int, int]]:
        """
        Искать предмет в инвентаре. До SCAN_PAGES страниц.
        Сначала сканирует текущую страницу, потом свайпает.
        Использует multi-scale template matching (основной) + SIFT (fallback).
        Возвращает (x, y) центра предмета или None.
        """
        best_overall: Tuple[int, float, str] = (0, 0.0, "none")  # (page, score, method)

        for page in range(1, SCAN_PAGES + 1):
            log(f"Аук: сканирую страницу {page}/{SCAN_PAGES} (свайпов до этого: {page-1})",
                self.window_id)
            img = self._grab(INV_SCAN)
            await self._save_debug(f"au_page_{page}.png", img)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # ── Основной метод: multi-scale template matching ──────────────
            center, score, scale, _ = self._match_template(sample_gray, gray)
            log(f"Аук: TM стр {page}: score={score:.3f} (порог {TM_THRESHOLD}) "
                f"scale={scale:.2f}", self.window_id)

            if score > best_overall[1]:
                best_overall = (page, score, "TM")

            if center is not None and score >= TM_THRESHOLD:
                cx = int(center[0]) + INV_SCAN[0]
                cy = int(center[1]) + INV_SCAN[1]
                log(f"Аук: предмет найден (TM) на стр {page} в ({cx},{cy}) "
                    f"score={score:.3f}", self.window_id)
                for _ in range(page - 1):
                    await self._swipe_inventory('up')
                return (cx, cy)

            # ── Fallback: SIFT (если TM не сработал) ────────────────────────
            sift_center, sift_cluster, sift_total = self._sift_match(sample_gray, gray)
            log(f"Аук: SIFT стр {page}: {sift_total} совп., кластер {sift_cluster}",
                self.window_id, level="DEBUG")
            if score > best_overall[1]:
                best_overall = (page, score, "SIFT")
            if sift_center is not None and sift_cluster >= SIFT_THRESHOLD:
                cx = int(sift_center[0]) + INV_SCAN[0]
                cy = int(sift_center[1]) + INV_SCAN[1]
                log(f"Аук: предмет найден (SIFT) на стр {page} в ({cx},{cy}) "
                    f"кластер={sift_cluster}", self.window_id)
                for _ in range(page - 1):
                    await self._swipe_inventory('up')
                return (cx, cy)

            if page < SCAN_PAGES:
                await self._swipe_inventory('down')

        for _ in range(SCAN_PAGES - 1):
            await self._swipe_inventory('up')
        log(f"Аук: предмет не найден ни на одной из {SCAN_PAGES} страниц. "
            f"Лучший результат: стр {best_overall[0]}, {best_overall[2]} "
            f"score={best_overall[1]:.3f} (порог TM={TM_THRESHOLD}, "
            f"SIFT={SIFT_THRESHOLD})", self.window_id, level="ERROR")
        return None

    # ──────────────────────────────────────────────────────────────────────
    # ГЛАВНЫЙ ЦИКЛ ОДНОГО ПРЕДМЕТА
    # ──────────────────────────────────────────────────────────────────────
    async def _one_item_cycle(self) -> str:
        """
        Обработка одного предмета: снять -> найти -> поставить.
        Возвращает 'ok' / 'empty' / 'error'.
        """
        # 1. Снять образец лота (вся зона целиком, без обрезки)
        sample = self._grab(LOT_SEARCH)
        await self._save_debug("au_lot_zone.png", sample)
        await self._save_debug("au_sample.png", sample)

        # Считаем SIFT keypoints образца (для лога)
        try:
            sift = cv2.SIFT_create()
            kp_sample, _ = sift.detectAndCompute(cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY), None)
            log(f"Аук: SIFT образец (лот): {len(kp_sample)} точек", self.window_id)
        except Exception:
            pass

        sample_gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)

        # 2. ПРОВЕРКА СТАТУСА «Продаётся» — ДО клика «Отмена».
        # Если первый лот в статусе «Продаётся» (только что переставлен) —
        # НЕ трогаем его. Возвращаем 'empty' → reregister() break →
        # защита от вечного цикла: снять → поставить → «Продаётся» → снять → ∞
        if self._is_status_prodano():
            log("Аук: первый лот в статусе «Продаётся» — пропускаю, "
                "не трогаю (защита от вечного цикла)", self.window_id)
            return 'empty'

        # 3. Клик "Отмена лота"
        if not await self._cancel_lot():
            return 'error'

        # 4. Подождать анимацию и кликнуть ОК
        await asyncio.sleep(T_CONFIRM_SETTLE)
        if not await self._click_ok_cancel():
            # Окно подтверждения не закрылось — попробуем закрыть вручную
            await self._click(*BTN_CLOSE)
            return 'error'

        log("Аук: лот снят, предмет упал в конец инвентаря", self.window_id)

        # 4. Найти предмет в инвентаре (SIFT, 5 страниц)
        await self._save_debug("au_after_click.png", self._grab(INV_SCAN))
        log("Аук: ищу предмет (SIFT)...", self.window_id)

        item_pos = await self._find_item(sample_gray)
        if item_pos is None:
            self.profile.notify("error",
                               f"Аук: ПРЕДМЕТ НЕ НАЙДЕН (SIFT, {SCAN_PAGES} стр)")
            return 'error'

        # 5. Кликнуть по найденному предмету
        await self._click(*item_pos)
        log(f"Аук: клик по предмету {item_pos}", self.window_id)
        await asyncio.sleep(T_ITEM_WINDOW)

        # 6. OCR "Текущая минимальная цена"
        min_price = self._ocr_price()
        if min_price is None or min_price < 10:
            log("Аук: не удалось прочитать мин. цену — ставлю 10", self.window_id,
                level="WARNING")
            my_price = 10
        else:
            my_price = max(min_price - 1, 10)  # не ниже 10 (игровой минимум)
            log(f"Аук: моя цена = {my_price} (мин={min_price})", self.window_id)

        # 7. Ввести цену
        await self._type_price(str(my_price))

        # 8. Клик "ОК" в окне цены
        await self._click(*BTN_OK_PRICE)
        await asyncio.sleep(1)

        # 9. Клик "Добавить"
        await self._click(*BTN_ADD)
        await asyncio.sleep(LONG_PAUSE)
        log("Аук: лот выставлен на продажу", self.window_id)

        return 'ok'
