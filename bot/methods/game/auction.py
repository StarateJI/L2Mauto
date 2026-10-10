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

# pytesseract — ленивый импорт (не падает при import auction.py если
# Tesseract OCR бинарник не установлен на ПК). Импортируется только
# при вызове _ocr_price() или _is_status_prodano().
# Это чинит баг "пропадают кнопки профилей на других ПК" — если
# pytesseract не установлен, auction.py всё равно импортируется,
# и кнопки Dungeon/PvP/Auction появляются в GUI.
_pytesseract = None

def _get_pytesseract():
    """Ленивый импорт pytesseract. Возвращает модуль или None."""
    global _pytesseract
    if _pytesseract is not None:
        return _pytesseract
    try:
        import pytesseract as _pt
        _pt.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
        _pytesseract = _pt
        return _pytesseract
    except ImportError:
        log("Аук: pytesseract не установлен — OCR цен/статуса недоступен",
            level="WARNING")
        return None
    except Exception as e:
        log(f"Аук: pytesseract init failed: {e}", level="WARNING")
        return None

from bot.clogger import log
from bot.delays import DELAY_WAIT_AUCTION
from bot.methods.base import parseCBT
from bot.methods.game._base import GameAction

# ── mss singleton: открывается ОДИН раз, не на каждый захват ───────────────
# mss.mss() — класс в нижнем регистре (да, это легально в Python).
# На некоторых версиях mss модуль называется mss.mss, на других mss.MSS.
try:
    _sct = mss.mss()
except AttributeError:
    _sct = mss.MSS()

# ── Рабочий размер окна ───────────────────────────────────────────────────
# 960×540 — OCR 100% точность, 4 окна на 2560×1440 (2×2), меньше перекрытие
WORK_W, WORK_H = 960, 540
# 4 позиции для пачки из 4 окон на мониторе 2560×1440:
#   окно 1: (0, 40) — верх-лево
#   окно 2: (960, 40) — верх-право
#   окно 3: (0, 610) — низ-лево (540+40+30 title bar = 610)
#   окно 4: (960, 610) — низ-право
WORK_POSITIONS = [(0, 40), (960, 40), (0, 610), (960, 610)]
POSITION_TOLERANCE = 15
REST_W, REST_H = 400, 225  # вернуть обратно после работы

# ── UI кнопки (window-relative, 960×540) ─────────────────────────────────
# Координаты пересчитаны с 1280×720 → 960×540 (scale 0.75)
BTN_TAB_SELL = (212, 88)         # вкладка "Продажа" (было 282,117)
BTN_CANCEL_LOT = (650, 179)      # "Отмена лота" (было 867,238)
BTN_OK_CANCEL = (546, 383)       # "ОК" в окне подтверждения (было 728,510)
BTN_OK_PRICE = (563, 469)       # "ОК" в окне цены (было 750,625)
BTN_ADD = (547, 383)             # "Добавить" (было 729,510)
BTN_CLOSE = (914, 35)            # крестик (было 1218,46)
BTN_FIELD_PRICE = (432, 410)     # "Общая цена" (было 576,547)

# ── Зоны захвата (window-relative, 960×540) ──────────────────────────────
LOT_SEARCH = (56, 143, 60, 53)   # иконка лота (было 75,190,80,70)
INV_SCAN = (686, 130, 259, 318)  # инвентарь (было 915,173,345,424)
ZONE_PRICE = (651, 230, 60, 15)  # OCR "Текущая минимальная цена" (было 868,306,80,20)
ZONE_MAX_PRICE = (651, 255, 60, 15)  # OCR "Макс цена" — fallback если мин цена отсутствует
STATUS_ZONE = (598, 143, 105, 26) # статус лота (было 797,190,140,35)
OK_CHECK_ZONE = (525, 360, 45, 45) # оранжевая ОК (было 700,480,60,60)

# ── Калькулятор (3x4 numpad, 960×540) ────────────────────────────────────
# База: "5" на (584, 391) при 960×540 (было 778,521 при 1280×720)
# Шаг 30px (было 40px)
CALC_DIGITS = {
    '0': (644, 422),  # справа от '3' на том же ряду (сетка 3×3 + 0 в 4-й колонке)
    '1': (554, 422),  # было (738, 562)
    '2': (584, 422),  # было (778, 562)
    '3': (614, 422),  # было (819, 562)
    '4': (554, 391),  # было (738, 521)
    '5': (584, 391),  # было (778, 521)
    '6': (614, 391),  # было (819, 521)
    '7': (554, 361),  # было (738, 481)
    '8': (584, 361),  # было (778, 481)
    '9': (614, 361),  # было (819, 481)
}

# ── Свайп инвентаря ───────────────────────────────────────────────────────
INV_CX = 890      # X центра свайпа (было 1187, ×0.75 = 890)
SWIPE_STEP = 98   # px за один свайп (было 130, ×0.75 = 97.5 ≈ 98)

