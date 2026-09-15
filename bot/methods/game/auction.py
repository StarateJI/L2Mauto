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
#
# ВАЖНО: mss использует thread-local handles. Если _grab вызывается из
# другого потока (LogUploader QThread и т.д.), handles не созданы в этом
# потоке → AttributeError: '_thread._local' object has no attribute 'srcdc'
# Решение: _grab пересоздаёт mss при ошибке (см. _recreate_sct).
_sct = None

def _get_sct():
    """Возвращает singleton mss. Создаёт при первом вызове."""
    global _sct
    if _sct is None:
        try:
            _sct = mss.mss()
        except AttributeError:
            _sct = mss.MSS()
    return _sct

def _recreate_sct():
    """Пересоздать mss singleton — если сломался thread-local handles."""
    global _sct
    try:
        if _sct is not None:
            _sct.close()
    except Exception:
        pass
    try:
        _sct = mss.mss()
    except AttributeError:
        _sct = mss.MSS()
    return _sct

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
ZONE_PRICE = (651, 230, 60, 15)  # OCR цены (было 868,306,80,20)
STATUS_ZONE = (598, 143, 105, 26) # статус лота (было 797,190,140,35)
OK_CHECK_ZONE = (525, 360, 45, 45) # оранжевая ОК (было 700,480,60,60)

