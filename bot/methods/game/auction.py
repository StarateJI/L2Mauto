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
WORK_POS = (100, 100)
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
# Зона лота целиком, БЕЗ обрезки. SIFT сам разрулит фон вокруг иконки.
LOT_SEARCH = (170, 277, 83, 77)

# Зона инвентаря — расширенная (+40px вниз), чтобы предмет в самом низу
# последней страницы тоже попадал в кадр.
INV_SCAN = (915, 173, 345, 424)

# Зона OCR "Текущая минимальная цена"
ZONE_PRICE = (868, 306, 80, 20)

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

# ── Тайминги (секунды) ───────────────────────────────────────────────────
T_CONFIRM_SETTLE = 3.0    # анимация окна подтверждения
T_ITEM_WINDOW = 4.0       # прогрузка окна цены после клика по предмету
T_PAGE_LOAD = 3.0         # пауза после свайпа страницы
LONG_PAUSE = 4.0          # после выставления лота

# ── SIFT ──────────────────────────────────────────────────────────────────
# Порог 3 (был 4 — не дотягивал: в логе было 2 совп. при пороге 4).
# Радиус 50 (был 30 — реальные совпадения на сжатой иконке ~68×68
# разлетаются на 30-50px друг от друга).
SIFT_THRESHOLD = 3
CLUSTER_RADIUS = 50
LOWE_RATIO = 0.75      # Lowe ratio test для BFMatcher

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
        """
        log("Аук: запущен relist (снять+найти+поставить)", self.window_id)

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
            log("Аук: не удалось установить рабочий размер — СТОП", self.window_id, level="ERROR")
            await self.wait_and_click("main_menu_gui", timeout=1)
            return False

        # 6. Кликнуть вкладку "Продажа"
        await self._click(*BTN_TAB_SELL)
        await asyncio.sleep(3)
        log("Аук: вкладка Продажа открыта", self.window_id)

        # 7. Цикл по предметам
        made = 0
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

        # 8. Вернуть размер окна обратно
        await self._resize_back()

        # 9. Закрыть аук/меню
        await self._click(*BTN_CLOSE)
        await asyncio.sleep(3)
        log("Аук: аук закрыт", self.window_id)

        # 10. Уведомление в TG
        if made > 0:
            self.profile.notify("info", f"Аук: переставлено лотов {made}")
            log(f"Аук: готово, переставлено {made}", self.window_id)
        else:
            self.profile.notify("warning", "Аук: не удалось переставить ни один лот")

        # 11. Загрузить логи + debug PNG в GitHub (ветка bot-logs)
        #    чтобы я мог самостоятельно читать без copy-paste из чата.
        try:
            from bot.log_uploader import upload_run_logs
            upload_run_logs(self.window_id, made=made)
        except Exception as e:
            log(f"Аук: log_uploader не сработал: {e}", self.window_id, level="WARNING")

        return made > 0

    # ──────────────────────────────────────────────────────────────────────
    # РАЗМЕР ОКНА
    # ──────────────────────────────────────────────────────────────────────
    async def _resize_work(self) -> bool:
        """
        Установить окно в 1280x720 на (100,100). До 3 попыток.
        Сохраняет исходную позицию ДО resize, чтобы потом вернуть обратно.
        Принудительно использует SetWindowPos если resizeTo не влез в экран.
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

        for attempt in range(1, 4):
            try:
                win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
                # restore + unmaximize (иначе resizeTo игнорируется на maximized окнах)
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

                # Сначала moveTo в рабочую позицию, потом resize — так окно
                # точно окажется в видимой части экрана и не будет обрезано.
                win.moveTo(*WORK_POS)
                await asyncio.sleep(0.2)
                win.resizeTo(WORK_W, WORK_H)
                await asyncio.sleep(0.5)

                # Принудительно через SetWindowPos — надёжнее, фиксит случаи
                # когда resizeTo оставил окно в обрезанном состоянии.
                hwnd = win._hWnd
                SetWindowPos(
                    ctypes.c_void_p(int(hwnd)), None,
                    WORK_POS[0], WORK_POS[1], WORK_W, WORK_H,
                    SWP_NOZORDER | SWP_NOACTIVATE,
                )
                await asyncio.sleep(0.4)

                # Проверка
                win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
                if win.width == WORK_W and win.height == WORK_H \
                        and win.left == WORK_POS[0] and win.top == WORK_POS[1]:
                    log(f"Аук: окно в рабочем размере (попытка {attempt}) "
                        f"на ({win.left},{win.top})", self.window_id)
                    self.window_info[self.window_id]["Position"] = (win.left, win.top)
                    self.window_info[self.window_id]["Width"] = win.width
                    self.window_info[self.window_id]["Height"] = win.height
                    self.window_info[self.window_id]["Size"] = f"{win.width}x{win.height}"
                    return True
                else:
                    log(f"Аук: resize не совпал: got ({win.left},{win.top}) "
                        f"{win.width}x{win.height}, retry",
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
    async def _cancel_lot(self) -> bool:
        """Клик 'Отмена лота' и ожидание окна подтверждения."""
        for attempt in range(1, 3):
            await self._click(*BTN_CANCEL_LOT)
            log(f"Аук: клик Отмена лота ({attempt}/2) {BTN_CANCEL_LOT}", self.window_id)
            await asyncio.sleep(2)
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

    async def _find_item(self, sample_gray: np.ndarray) -> Optional[Tuple[int, int]]:
        """
        Искать предмет в инвентаре по SIFT. До SCAN_PAGES страниц.
        Сначала сканирует текущую страницу, потом свайпает — НЕ наоборот.
        Возвращает (x, y) центра предмета или None.
        """
        best_overall: Tuple[int, int, int] = (0, 0, 0)  # (page, cluster, total) для лога

        for page in range(1, SCAN_PAGES + 1):
            # СНАЧАЛА сканируем текущую страницу
            log(f"Аук: сканирую страницу {page}/{SCAN_PAGES} (свайпов до этого: {page-1})",
                self.window_id)
            img = self._grab(INV_SCAN)
            await self._save_debug(f"au_page_{page}.png", img)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            center, cluster_size, total = self._sift_match(sample_gray, gray)
            log(f"Аук: SIFT стр {page}: {total} совп., кластер {cluster_size} "
                f"(порог {SIFT_THRESHOLD})", self.window_id)

            if cluster_size > best_overall[2]:
                best_overall = (page, cluster_size, total)

            if center is not None and cluster_size >= SIFT_THRESHOLD:
                # center — координаты внутри INV_SCAN. Прибавляем смещение INV_SCAN.
                cx = int(center[0]) + INV_SCAN[0]
                cy = int(center[1]) + INV_SCAN[1]
                log(f"Аук: предмет найден на странице {page} в ({cx},{cy})",
                    self.window_id)
                # Вернуться в начало инвентаря (если листали)
                for _ in range(page - 1):
                    await self._swipe_inventory('up')
                return (cx, cy)

            # Не нашли на этой странице — свайпаем к следующей
            if page < SCAN_PAGES:
                await self._swipe_inventory('down')

        # Не нашли нигде — вернуться в начало
        for _ in range(SCAN_PAGES - 1):
            await self._swipe_inventory('up')
        log(f"Аук: предмет не найден ни на одной из {SCAN_PAGES} страниц. "
            f"Лучший результат: стр {best_overall[0]}, кластер {best_overall[1]}, "
            f"всего совпадений {best_overall[2]} (порог был {SIFT_THRESHOLD})",
            self.window_id, level="ERROR")
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

        # 2. Клик "Отмена лота"
        if not await self._cancel_lot():
            return 'error'

        # 3. Подождать анимацию и кликнуть ОК
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