# ── Тайминги (секунды) — v5.3.1: увеличены для надёжности на лагающих ПК ──
T_CONFIRM_SETTLE = 3.0    # 2.0 → 3.0 — анимация окна подтверждения
T_ITEM_WINDOW = 4.0       # 3.0 → 4.0 — прогрузка окна цены после клика по предмету
T_PAGE_LOAD = 3.0         # 2.0 → 3.0 — пауза после свайпа страницы
LONG_PAUSE = 4.0          # 3.0 → 4.0 — после выставления лота
T_TAB_SELL_OPEN = 4.0     # 3.0 → 4.0 — пауза после клика по вкладке Продажа
T_AUCTION_CLOSE = 3.0     # 2.5 → 3.0 — пауза после клика по крестику (закрыть аук)
T_AFTER_ENERGY_OFF = 2.0  # пауза после выхода из энерго (до открытия меню)
T_AFTER_RESIZE = 1.5      # пауза после resize (до клика вкладка Продажа)

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
SCAN_PAGES = 2          # 2 страницы — не листаем слишком далеко
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

        # Очистка старых debug PNG от прошлых прогонов
        try:
            out_dir = os.path.dirname(os.path.abspath(__file__))
            for fname in os.listdir(out_dir):
                if fname.startswith(("au_", "cmp_")) and fname.endswith(".png"):
                    try:
                        os.remove(os.path.join(out_dir, fname))
                    except Exception:
                        pass
        except Exception:
            pass
        made = 0
        last_error: Optional[Exception] = None
        resize_done = False  # чтобы в finally знать — надо ли возвращать размер

        try:
            # 1. Разбудить окно — выйти из энерго.
            # Проблема (Zakamsk 17:15, v5.6.14): turn_off(ignore=True) делал
            # swipe, но swipe НЕ срабатывал на спящем окне → окно оставалось
            # в сне. Дальше бот кликал main_menu_gui → клик уходил в спящее
            # окно → НО пиксель случайно совпадал на чужом окне/рабочем столе
            # → бот думал «Аук: загрузился» → SIFT 0 → «список пуст».
            # Логи врали, скрины показывали что окно реально в сне.
            #
            # Решение: ЦИКЛ из 3 попыток turn_off с проверкой is_on() между.
            # Используем _wake_up из base.py — пробует turn_off до 3 раз
            # с проверкой is_on() после каждой попытки.
            woke = await self.profile._wake_up(max_attempts=3)
            if not woke:
                log("Аук: окно НЕ вышло из сна — пропускаю",
                    self.window_id, level="ERROR")
                try:
                    from gui.maingui import NedoGui
                    gui = NedoGui._instance if hasattr(NedoGui, '_instance') else None
                    if gui and hasattr(gui, '_skipped_windows'):
                        gui._skipped_windows.append(self.window_id)
                except Exception:
                    pass
                return False

            await asyncio.sleep(T_AFTER_ENERGY_OFF)

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

            # 4. Дождаться загрузки аукциона (пиксель auction_nalog, до 120с)
            if not await self._wait_auction_loaded(timeout=120):
                log("Чет пошло не так, не прогрузился аук =( Пробую выйти в меню", self.window_id)
                # Добавить в список пропущенных — вернёмся в конце прогона
                try:
                    from gui.maingui import NedoGui
                    gui = NedoGui._instance if hasattr(NedoGui, '_instance') else None
                    if gui and hasattr(gui, '_skipped_windows'):
                        gui._skipped_windows.append(self.window_id)
                        log(f"Аук: окно {self.window_id} добавлено в пропущенные", self.window_id)
                except Exception:
                    pass
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

            # Пауза после resize — окно должно перерисоваться в новом размере
            await asyncio.sleep(T_AFTER_RESIZE)

            # 6. Кликнуть вкладку "Продажа" + дождаться прогрузки
            await self._click(*BTN_TAB_SELL)
            await asyncio.sleep(T_TAB_SELL_OPEN)  # 3 сек — на лагающих ПК вкладка открывается
            log("Аук: вкладка Продажа открыта", self.window_id)
            # Фулл-скрин после открытия вкладки Продажа — видно что открылось
            self._take_fullscreen("au_after_tab_sell.png")

            # 7. Цикл по предметам
            for i in range(1, MAX_ITEMS + 1):
                log(f"Аук: предмет {i}/{MAX_ITEMS}", self.window_id)
                try:
                    result = await self._one_item_cycle()
                except Exception as e:
                    log(f"Аук: предмет {i} упал с исключением: {e!r} — пропускаю",
                        self.window_id, level="WARNING")
                    result = 'error'
                if result == 'ok':
                    made += 1
                    log(f"Аук: предмет {i} переставлен", self.window_id)
                elif result == 'empty':
                    log(f"Аук: лотов больше нет на странице (предмет {i})", self.window_id)
                    break
                else:  # 'error'
                    log(f"Аук: ошибка на предмете {i} — пропускаю, иду к следующему",
                        self.window_id, level="WARNING")
                    continue

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

            # 8a. Закрыть аук/меню ДО resize_back (кнопка 1218,46 в окне 1280x720,
            #     после resize_back окно станет 400x225 и клик не попадёт).
            #     Используем SetForegroundWindow для надёжности.
            #     Ждём T_AUCTION_CLOSE после клика — аук должен успеть закрыться.
            try:
                import ctypes
                hwnd_val = self.window_info[self.window_id].get("ID")
                if hwnd_val:
                    try:
                        ctypes.windll.user32.SetForegroundWindow(int(hwnd_val))
                    except Exception:
                        pass
                await self._click(*BTN_CLOSE)
                await asyncio.sleep(T_AUCTION_CLOSE)  # 2.5 сек — аук закрывается
                log("Аук: аук закрыт", self.window_id)
            except Exception as e:
                log(f"Аук: не удалось закрыть аук: {e}", self.window_id, level="WARNING")

            # 8b. Вернуть размер окна (если увеличивали) + ПРОВЕРИТЬ что стало 400x225
            #     Если resize_back не сработал — принудительно SetWindowPos ещё раз.
            #     После возврата — СВЕРНУТЬ окно (minimize), чтобы оно не мешало
            #     следующему окну в пачке (особенно при batch=1 для Auction).
            if resize_done:
                try:
                    await self._resize_back()
                    # Проверка что окно реально 400x225 и на СВОЕЙ позиции,
                    # а не зависло 1280x720 или не встало на чужое место.
                    import pygetwindow as gw
                    try:
                        win = gw.getWindowsWithTitle(
                            self.window_info[self.window_id]["Title"])[0]
                        saved = getattr(self.profile, '_au_saved_pos', None)
                        expected_pos = saved[:2] if saved else None
                        if win.width != REST_W or win.height != REST_H:
                            log(f"Аук: окно НЕ вернулось в {REST_W}x{REST_H}, "
                                f"сейчас {win.width}x{win.height} — принудительный "
                                f"SetWindowPos",
                                self.window_id, level="WARNING")
                            import ctypes
                            SWP_NOZORDER = 0x0004
                            SWP_NOACTIVATE = 0x0010
                            if saved:
                                left, top, w, h = saved
                            else:
                                left, top, w, h = win.left, win.top, REST_W, REST_H
                            ctypes.windll.user32.SetWindowPos(
                                ctypes.c_void_p(int(win._hWnd)), None,
                                left, top, REST_W, REST_H,
                                SWP_NOZORDER | SWP_NOACTIVATE,
                            )
                            await asyncio.sleep(0.5)
                            log(f"Аук: принудительный resize завершён", self.window_id)
                        elif expected_pos and (win.left, win.top) != expected_pos:
                            # Размер 400x225 но позиция не совпала — FranklinSaint bug
                            log(f"Аук: окно на чужой позиции ({win.left},{win.top}), "
                                f"ожидалась {expected_pos} — двигаю на свою",
                                self.window_id, level="WARNING")
                            import ctypes
                            SWP_NOSIZE = 0x0001
                            SWP_NOZORDER = 0x0004
                            SWP_NOACTIVATE = 0x0010
                            ctypes.windll.user32.SetWindowPos(
                                ctypes.c_void_p(int(win._hWnd)), None,
                                expected_pos[0], expected_pos[1], 0, 0,
                                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
                            )
                            await asyncio.sleep(0.5)
                            log(f"Аук: окно передвинуто на {expected_pos}",
                                self.window_id)
                    except Exception as e:
                        log(f"Аук: проверка размера не удалась: {e}",
                            self.window_id, level="WARNING")
                except Exception as e:
                    log(f"Аук: не удалось вернуть размер окна: {e}",
                        self.window_id, level="WARNING")

            # 8c. Включить энергорежим — 1 попытка, без 3×8сек ожидания.
            try:
                if not await self.profile.energo.is_on():
                    await self.profile.energo.turn_on()
                    await asyncio.sleep(2.0)
                if await self.profile.energo.is_on():
                    log("Аук: окно уложено спать", self.window_id)
                else:
                    log("Аук: энерго не включился (не критично)", self.window_id, level="WARNING")
            except Exception as e:
                log(f"Аук: не удалось включить энерго: {e}",
                    self.window_id, level="WARNING")

            # 8d. ФУЛЛ-СКРИН в конце прогона — видно реальное состояние ВСЕХ окон.
            #     Логи могут врать (бот пишет «окно возвращено» а по факту нет),
            #     а скриншот показывает правду. Закоммитится в GitHub через log_uploader.
            try:
                self._take_fullscreen("au_final_fullscreen.png")
            except Exception:
                pass

            # Примечание: minimize (сворачивание в трей) убрано — пользователь
            # не хочет чтобы окно пропадало из вида. _resize_back через
            # WM_SYSCOMMAND SC_RESTORE уже вернул окно в рабочее положение.

            # 9. Уведомление в TG
            try:
                if made > 0:
                    self.profile.notify("info", f"Аук: переставлено лотов {made}")
                    log(f"Аук: готово, переставлено {made}", self.window_id)
                elif last_error is not None:
                    self.profile.notify("error",
                                      f"Аук: УПАЛ с ошибкой: {last_error}")
                    try:
                        self.profile.notify_screenshot(
                            f"Аук упал: {last_error}", level="error")
                    except Exception:
                        pass
                else:
                    # Не ошибка — просто нет лотов для перестановки (INFO не ERROR)
                    self.profile.notify("info",
                                      "Аук: лотов для перестановки не найдено")
                    log("Аук: нечего переставлять (все лоты в «Продаётся» "
                        "или список пуст)", self.window_id, level="INFO")
            except Exception as e:
                log(f"Аук: не удалось отправить TG-уведомление: {e}",
                    self.window_id, level="WARNING")

            # 10. Загрузить логи + debug PNG в GitHub (ветка bot-logs)
            #     В отдельном потоке — НЕ блокирует finally (не создаёт паузы).
            try:
                import threading
                from bot.log_uploader import upload_run_logs
                error_str = str(last_error) if last_error else None
                t = threading.Thread(
                    target=upload_run_logs,
                    args=(self.window_id,),
                    kwargs={"made": made, "error": error_str},
                    daemon=True
                )
                t.start()
                log(f"Аук: log_uploader запущен в фоне", self.window_id, level="DEBUG")
            except Exception as e:
                log(f"Аук: log_uploader не сработал: {e}",
                    self.window_id, level="WARNING")

        return made > 0

    # ──────────────────────────────────────────────────────────────────────
    # РАЗМЕР ОКНА
    # ──────────────────────────────────────────────────────────────────────
    def _click_titlebar_button(self, hwnd: int, button: str) -> bool:
        """
        Простой реальный клик мышью по кнопке title bar через pyautogui
        (как просил пользователь — обычный клик, не API-аналоги).

        pyautogui.click(x, y) делает SetCursorPos + SendInput — это
        работает с любым окном, доказано в _find_item (клик по предмету).

        button: 'maximize' | 'minimize' | 'close'
        (restore = повторный клик maximize — toggle)
        """
        import pyautogui
        import pygetwindow as gw

        try:
            win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
            # Координаты title bar:
            # Стандартный Windows title bar = 30px высота.
            # Кнопки справа: close (правый край), maximize/minimize (левее).
            # Ширина кнопки ~45px.
            #
            # Для CEF-окна Lineage2M title bar может быть ~30px.
            # Кнопка maximize ≈ 45-60px от правого края, ~15px от верха.
            title_h = 30
            btn_w = 45

            btn_order = ['close', 'maximize', 'minimize']
            idx = btn_order.index(button) if button in btn_order else 1

            screen_x = win.right - (idx + 1) * btn_w + btn_w // 2
            screen_y = win.top + title_h // 2

            log(f"Аук: клик по title bar '{button}' на ({screen_x},{screen_y}) "
                f"окно=({win.left},{win.top}) {win.width}x{win.height}",
                self.window_id)

            # Дебаг-скриншот title bar — видно окно с кнопками до клика
            try:
                import mss as _mss
                _sct_local = _mss.mss()
                mon = {"left": win.left, "top": win.top,
                       "width": win.width, "height": 40}
                _shot = _sct_local.grab(mon)
                import numpy as _np
                import cv2 as _cv2
                _arr = _np.array(_shot)
                _bgr = _cv2.cvtColor(_arr, _cv2.COLOR_BGRA2BGR)
                _out = os.path.dirname(os.path.abspath(__file__))
                _cv2.imwrite(os.path.join(_out, "au_titlebar_before_click.png"), _bgr)
                _sct_local.close()
            except Exception:
                pass

            # pyautogui.moveTo + click — реальный клик через SendInput
            pyautogui.moveTo(screen_x, screen_y, duration=0.1)
            pyautogui.click(screen_x, screen_y)
            import time as _t
            _t.sleep(0.3)
            return True
        except Exception as e:
            log(f"Аук: _click_titlebar_button({button}) не сработал: {e}",
                self.window_id, level="WARNING")
            return False

    async def _resize_work(self) -> bool:
        """
        Развернуть окно на ФУЛЛСКРИН — КЛИК по средней кнопке title bar
        (как пользователь просил, не 'аналоги' через ShowWindow/SYSCOMMAND).

        Scale (real_w/960, real_h/540) сохраняется в self._au_scale —
        все координаты в _click/_grab масштабируются.
        """
        import ctypes
        import pygetwindow as gw
        from ctypes import wintypes

        # Сохраняем исходную позицию ДО maximize (один раз за цикл)
        if not hasattr(self.profile, '_au_saved_pos') or self.profile._au_saved_pos is None:
            try:
                win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
                self.profile._au_saved_pos = (win.left, win.top, win.width, win.height)
                log(f"Аук: сохранил позицию окна до maximize: "
                    f"({win.left},{win.top}) {win.width}x{win.height}",
                    self.window_id)
            except Exception as e:
                log(f"Аук: не удалось сохранить позицию: {e}",
                    self.window_id, level="WARNING")

        u = ctypes.windll.user32
        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        MONITOR_DEFAULTTOPRIMARY = 1

        try:
            win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
            hwnd = win._hWnd

            # 1) Если уже maximize — restore (toggle)
            if win.isMaximized:
                self._click_titlebar_button(hwnd, 'restore')
                await asyncio.sleep(0.4)

            # 2) КЛИК по средней кнопке (maximize) в title bar
            self._ensure_foreground()
            ok = self._click_titlebar_button(hwnd, 'maximize')
            await asyncio.sleep(T_AFTER_RESIZE)

            # 3) Проверить размер. Если не maximize — fallback на SetWindowPos
            win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
            if not win.isMaximized:
                log(f"Аук: клик по maximize не сработал, fallback на SetWindowPos",
                    self.window_id, level="WARNING")
                try:
                    MONITORINFO = type('MONITORINFO', (ctypes.Structure,), {
                        '_fields_': [
                            ('cbSize', ctypes.c_uint32),
                            ('rcMonitor', wintypes.RECT),
                            ('rcWork', wintypes.RECT),
                            ('dwFlags', ctypes.c_uint32),
                        ],
                    })
                    hmon = u.MonitorFromWindow(
                        wintypes.HWND(hwnd),
                        ctypes.c_uint32(MONITOR_DEFAULTTOPRIMARY),
                    )
                    mi = MONITORINFO()
                    mi.cbSize = ctypes.sizeof(MONITORINFO)
                    u.GetMonitorInfoW(wintypes.HMONITOR(hmon), ctypes.byref(mi))
                    # rcWork — рабочая область (без taskbar), НЕ rcMonitor!
                    # rcMonitor = весь экран включая taskbar.
                    # Используем rcWork чтобы окно не уезжало за экран.
                    mx, my = mi.rcWork.left, mi.rcWork.top
                    mw = mi.rcWork.right - mi.rcWork.left
                    mh = mi.rcWork.bottom - mi.rcWork.top
                    u.SetWindowPos(
                        wintypes.HWND(hwnd), None,
                        mx, my, mw, mh,
                        SWP_NOZORDER | SWP_NOACTIVATE,
                    )
                    await asyncio.sleep(T_AFTER_RESIZE)
                    log(f"Аук: SetWindowPos до {mw}x{mh} на ({mx},{my}) — рабочая область",
                        self.window_id)
                except Exception as e:
                    log(f"Аук: SetWindowPos fallback не сработал: {e}",
                        self.window_id, level="ERROR")

            # Перечитать размер окна после maximize
            win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
            real_w, real_h = win.width, win.height
            self.window_info[self.window_id]["Position"] = (win.left, win.top)
            self.window_info[self.window_id]["Width"] = real_w
            self.window_info[self.window_id]["Height"] = real_h
            self.window_info[self.window_id]["Size"] = f"{real_w}x{real_h}"

            sx = real_w / WORK_W
            sy = real_h / WORK_H
            self._au_scale = (sx, sy)
            log(f"Аук: окно maximize {real_w}x{real_h}, scale=({sx:.2f},{sy:.2f})",
                self.window_id)

            if abs(sx - sy) > 0.15:
                log(f"Аук: ВНИМАНИЕ — масштаб неравномерный (sx={sx:.2f}, sy={sy:.2f}). "
                    f"Монитор не 16:9? Координаты могут съехать.",
                    self.window_id, level="WARNING")
            return True
        except Exception as e:
            log(f"Аук: maximize не удался: {e}", self.window_id, level="WARNING")
            self._au_scale = (1.0, 1.0)
            return False

    async def _resize_back(self) -> None:
        """
        Вернуть окно в исходное положение — КЛИК по средней кнопке title bar
        (toggle restore). Если не сработало — SetWindowPos до сохранённой
        позиции. Сбрасывает self._au_scale = (1.0, 1.0).
        """
        import ctypes
        import pygetwindow as gw
        from ctypes import wintypes

        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        u = ctypes.windll.user32

        saved = getattr(self.profile, '_au_saved_pos', None)
        if saved:
            left, top, w, h = saved
            self.profile._au_saved_pos = None
        else:
            left, top, w, h = 0, 40, REST_W, REST_H

        try:
            win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
            hwnd = win._hWnd

            # 1) Клик по средней кнопке (toggle restore) если окно maximize
            if win.isMaximized:
                self._ensure_foreground()
                # maximize кнопка в toggle режиме: клик = restore
                self._click_titlebar_button(hwnd, 'maximize')
                await asyncio.sleep(0.5)

            # 2) Проверить — если restore не вернул сохранённый размер, SetWindowPos
            win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
            if win.width != w or win.height != h or (win.left, win.top) != (left, top):
                u.SetWindowPos(
                    wintypes.HWND(hwnd), None,
                    left, top, w, h,
                    SWP_NOZORDER | SWP_NOACTIVATE,
                )
                await asyncio.sleep(0.4)

            # Перечитать win (мог сместиться)
            win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
            self.window_info[self.window_id]["Position"] = (win.left, win.top)
            self.window_info[self.window_id]["Width"] = win.width
            self.window_info[self.window_id]["Height"] = win.height
            self.window_info[self.window_id]["Size"] = f"{win.width}x{win.height}"
            log(f"Аук: окно возвращено {win.width}x{win.height} на ({win.left},{win.top})",
                self.window_id)
        except Exception as e:
            log(f"Аук: не удалось вернуть размер окна: {e}",
                self.window_id, level="WARNING")

        # Сброс scale — координаты снова 1:1
        self._au_scale = (1.0, 1.0)

    # ──────────────────────────────────────────────────────────────────────
    # ОЖИДАНИЕ ЗАГРУЗКИ АУКЦИОНА
    # ──────────────────────────────────────────────────────────────────────
    async def _wait_auction_loaded(self, timeout: int = 120) -> bool:
        """
        Ждать пока аукцион загрузится. До timeout секунд.
        Проверяет пиксель auction_nalog (что аукцион прогрузился).
        Если на экране «Поиск информации» — ждём, это нормально.
        Логирует прогресс каждые 10 сек.
        """
        xy, rgb = parseCBT("auction_nalog", profile=self.profile)
        if xy is None:
            log("Аук: auction_nalog не найден в CBT", self.window_id, level="ERROR")
            return False

        deadline = time.monotonic() + timeout
        last_log = time.monotonic()
        while time.monotonic() < deadline:
            try:
                if await self.profile.check_pixel(xy, rgb, timeout=1, thr=4):
                    return True
            except Exception:
                pass
            # Лог прогресса каждые 10 сек
            now = time.monotonic()
            if now - last_log >= 10:
                remaining = int(deadline - now)
                log(f"Аук: жду загрузки... осталось {remaining}с", self.window_id)
                last_log = now
            await asyncio.sleep(2)
        log(f"Аук: не прогрузился за {timeout} сек (Поиск информации?) — пропускаю",
            self.window_id, level="WARNING")
        return False

    # ──────────────────────────────────────────────────────────────────────
    # ЗАХВАТ ЭКРАНА (window-relative)
    # ──────────────────────────────────────────────────────────────────────
    def _grab(self, rect: Tuple[int, int, int, int]) -> np.ndarray:
        """
        Захват зоны rect=(x, y, w, h) в window-relative координатах (960×540 base).
        Возвращает BGR ndarray РАЗМЕРОМ (h, w) — как будто окно 960×540,
        независимо от реального размера (после maximize окно может быть
        1920×1080 — тогда зона захватывается с scale и resize'ится к base).
        """
        win = self.window_info[self.window_id]
        wx, wy = win["Position"]
        x, y, w, h = rect
        # Scale: если окно maximize (не 960×540), масштабируем координаты
        sx, sy = getattr(self, '_au_scale', (1.0, 1.0))
        monitor = {
            "left": int(wx + x * sx),
            "top": int(wy + y * sy),
            "width": int(w * sx),
            "height": int(h * sy),
        }
        try:
            shot = _sct.grab(monitor)
        except Exception as e:
            if 'srcdc' in str(e) or 'memdc' in str(e):
                try:
                    local_sct = mss.mss()
                except AttributeError:
                    local_sct = mss.MSS()
                shot = local_sct.grab(monitor)
                try:
                    local_sct.close()
                except Exception:
                    pass
            else:
                raise
        arr = np.array(shot)  # BGRA, размер (h*sy, w*sx)
        bgr = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
        # Если окно не 960×540 — resize к base размеру (h, w)
        if sx != 1.0 or sy != 1.0:
            bgr = cv2.resize(bgr, (w, h), interpolation=cv2.INTER_AREA)
        return bgr

    async def _save_debug(self, name: str, img: np.ndarray) -> None:
        """Сохранить PNG рядом с auction.py для отладки."""
        try:
            out_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(out_dir, name)
            cv2.imwrite(path, img)
            log(f"Аук: сохранён {name}", self.window_id)
        except Exception as e:
            log(f"Аук: не удалось сохранить {name}: {e}", self.window_id, level="WARNING")

    def _take_fullscreen(self, name: str = "au_fullscreen.png") -> None:
        """
        Сделать скриншот ВСЕГО монитора (не отдельного окна) и сохранить
        рядом с auction.py. Используется для диагностики — видно все окна
        в момент вызова, не только текущее.

        Использует singleton _sct (тот же что и _grab) — НЕ создаёт новый mss.
        Синхронный (быстрый ~50ms) — не блокирует event loop надолго.
        """
        try:
            out_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(out_dir, name)
            # Берём главный монитор (обычно 2560×1440)
            # monitors[0] = все мониторы вместе (virtual screen)
            # monitors[1] = первый реальный монитор
            monitors = _sct.monitors
            if len(monitors) > 1:
                monitor = monitors[1]
            else:
                monitor = monitors[0]
            shot = _sct.grab(monitor)
            arr = np.array(shot)  # BGRA
            img = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
            cv2.imwrite(path, img)
            log(f"Аук: сохранён фулл-скрин {name} ({monitor['width']}x{monitor['height']})",
                self.window_id)
        except Exception as e:
            log(f"Аук: не удалось сохранить фулл-скрин {name}: {e}",
                self.window_id, level="WARNING")

    # ──────────────────────────────────────────────────────────────────────
    # FOREGROUND — гарантия что окно на переднем плане
    # ──────────────────────────────────────────────────────────────────────
    def _ensure_foreground(self) -> bool:
        """
        Принудительно вывести окно на передний план и проверить результат.

        Проблема: SetForegroundWindow в Windows не работает если текущий
        foreground принадлежит другому процессу (или окно перекрыто).
        Решение — трюк с AttachThreadInput: прикрепляем input-поток текущего
        foreground окна к нашему, тогда SetForegroundWindow срабатывает.

        Возвращает True если после всех попыток наше окно стало foreground.
        """
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd_val = self.window_info[self.window_id].get("ID")
            if not hwnd_val:
                return False
            hwnd = int(hwnd_val)

            # Если уже foreground — выходим быстро
            fg_now = user32.GetForegroundWindow()
            if fg_now == hwnd:
                return True

            # Трюк с AttachThreadInput: позволяет «украсть» foreground
            fg_thread = user32.GetWindowThreadProcessId(fg_now, None)
            my_thread = user32.GetCurrentThreadId()

            attached = False
            if fg_thread and fg_thread != my_thread:
                # Прикрепляем поток foreground окна к нашему
                if user32.AttachThreadInput(my_thread, fg_thread, True):
                    attached = True

            # Пробуем несколько раз — иногда нужно с задержкой
            ok = False
            for _ in range(3):
                # Альт-трюк: нажать+отпустить Alt «снимает» foreground lock
                user32.keybd_event(0x12, 0, 0, 0)        # VK_MENU down
                user32.keybd_event(0x12, 0, 0x0002, 0)   # VK_MENU up (KEYEVENTF_KEYUP)
                # Теперь SetForegroundWindow должен сработать
                user32.SetForegroundWindow(hwnd)
                # Если окно свёрнуто — восстановить
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                # Небольшая задержка
                import time as _t
                _t.sleep(0.05)
                if user32.GetForegroundWindow() == hwnd:
                    ok = True
                    break
                _t.sleep(0.05)

            # Открепляем потоки
            if attached:
                user32.AttachThreadInput(my_thread, fg_thread, False)

            if not ok:
                log(f"Аук: _ensure_foreground НЕ смог вывести окно на передний план "
                    f"(hwnd={hwnd})", self.window_id, level="WARNING")
            return ok
        except Exception as e:
            log(f"Аук: _ensure_foreground exception: {e}", self.window_id,
                level="WARNING")
            return False

    # ──────────────────────────────────────────────────────────────────────
    # КЛИКИ
    # ──────────────────────────────────────────────────────────────────────
    async def _click(self, x: int, y: int) -> None:
        """Клик по window-relative координатам (960×540 base) через очередь мыши.
        Сначала _ensure_foreground — гарантия что клик уйдёт в правильное окно.
        Если окно maximize (не 960×540) — координаты масштабируются."""
        self._ensure_foreground()
        sx, sy = getattr(self, '_au_scale', (1.0, 1.0))
        await self.mouse.click(self.window_info, int(x * sx), int(y * sy))

    async def _click_and_verify(self, x: int, y: int, label: str = "",
                               verify_zone: Optional[Tuple[int, int, int, int]] = None) -> bool:
        """
        Клик + проверка результата. Делает скрин до и после клика,
        сравнивает — если экран не изменился, клик не прошёл.

        verify_zone: зона для сравнения (если None — весь INV_SCAN).
        Возвращает True если экран изменился (клик сработал).

        Сохраняет скрины:
          au_before_{label}.png — до клика
          au_after_{label}.png — после клика
        """
        zone = verify_zone or INV_SCAN
        before = self._grab(zone)
        await self._click(x, y)
        await asyncio.sleep(2.0)
        after = self._grab(zone)
        # Сравнение: насколько изменились картинки
        diff = cv2.absdiff(before, after)
        changed_pixels = int(np.sum(diff > 30))  # пиксели изменившиеся >30
        total = before.shape[0] * before.shape[1] * before.shape[2]
        change_ratio = changed_pixels / total
        # Сохраняем для диагностики
        safe_label = label.replace(" ", "_").lower()
        await self._save_debug(f"au_before_{safe_label}.png", before)
        await self._save_debug(f"au_after_{safe_label}.png", after)
        if change_ratio > 0.01:  # >1% пикселей изменилось
            log(f"Аук: клик '{label}' сработал (изменение {change_ratio:.1%})",
                self.window_id)
            return True
        else:
            log(f"Аук: клик '{label}' НЕ сработал (изменение {change_ratio:.1%}) — "
                f"возможно окно перекрыто", self.window_id, level="WARNING")
            return False

    async def _swipe_inventory(self, direction: str) -> None:
        """
        Свайп инвентаря. direction='down' — следующая страница, 'up' — назад.

        Сначала _ensure_foreground — иначе при перекрытии окон свайп уходит
        в чужое окно (поэтому в логе страницы 1 и 2 выглядят одинаково:
        иконка на одних и тех же координатах).

        Генерирует ~20 промежуточных точек между start и end — swipe
        получается медленным и плавным. Старый вариант с 2 точками делал
        FLICK (быстрый резкий жест) и эластичный скролл Lineage2M улетал
        далеко за пределы («сразу в самый низ»).
        """
        self._ensure_foreground()
        # Scale для maximize — свайп тоже должен масштабироваться
        sx, sy = getattr(self, '_au_scale', (1.0, 1.0))
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
            # Масштабируем координаты под реальный размер окна
            points.append((int(cx * sx), int(y * sy)))

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
        Возвращает True если ХОТЯ БЫ ОДИН из 3 методов нашёл признак «Продаётся»:
          1. OCR: слово «продаётся»/«продается»/«прода» в зоне статуса
          2. Цвет: много зелёных пикселей (статус «Продаётся» рисуется зелёным)
          3. Цвет: мало тёмных пикселей (статус-таймер обычно серый, не яркий)

        Такие лоты НЕ трогаем — иначе вечный цикл.
        Если хотя бы один метод сработал → возвращаем True (лучше пропустить).
        """
        try:
            img = self._grab(STATUS_ZONE)
            # Сохраняем для отладки
            import cv2
            import os
            debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "au_status.png")
            cv2.imwrite(debug_path, img)

            # ── Метод 1: Tesseract (основной) ────────────────────────────
            h, w = img.shape[:2]
            big = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
            pt = _get_pytesseract()
            text = ""
            if pt is not None:
                text = pt.image_to_string(gray, lang="rus+eng", config="--psm 7").strip().lower()
                log(f"Аук: статус лота Tesseract: '{text}'", self.window_id, level="DEBUG")
                ocr_match = any(kw in text for kw in
                                ("продаёт", "продает", "продаю", "продажа",
                                 "продаё", "продае", "прода", "продаетс"))
                if ocr_match:
                    log("Аук: статус = «Продаётся» (Tesseract)", self.window_id)
                    return True

            # ── Метод 2: зелёные пиксели ─────────────────────────────────
            # В Lineage2M статус «Продаётся» часто подсвечен зелёным.
            # HSV: H в [40..90] (зелёный), S>50, V>100
            try:
                hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
                # Зелёный: H 40..90, S 50..255, V 100..255
                lower = np.array([40, 50, 100])
                upper = np.array([90, 255, 255])
                green_mask = cv2.inRange(hsv, lower, upper)
                green_count = int(np.sum(green_mask > 0))
                total_pixels = img.shape[0] * img.shape[1]
                green_ratio = green_count / max(total_pixels, 1)
                log(f"Аук: статус зелёных пикселей: {green_count} "
                    f"({green_ratio:.2%})", self.window_id, level="DEBUG")
                # Если >5% пикселей зелёные — почти наверняка «Продаётся»
                if green_ratio > 0.05:
                    log(f"Аук: статус = «Продаётся» (зелёный метод, "
                        f"{green_ratio:.1%})", self.window_id)
                    return True
            except Exception as e:
                log(f"Аук: green check failed: {e}", self.window_id, level="DEBUG")

            # ── Метод 3: OCR вернул что-то похожее на таймер? ───────────────
            # Если OCR вернул цифры + «д.»/«ч.» — это таймер, не «Продаётся».
            # Если OCR вернул текст похожий на «прод...» — это «Продаётся».
            # Если OCR вернул явный мусор ('=', 'a if', 'at "24.34...') —
            # это НЕ «Продаётся» (мусор = OCR не смог прочитать таймер).
            # Раньше тут было «вернуть True при пустом OCR — вдруг Продаётся»,
            # но это вызывало ЛОЖНЫЕ пропуски: бот не переставлял рабочие лоты.
            # Правильно: мусор/пусто → НЕ «Продаётся» → возвращаем False.
            if not text or text in ("", "=", "-", "]"):
                # OCR пустой/мусор — не можем сказать что это «Продаётся».
                # Возвращаем False — пусть бот работает (снимает лот).
                log(f"Аук: OCR вернул пусто/мусор ('{text}') — НЕ «Продаётся», "
                    f"работаю дальше (снимаю лот)", self.window_id, level="DEBUG")
                return False

            # ── Все 3 метода: не «Продаётся», есть таймер/текст ─────────────
            return False

        except Exception as e:
            log(f"Аук: OCR статуса не удался: {e} — НЕ ТРОГАЮ (безопасно)",
                self.window_id, level="WARNING")
            return True  # Если проверка упала — лучше не трогать

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
    def _ocr_price_from_zone(self, zone: Tuple[int, int, int, int],
                              label: str = "мин") -> Optional[int]:
        """
        OCR цены из указанной зоны.
        label — 'мин' или 'макс' для логирования.
        Возвращает int или None.
        """
        try:
            img = self._grab(zone)
            h, w = img.shape[:2]
            big = cv2.resize(img, (w * 4, h * 4), interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
            inv = cv2.bitwise_not(gray)
            _, thr = cv2.threshold(inv, 128, 255, cv2.THRESH_BINARY)
            pt = _get_pytesseract()
            if pt is None:
                return None
            text = pt.image_to_string(
                thr,
                config="--psm 7 -c tessedit_char_whitelist=0123456789",
            ).strip()
            digits = text.replace(",", "").replace(" ", "").replace(".", "")
            digits = digits.lstrip('0') or '0'
            if not digits.isdigit():
                log(f"Аук: OCR {label} цена вернула не цифры: '{text}'",
                    self.window_id, level="WARNING")
                return None
            price = int(digits)
            log(f"Аук: OCR {label} цена = {price} (raw='{text}')", self.window_id)
            return price
        except Exception as e:
            log(f"Аук: OCR {label} цена не удалась: {e}", self.window_id, level="WARNING")
            return None

    def _ocr_price(self) -> Optional[int]:
        """OCR 'Текущая минимальная цена' из ZONE_PRICE."""
        return self._ocr_price_from_zone(ZONE_PRICE, "мин")

    def _ocr_max_price(self) -> Optional[int]:
        """OCR 'Макс цена' из ZONE_MAX_PRICE. Fallback если мин цена отсутствует."""
        return self._ocr_price_from_zone(ZONE_MAX_PRICE, "макс")

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

    def _find_red_dots(self, img: np.ndarray) -> list:
        """
        Найти красные точки «новое» в кадре инвентаря.
        Точный цвет точки в Lineage2M: BGR=(0, 102, 255) = R=255, G=102, B=0.
        Это яркий красно-оранжевый круг в правом верхнем углу ячейки.
        Фильтр: R>200, G 70-130, B<30 — точный цвет красной точки.
        """
        try:
            b, g, r = cv2.split(img)
            # R>200, G=70-130, B<30 — точный цвет красной точки Lineage2M
            mask = (r > 200) & (g > 70) & (g < 130) & (b < 30)
            mask_u8 = (mask.astype(np.uint8)) * 255
            # Морфология — объединить пиксели в кластер
            kernel = np.ones((3, 3), np.uint8)
            mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, kernel)
            num, labels, stats, centroids = cv2.connectedComponentsWithStats(mask_u8)
            dots = []
            for i in range(1, num):  # 0 = фон
                area = stats[i, cv2.CC_STAT_AREA]
                if area < 15:  # слишком маленький — шум (было 5)
                    continue
                cx = int(centroids[i][0])
                cy = int(centroids[i][1])
                # Игнорировать точки в заголовке инвентаря (y < 30) — это шум
                if cy < 30:
                    continue
                dots.append((cx, cy))
            return dots
        except Exception as e:
            log(f"Аук: _find_red_dots exception: {e}", self.window_id, level="WARNING")
            return []

    async def _find_item(self, sample_gray: np.ndarray) -> Optional[Tuple[int, int]]:
        """
        Искать предмет в инвентаре ТОЛЬКО через YOLOv8 + ORB.
        matchTemplate УБРАН — был ненадёжным.
        Красная точка — подтверждение что предмет снят с продажи.
        """
        best_result = None

        try:
            from bot.yolo_detector import find_item as yolo_find_item
            yolo_available = True
        except Exception:
            yolo_available = False
            log("Аук: YOLOv8 недоступен — pip install ultralytics + "
                "bot/models/item_detector.pt", self.window_id, level="ERROR")

        if not yolo_available:
            return None

        # Сначала листаем ВНИЗ — предмет падает в конец инвентаря
        for page in range(1, SCAN_PAGES + 1):
            log(f"Аук: сканирую страницу {page}/{SCAN_PAGES} (вниз)", self.window_id)
            img = self._grab(INV_SCAN)
            await self._save_debug(f"au_page_{page}.png", img)

            # matchTemplate multi-scale
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            best_loc, best_score, _, _ = self._match_template(sample_gray, img_gray)
            if best_loc is not None:
                cx, cy = best_loc
                win_cx = cx + INV_SCAN[0]
                win_cy = cy + INV_SCAN[1]
                log(f"Аук: matchTemplate НАШЁЛ — стр {page} ({cx},{cy}) score={best_score:.3f}",
                    self.window_id)
                best_result = (win_cx, win_cy, best_score, page)
                break
            else:
                log(f"Аук: matchTemplate не нашёл на стр {page} (score={best_score:.3f})",
                    self.window_id, level="DEBUG")

            if page < SCAN_PAGES:
                await self._swipe_inventory('down')

        # Если не нашли внизу — листаем ВВЕРХ (второй предмет может быть выше)
        if best_result is None:
            for _ in range(SCAN_PAGES):
                await self._swipe_inventory('up')
            await asyncio.sleep(0.5)
            await self._swipe_inventory('up')
            await asyncio.sleep(0.5)
            log(f"Аук: сканирую вверх (стр -1)", self.window_id)
            img = self._grab(INV_SCAN)
            await self._save_debug("au_page_up.png", img)
            img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            best_loc, best_score, _, _ = self._match_template(sample_gray, img_gray)
            if best_loc is not None:
                cx, cy = best_loc
                win_cx = cx + INV_SCAN[0]
                win_cy = cy + INV_SCAN[1]
                log(f"Аук: matchTemplate НАШЁЛ вверх ({cx},{cy}) score={best_score:.3f}",
                    self.window_id)
                best_result = (win_cx, win_cy, best_score, -1)

        # Возвращаемся в начало
        if best_result is not None and best_result[3] > 0:
            for _ in range(best_result[3]):
                await self._swipe_inventory('up')
            await asyncio.sleep(1.0)
        elif best_result is not None and best_result[3] == -1:
            await self._swipe_inventory('down')
            await asyncio.sleep(1.0)

        if best_result is not None:
            log(f"Аук: предмет найден! стр {best_result[3]} "
                f"({best_result[0]},{best_result[1]}) score={best_result[2]:.3f}",
                self.window_id)
            return (best_result[0], best_result[1])

        log(f"Аук: предмет не найден (ни внизу, ни вверху)", self.window_id, level="ERROR")
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

        # Считаем SIFT keypoints образца — если 0, значит строка пустая
        # (нет иконки/лота на продаже). Это НЕ ошибка — просто нечего переставлять.
        kp_count = 0
        try:
            sift = cv2.SIFT_create()
            kp_sample, _ = sift.detectAndCompute(cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY), None)
            kp_count = len(kp_sample) if kp_sample else 0
            log(f"Аук: SIFT образец (лот): {kp_count} точек", self.window_id)
        except Exception:
            pass

        sample_gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)

        # 2. Защита от вечного цикла: если первый лот в статусе «Продаётся» —
        # значит он только что выставлен, снимать/переставлять его НЕ НАДО.
        # Пропускаем. Обёрнуто в try/except — RapidOCR может крашнуть процесс
        # при первом вызове (скачивание моделей).
        try:
            if self._is_status_prodano():
                log("Аук: первый лот в статусе «Продаётся» — пропускаю",
                    self.window_id)
                return 'empty'
        except Exception as e:
            log(f"Аук: _is_status_prodano упал: {e} — продолжаю",
                self.window_id, level="WARNING")

        # 2b. Если образец пустой (0 SIFT точек) и статус не «Продаётся» —
        # значит строка лота пустая (нет лотов на продаже вообще).
        # Это НЕ ошибка — просто нечего переставлять. Возвращаем 'empty'.
        if kp_count == 0:
            log("Аук: образец лота пустой (нет иконки) — список лотов пуст. "
                "Завершаю прогон (не ошибка).",
                self.window_id, level="INFO")
            return 'empty'

        # 3. Клик "Отмена лота"
        if not await self._cancel_lot():
            # Окно подтверждения НЕ появилось после 2 кликов по «Отмена лота».
            # Это значит список лотов ПУСТОЙ — кнопка серая/неактивная, клик
            # по ней ничего не делает. Это НЕ ошибка — просто нечего снимать.
            # Раньше тут было return 'error' → бот стопал весь прогон.
            # Правильно: return 'empty' — завершить как «нечего переставлять».
            log("Аук: окно подтверждения не появилось — список лотов пуст "
                "(кнопка «Отмена» серая). Завершаю прогон (не ошибка).",
                self.window_id, level="INFO")
            return 'empty'

        # 4. Подождать анимацию и кликнуть ОК
        await asyncio.sleep(T_CONFIRM_SETTLE)
        if not await self._click_ok_cancel():
            # Окно подтверждения не закрылось — попробуем закрыть вручную
            await self._click(*BTN_CLOSE)
            return 'error'

        log("Аук: лот снят, предмет упал в конец инвентаря", self.window_id)

        # 4. Найти предмет в инвентаре (YOLOv8, 5 страниц)
        await self._save_debug("au_after_click.png", self._grab(INV_SCAN))
        log("Аук: ищу предмет (YOLOv8)...", self.window_id)

        try:
            item_pos = await self._find_item(sample_gray)
        except Exception as e:
            log(f"Аук: _find_item упал: {e} — пропускаю предмет",
                self.window_id, level="ERROR")
            return 'error'
        if item_pos is None:
            self.profile.notify("error",
                               f"Аук: ПРЕДМЕТ НЕ НАЙДЕН (SIFT, {SCAN_PAGES} стр)")
            return 'error'

        # 5. Клик по найденному предмету.
        # matchTemplate возвращает оконные координаты (cx + INV_SCAN[0]).
        # Используем pyautogui.click — напрямую через Windows API, просто и надёжно.
        try:
            import pyautogui
            # item_pos = (win_cx, win_cy) — оконные координаты (960×540 base)
            # Добавляем позицию окна + scale для экранных
            win = self.window_info[self.window_id]
            wx, wy = win["Position"]
            sx, sy = getattr(self, '_au_scale', (1.0, 1.0))
            screen_x = int(wx + item_pos[0] * sx)
            screen_y = int(wy + item_pos[1] * sy)
            log(f"Аук: pyautogui.click({screen_x},{screen_y}) — окно=({wx},{wy}) item=({item_pos[0]},{item_pos[1]}) scale=({sx:.2f},{sy:.2f})",
                self.window_id)
            pyautogui.click(screen_x, screen_y)
        except Exception as e:
            log(f"Аук: pyautogui.click ошибка: {e} — fallback на self._click",
                self.window_id, level="WARNING")
            await self._click(*item_pos)
        await asyncio.sleep(T_ITEM_WINDOW)
        # Скрин после клика — видно открылось ли окно цены
        after_item_click = self._grab(INV_SCAN)
        await self._save_debug("au_after_item_click.png", after_item_click)

        # 6. OCR "Текущая минимальная цена"
        # ⚠️ КРИТИЧНО: если OCR не смог прочитать цену — СТОП, не выставлять!
        # Раньше бот ставил 10 аден и «успешно» выставлял предмет за бесценок.
        # Fallback: если мин цена отсутствует (предмет новый, nobody selling) —
        # читаем МАКС цену и ставим такую же (не ниже рынка).
        min_price = self._ocr_price()
        MAX_REASONABLE_PRICE = 10_000_000  # 10M — верхняя граница sanity
        price_source = "мин"

        if min_price is None or min_price < 10 or min_price > MAX_REASONABLE_PRICE:
            log(f"Аук: мин. цена не читается (={min_price}) — пробую макс. цену",
                self.window_id, level="WARNING")
            max_price = self._ocr_max_price()
            if max_price is not None and 10 <= max_price <= MAX_REASONABLE_PRICE:
                # Ставим по макс цене — не ниже рынка
                min_price = max_price
                price_source = "макс"
                log(f"Аук: использую макс. цену {max_price} как опорную",
                    self.window_id)
            else:
                log(f"Аук: ни мин, ни макс цена не читаются (мин={min_price}, "
                    f"макс={max_price}) — СТОП, не выставляю",
                    self.window_id, level="ERROR")
                self.profile.notify("error",
                                   "Аук: OCR цены не сработал — предмет НЕ выставлен")
                await self._click(*BTN_CLOSE)
                await asyncio.sleep(1)
                return 'error'

        # По макс цене ставим РАВНУЮ (не -1) — не ниже рынка
        if price_source == "макс":
            my_price = min_price
        else:
            my_price = max(min_price - 1, 10)  # -1 от мин, не ниже 10
        log(f"Аук: моя цена = {my_price} (опора={min_price}, источник={price_source})",
            self.window_id)

        # 7. Ввести цену (дебаг-скриншот numpad ДО ввода — для проверки координат)
        try:
            numpad_shot = self._grab((530, 340, 110, 130))
            await self._save_debug("au_numpad_before_type.png", numpad_shot)
        except Exception:
            pass
        await self._type_price(str(my_price))

        # 8. Клик "ОК" в окне цены
        await self._click(*BTN_OK_PRICE)
        await asyncio.sleep(1)

        # 9. Клик "Добавить"
        await self._click(*BTN_ADD)
        await asyncio.sleep(LONG_PAUSE)
        log("Аук: лот выставлен на продажу", self.window_id)

        return 'ok'