# ── Калькулятор (3x4 numpad, 960×540) ────────────────────────────────────
# База: "5" на (584, 391) при 960×540 (было 778,521 при 1280×720)
# Шаг 30px (было 40px)
CALC_DIGITS = {
    '0': (584, 452),  # было (778, 602)
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
            # Если после swipe окно всё ещё в энерго — повторяем. ignore=False
            # чтобы turn_off сам проверял результат (не trust blindly).
            woke = False
            for attempt in range(1, 4):
                try:
                    # ignore=False только на последней попытке — turn_off
                    # сам проверит пиксель zalupka_gui после swipe (телепорт).
                    # На первых попытках ignore=True (быстро, без долгих проверок).
                    ignore_flag = (attempt < 3)
                    await self.profile.energo.turn_off(ignore=ignore_flag)
                except Exception as e:
                    log(f"Аук: turn_off попытка {attempt}/3 exception: {e}",
                        self.window_id, level="WARNING")

                await asyncio.sleep(1.0)

                # Проверка — реально вышло ли из сна?
                if await self.profile.energo.is_on():
                    log(f"Аук: после turn_off попытка {attempt}/3 — окно "
                        f"ВСЁ ЕЩЁ в энерго (swipe не сработал) — повторяю",
                        self.window_id, level="WARNING")
                    continue
                # is_on() = False — окно вышло из сна (или не было в нём)
                woke = True
                if attempt > 1:
                    log(f"Аук: окно вышло из сна с попытки {attempt}/3",
                        self.window_id)
                break

            if not woke:
                log("Аук: ВАЖНО — окно НЕ вышло из энерго за 3 попытки! "
                    "Аукцион не откроется — будет пустой кадр. Пропускаю окно.",
                    self.window_id, level="ERROR")
                # Добавить в пропущенные — вернёмся в конце прогона
                try:
                    from gui.maingui import NedoGui
                    gui = NedoGui._instance if hasattr(NedoGui, '_instance') else None
                    if gui and hasattr(gui, '_skipped_windows'):
                        gui._skipped_windows.append(self.window_id)
                except Exception:
                    pass
                return False

            # Пауза после выхода из энерго — окно должно «проснуться» полностью
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
        # Найти свободную из WORK_POSITIONS.
        # Проверяем ВСЕ окна (даже 400×225) — если окно уже стоит на позиции,
        # считаем её занятой (не только 960×540 окна).
        chosen_pos: Optional[Tuple[int, int]] = None
        try:
            from bot.utils import findAllWindows as _findAll
            all_wins = _findAll()
            occupied: set = set()
            my_title = self.window_info[self.window_id]["Title"]

            # Проверяем все позиции — занята ли любым окном в пределах tolerance
            for nick, info in all_wins.items():
                if info.get("Title") == my_title:
                    continue  # себя не считаем
                pos = info.get("Position", (0, 0))
                win_w = info.get("Width", 0)
                win_h = info.get("Height", 0)
                # Если окно любого размера стоит близко к рабочей позиции — занято
                for wp in WORK_POSITIONS:
                    if (abs(pos[0] - wp[0]) <= POSITION_TOLERANCE and
                        abs(pos[1] - wp[1]) <= POSITION_TOLERANCE):
                        occupied.add(wp)

            # Также проверяем окно по hwnd — может быть развёрнуто но не в findAllWindows
            import pygetwindow as gw
            try:
                all_gw_wins = gw.getAllWindows()
                for w in all_gw_wins:
                    if "Lineage2M" not in w.title:
                        continue
                    if w.title == my_title:
                        continue
                    for wp in WORK_POSITIONS:
                        if (abs(w.left - wp[0]) <= POSITION_TOLERANCE and
                            abs(w.top - wp[1]) <= POSITION_TOLERANCE):
                            occupied.add(wp)
            except Exception:
                pass

            for pos in WORK_POSITIONS:
                if pos not in occupied:
                    chosen_pos = pos
                    break
            if chosen_pos is None:
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
        """
        Вернуть окно в исходное положение (сохранённое до resize_work).
        Использует SetWindowPos (как _resize_work) — надёжнее чем moveTo+resizeTo,
        потому что moveTo не сработает если окно перекрыто другим окном 1280x720.
        """
        import ctypes
        import pygetwindow as gw

        SWP_NOZORDER = 0x0004
        SWP_NOACTIVATE = 0x0010
        SetWindowPos = ctypes.windll.user32.SetWindowPos

        saved = getattr(self.profile, '_au_saved_pos', None)
        if saved:
            left, top, w, h = saved
            self.profile._au_saved_pos = None
        else:
            left, top, w, h = 0, 40, REST_W, REST_H

        try:
            win = gw.getWindowsWithTitle(self.window_info[self.window_id]["Title"])[0]
            # restore + unmaximize (иначе SetWindowPos игнорируется)
            try:
                win.restore()
            except Exception:
                pass
            if win.isMaximized:
                try:
                    win.unmaximize()
                except Exception:
                    pass

            # SetWindowPos — принудительно, даже если окно перекрыто
            hwnd = win._hWnd
            SetWindowPos(
                ctypes.c_void_p(int(hwnd)), None,
                left, top, w, h,
                SWP_NOZORDER | SWP_NOACTIVATE,
            )
            await asyncio.sleep(0.5)

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
        Захват зоны rect=(x, y, w, h) в window-relative координатах.
        Возвращает BGR ndarray. mss отдаёт BGRA — конвертируем.
        """
        win = self.window_info[self.window_id]
        wx, wy = win["Position"]
        x, y, w, h = rect
        monitor = {"left": wx + x, "top": wy + y, "width": w, "height": h}
        # _grab может вызываться из разных потоков (LogUploader QThread и т.д.)
        # mss использует thread-local handles — при ошибке пересоздаём.
        try:
            shot = _get_sct().grab(monitor)
        except AttributeError as e:
            if 'srcdc' in str(e) or 'memdc' in str(e):
                # thread-local handles сломаны — пересоздаём mss
                log(f"Аук: mss сломался ({e}) — пересоздаю",
                    self.window_id, level="WARNING")
                _recreate_sct()
                shot = _get_sct().grab(monitor)
            else:
                raise
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
            sct = _get_sct()
            try:
                monitors = sct.monitors
                if len(monitors) > 1:
                    monitor = monitors[1]
                else:
                    monitor = monitors[0]
                shot = sct.grab(monitor)
            except AttributeError as e:
                if 'srcdc' in str(e) or 'memdc' in str(e):
                    log(f"Аук: mss сломался в _take_fullscreen ({e}) — пересоздаю",
                        self.window_id, level="WARNING")
                    sct = _recreate_sct()
                    monitors = sct.monitors
                    monitor = monitors[1] if len(monitors) > 1 else monitors[0]
                    shot = sct.grab(monitor)
                else:
                    raise
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
        """Клик по window-relative координатам через очередь мыши.
        Сначала _ensure_foreground — гарантия что клик уйдёт в правильное окно."""
        self._ensure_foreground()
        await self.mouse.click(self.window_info, x, y)

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
        Возвращает True только если статус «Продаётся» — НЕ трогаем.
        Возвращает False для «Не продано», таймера, или любого другого.

        Пользователь (простыми словами):
          - «Продаётся»  → пропускаем (return True)
          - «Отмена»     → переставляем (return False)
          - «Забрать»    → переставляем (return False) — это «Не продано»

        Метод: проверка ЦВЕТА статуса (надёжнее OCR который может не работать
        если pytesseract не установлен на ПК).
          - «Продаётся»  → ЗЕЛЁНЫЙ текст (G высокий, R низкий, B низкий)
          - «Не продано» → КРАСНЫЙ текст (R высокий, G низкий, B низкий)
          - таймер       → СЕРЫЙ/БЕЛЫЙ текст (все каналы средние)
        Только зелёный = «Продаётся» = return True.
        Красный/серый/белый = НЕ «Продаётся» = return False.
        """
        try:
            img = self._grab(STATUS_ZONE)
            # Сохраняем для отладки
            import cv2
            import os
            debug_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "au_status.png")
            cv2.imwrite(debug_path, img)

            b, g, r = cv2.split(img)
            total_pixels = img.shape[0] * img.shape[1]

            # ── Метод 1 (основной): ЦВЕТ статуса ────────────────────────────
            # Зелёный текст «Продаётся»: G высокий, R и B низкие.
            # HSV: H 40..90, S>50, V>100
            try:
                hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
                green_mask = cv2.inRange(hsv,
                                         np.array([40, 50, 100]),
                                         np.array([90, 255, 255]))
                green_count = int(np.sum(green_mask > 0))
                green_ratio = green_count / max(total_pixels, 1)

                # Красный текст «Не продано»: R высокий, G и B низкие.
                # HSV: H 0..10 или 170..180 (красный на краях круга)
                red_mask1 = cv2.inRange(hsv,
                                        np.array([0, 50, 100]),
                                        np.array([10, 255, 255]))
                red_mask2 = cv2.inRange(hsv,
                                        np.array([170, 50, 100]),
                                        np.array([180, 255, 255]))
                red_mask = cv2.bitwise_or(red_mask1, red_mask2)
                red_count = int(np.sum(red_mask > 0))
                red_ratio = red_count / max(total_pixels, 1)

                log(f"Аук: статус цвет: зелёный={green_count} ({green_ratio:.2%}), "
                    f"красный={red_count} ({red_ratio:.2%})",
                    self.window_id, level="DEBUG")

                # Зелёный > 3% → «Продаётся» (пропускаем)
                if green_ratio > 0.03:
                    log(f"Аук: статус = «Продаётся» (зелёный текст {green_ratio:.1%})",
                        self.window_id)
                    return True
                # Красный > 3% → «Не продано» (Забрать, переставляем)
                if red_ratio > 0.03:
                    log(f"Аук: статус = «Не продано» (красный текст {red_ratio:.1%}) — "
                        f"иду нажимать «Забрать»", self.window_id)
                    return False
            except Exception as e:
                log(f"Аук: цветовая проверка статуса не удалась: {e}",
                    self.window_id, level="DEBUG")

            # ── Метод 2 (fallback): OCR если цвет не сработал ────────────────
            # (серый/белый текст = таймер, не «Продаётся» и не «Не продано»)
            h, w = img.shape[:2]
            big = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
            pt = _get_pytesseract()
            if pt is None:
                # pytesseract не установлен — не можем читать OCR.
                # Но если цвет не сработал (ни зелёный ни красный), значит
                # это таймер или пусто → НЕ «Продаётся» → переставляем.
                log("Аук: pytesseract недоступен, цвет не зелёный/красный — "
                    "НЕ «Продаётся» (вероятно таймер), переставляю",
                    self.window_id, level="DEBUG")
                return False
            text = pt.image_to_string(
                gray, lang="rus+eng", config="--psm 7",
            ).strip().lower()
            log(f"Аук: статус лота OCR: '{text}'", self.window_id, level="DEBUG")

            # OCR ключевые слова для «Продаётся».
            ocr_match = any(kw in text for kw in
                            ("продаёт", "продает", "продаю", "продажа",
                             "продаё", "продае", "продаетс"))
            if ocr_match:
                log("Аук: статус = «Продаётся» (OCR method)", self.window_id)
                return True

            # Если OCR не нашёл «Продаётся» — это таймер или «Не продано».
            # В обоих случаях НЕ «Продаётся» → переставляем.
            return False

        except Exception as e:
            log(f"Аук: проверка статуса не удалась: {e} — НЕ ТРОГАЮ (безопасно)",
                self.window_id, level="WARNING")
            return True  # Если проверка упала — лучше не трогать

    async def _cancel_lot(self) -> bool:
        """
        Клик 'Отмена лота' (или 'Забрать' — та же кнопка на том же месте,
        другой текст). После клика появляется окно подтверждения.

        Пользователь: «забудь про цвет вообще, кнопка находится точно в том
        же месте, где и Отмена, всё, тебе больше не нужно ничего».

        До 2 попыток клика с ожиданием окна подтверждения.
        """
        for attempt in range(1, 3):
            await self._click(*BTN_CANCEL_LOT)
            log(f"Аук: клик Отмена/Забрать ({attempt}/2) {BTN_CANCEL_LOT}",
                self.window_id)
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
            pt = _get_pytesseract()
            if pt is None:
                return None
            text = pt.image_to_string(
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
                if area < 5:  # слишком маленький — шум
                    continue
                cx = int(centroids[i][0])
                cy = int(centroids[i][1])
                dots.append((cx, cy))
            return dots
        except Exception as e:
            log(f"Аук: _find_red_dots exception: {e}", self.window_id, level="WARNING")
            return []

    async def _find_item(self, sample_gray: np.ndarray) -> Optional[Tuple[int, int]]:
        """
        Искать предмет в инвентаре.
        Правильный порядок (как просил пользователь):
          1. ПЕРВИЧНО — multi-scale matchTemplate по ВСЕЙ зоне INV_SCAN на каждой
             странице. Находит ВСЕ места с score >= порога (не только лучшее),
             потому что в инвентаре могут быть чёрно-белые НЕПРОДАВАЕМЫЕ дубликаты
             с той же иконкой — matchTemplate может сматчить их тоже.
          2. ПОДТВЕРЖДЕНИЕ — рядом с найденной иконкой проверяем красную точку
             «новое». Предмет только что снят с продажи → у него ВСЕГДА есть
             красная точка. Чёрно-белые дубликаты (непродаваемые) точки не имеют.
          3. Кликаем только если ЕСТЬ И иконка И красная точка рядом.

        Красная точка — ВСПОМОГАТЕЛЬНАЯ (подтверждение), НЕ фильтр страниц.
        Каждая страница сканируется matchTemplate'ом независимо от наличия точек.
        """
        best_result = None  # (cx, cy, score, page) — window-relative
        h_sample, w_sample = sample_gray.shape[:2]

        for page in range(1, SCAN_PAGES + 1):
            log(f"Аук: сканирую страницу {page}/{SCAN_PAGES}", self.window_id)
            img = self._grab(INV_SCAN)
            await self._save_debug(f"au_page_{page}.png", img)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 1. ПЕРВИЧНО: multi-scale matchTemplate → все кандидаты >= порога.
            #    Берём ВСЕ пики, не только лучший — чтобы не пропустить наш
            #    цветной предмет, если B&W-дубликат получил чуть больший score.
            candidates = []  # [(cx, cy, score)] в координатах page_gray
            for scale in TM_SCALES:
                new_w = int(w_sample * scale)
                new_h = int(h_sample * scale)
                if new_w < 5 or new_h < 5:
                    continue
                if new_w > gray.shape[1] or new_h > gray.shape[0]:
                    continue
                scaled = cv2.resize(sample_gray, (new_w, new_h),
                                    interpolation=cv2.INTER_AREA)
                try:
                    result = cv2.matchTemplate(gray, scaled,
                                               cv2.TM_CCOEFF_NORMED)
                except cv2.error:
                    continue
                locs = np.where(result >= TM_THRESHOLD)
                for (pt_y, pt_x) in zip(*locs):
                    cx = int(pt_x) + new_w // 2
                    cy = int(pt_y) + new_h // 2
                    score = float(result[int(pt_y), int(pt_x)])
                    candidates.append((cx, cy, score))

            # Дедупликация: кандидаты в пределах 25px друг от друга —
            # оставляем с максимальным score (это один и тот же предмет,
            # сматченный на разных масштабах).
            candidates.sort(key=lambda c: -c[2])
            deduped = []
            for c in candidates:
                if all(abs(c[0] - d[0]) > 25 or abs(c[1] - d[1]) > 25
                       for d in deduped):
                    deduped.append(c)

            best_page_score = deduped[0][2] if deduped else 0.0

            # 2. ПОДТВЕРЖДЕНИЕ: красные точки на этой странице
            red_dots = self._find_red_dots(img)
            log(f"Аук: стр {page} — кандидатов TM: {len(deduped)} "
                f"(лучший score={best_page_score:.3f}), "
                f"красных точек: {len(red_dots)}", self.window_id)

            # 3. Ищем кандидата с красной точкой рядом.
            #    Красная точка в Lineage2M — правый верхний угол ячейки,
            #    т.е. в пределах ~40px от центра иконки 60×53.
            for (cx, cy, score) in deduped:
                confirmed_dot = None
                for (dx, dy) in red_dots:
                    if abs(dx - cx) <= 40 and abs(dy - cy) <= 40:
                        confirmed_dot = (dx, dy)
                        break
                if confirmed_dot is None:
                    # Иконка сматчилась, но красной точки рядом нет →
                    # это B&W-дубликат (непродаваемый), не наш предмет.
                    log(f"Аук: стр {page} — иконка ({cx},{cy}) "
                        f"score={score:.3f} НО без красной точки → дубликат, "
                        f"пропускаю", self.window_id, level="DEBUG")
                    continue

                # Есть И иконка И красная точка → наш предмет.
                win_cx = cx + INV_SCAN[0]
                win_cy = cy + INV_SCAN[1]
                if best_result is None or score > best_result[2]:
                    best_result = (win_cx, win_cy, score, page)
                    log(f"Аук: НАЙДЕН И ПОДТВЕРЖДЁН — стр {page} "
                        f"иконка ({cx},{cy}) + точка {confirmed_dot} "
                        f"→ клик ({win_cx},{win_cy}) score={score:.3f}",
                        self.window_id)
                # Точное совпадение с подтверждением — дальше не листаем.
                if score >= 0.90:
                    log(f"Аук: точное совпадение с красной точкой "
                        f"(score >= 0.90), не листаю дальше", self.window_id)
                    break

            if best_result is not None and best_result[2] >= 0.90:
                break

            if page < SCAN_PAGES:
                await self._swipe_inventory('down')

        # Вернуться к странице с предметом
        if best_result is not None:
            pages_to_back = best_result[3] - 1
            for _ in range(pages_to_back):
                await self._swipe_inventory('up')
            log(f"Аук: предмет найден и подтверждён красной точкой! "
                f"стр {best_result[3]} ({best_result[0]},{best_result[1]}) "
                f"score={best_result[2]:.3f}", self.window_id)
            return (best_result[0], best_result[1])

        # Не нашли — вернуться в начало
        for _ in range(SCAN_PAGES - 1):
            await self._swipe_inventory('up')
        log(f"Аук: предмет не найден ни на одной из {SCAN_PAGES} страниц "
            f"(ни иконки с красной точкой)", self.window_id, level="ERROR")
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
        # Пропускаем. (TEST_MODE выключен — проверка возвращена.)
        if self._is_status_prodano():
            log("Аук: первый лот в статусе «Продаётся» — пропускаю",
                self.window_id)
            return 'empty'

        # 2b. Если образец пустой (0 SIFT точек) и статус не «Продаётся» —
        # значит строка лота пустая (нет лотов на продаже вообще).
        # Это НЕ ошибка — просто нечего переставлять. Возвращаем 'empty'.
        if kp_count == 0:
            log("Аук: образец лота пустой (нет иконки) — список лотов пуст. "
                "Завершаю прогон (не ошибка).",
                self.window_id, level="INFO")
            return 'empty'

        # 3. Клик "Отмена лота" (или "Забрать" — та же кнопка, другой текст).
        # Пользователь: «просто текст другой, действуй по скрипту».
        # Обе кнопки одинакового цвета (серый фон + белый текст). После клика
        # окно подтверждения появляется в обоих случаях одинаково.
        if not await self._cancel_lot():
            log("Аук: окно подтверждения не появилось — список лотов пуст "
                "(кнопка серая). Завершаю прогон (не ошибка).",
                self.window_id, level="INFO")
            return 'empty'

        # 4. Подождать анимацию и кликнуть ОК
        await asyncio.sleep(T_CONFIRM_SETTLE)
        if not await self._click_ok_cancel():
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

        # 5. Кликнуть по найденному предмету (двойной клик — первый выделяет, второй открывает окно)
        await self._click(*item_pos)
        log(f"Аук: клик 1 по предмету {item_pos}", self.window_id)
        await asyncio.sleep(1.0)
        await self._click(*item_pos)
        log(f"Аук: клик 2 по предмету {item_pos}", self.window_id)
        await asyncio.sleep(T_ITEM_WINDOW)
        # Скрин после клика — видно открылось ли окно цены
        after_item_click = self._grab(INV_SCAN)
        await self._save_debug("au_after_item_click.png", after_item_click)

        # 6. OCR "Текущая минимальная цена"
        # ⚠️ КРИТИЧНО: если OCR не смог прочитать цену — СТОП, не выставлять!
        # Раньше бот ставил 10 аден и «успешно» выставлял предмет за бесценок.
        min_price = self._ocr_price()
        if min_price is None or min_price < 10:
            log("Аук: не удалось прочитать мин. цену — СТОП, не выставляю "
                "(защита от продажи за бесценок)", self.window_id, level="ERROR")
            self.profile.notify("error",
                               "Аук: OCR цены не сработал — предмет НЕ выставлен")
            # Закрыть окно цены крестиком (выйти без выставления)
            await self._click(*BTN_CLOSE)
            await asyncio.sleep(1)
            return 'error'

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
