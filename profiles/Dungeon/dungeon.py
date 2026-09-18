from profiles.event_driven import EventDrivenProfile
from bot.methods.game import PartyDungeon
from bot.events.enums import MonitorType
from bot.clogger import log
import asyncio
import os

import mss
import numpy as np
import cv2

# ── Ленивый импорт pytesseract (не падает если Tesseract не установлен) ────
_pytesseract = None


def _get_pytesseract():
    """Возвращает модуль pytesseract или None (как в auction.py)."""
    global _pytesseract
    if _pytesseract is not None:
        return _pytesseract
    try:
        import pytesseract as _pt
        # Пробуем стандартный путь установки Tesseract на Windows
        for cand in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                     r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                     r"C:\Tesseract-OCR\tesseract.exe"):
            if os.path.exists(cand):
                _pt.pytesseract.tesseract_cmd = cand
                break
        _pytesseract = _pt
        return _pytesseract
    except ImportError:
        log("Данжи: pytesseract не установлен — OCR текста недоступен",
            level="WARNING")
        return None
    except Exception as e:
        log(f"Данжи: pytesseract init failed: {e}", level="WARNING")
        return None


# ── mss singleton (как в auction.py — НЕ открываем на каждый захват) ─────
try:
    _sct = mss.mss()
except AttributeError:
    _sct = mss.MSS()


class Dungeon(EventDrivenProfile):

    EVENT_HANDLERS = {
        "death": "_handle_death",
    }

    def __init__(self, window_info, settings=None, **kwargs):
        super().__init__(window_info, settings=settings, **kwargs)
        self.dungeon_type = kwargs.get("dungeon_type", "Пати данж")

    def profile_version(self):
        return "1.0.0"

    def profile_name(self):
        return "Party Dungeon"

    async def _handle_death(self):
        log("_Анлука, помер во время пати данжа. оффаюсь", self.window_id)

    async def main_loop(self):
        if self.dungeon_type == "Благословенная Земля":
            return await self._blessed_land_loop()
        return await self._party_dungeon_loop()

    async def _party_dungeon_loop(self):
        window_id, window = self.window_id, self.window_info[self.window_id]
        try:
            rip, btn = await self.combat.is_dead()
            if rip:
                log("Окно сдохло, не обрабатываю.", window_id)
                await self.combat.respawn()
                await asyncio.sleep(5)
                if self.settings.BUY_LOOT_RIP:
                    await self.town.buy_loot()
                return

            flaged = False
            energo = await self.energo.is_on()
            if energo:
                flaged = True
                #await self.energo.turn_off()
                await asyncio.sleep(0.1)

            await self.tp.safe_home()
            await asyncio.sleep(1.5)
            await self.tp.wait_arrived()
            dungeon = PartyDungeon(self)
            await dungeon.party_create()
            await asyncio.sleep(0.5)
            await dungeon.open_dungeon()
            await asyncio.sleep(1.5)
            xy = await dungeon.find_dungeon()
            if not xy:
                log("Не нашел данжик, выхожу", window_id)
                await dungeon.wait_and_click("main_menu_gui")
                await asyncio.sleep(1.8)
                await dungeon.party_leave()

                if self.settings.NEED_BACK_TO_SPOT_PARTY_DUNGEON:
                    to_spot = await self.tp.to_random_spot(self.settings.SPOT_OT, self.settings.SPOT_DO)
                    if to_spot:
                        return True
                    return False

                if flaged:
                    await self.energo.turn_on()
                    return False

            started = await dungeon.start_dungeon(xy)
            if started:
                await self.combat.toggle_autohunt()
                to_back = await dungeon.no_limit() # энерго включено клики в dungeon.cliks
                self.events_checker.start_monitoring(window_id, self, monitors=[MonitorType.DEATH])
                log(to_back, window_id)
                while True:
                    hunt = await self.combat.is_autohunt_on()
                    log(hunt, window_id)
                    if not hunt:
                        self.events_checker.stop_monitoring(window_id)
                        rip, btn = await self.combat.is_dead()
                        if rip:
                            log("Анлука, помер во время пати данжа. оффаюсь", window_id)
                            return

                        break

                    await asyncio.sleep(3)

                await asyncio.sleep(3)
                rip, btn = await self.combat.is_dead()
                if rip:
                    log("Анлука, помер во время пати данжа. оффаюсь", window_id)
                    return

                log("Успешно пробежал пати данжик закуплюсь и оффаюсь", window_id)
                if await self.energo.is_on():
                    await self.energo.turn_off(ignore=True)
                    await asyncio.sleep(1)

                    self.notify_screenshot("Закачал пати данжик, закуплюсь и оффнусь =)")

                await self.mouse.click(self.window_info, 200, 188)

                await dungeon.to_start()
                await dungeon.party_leave()

                ok, in_town, npcs = await self.town.buy_in_shop()
                log(f"ok={ok}, town={in_town}", window_id)

                if self.settings.NEED_BACK_TO_SPOT_PARTY_DUNGEON:
                    to_spot = await self.tp.to_random_spot(self.settings.SPOT_OT, self.settings.SPOT_DO)
                    if to_spot:
                        return True
                    return False

                if not await self.energo.is_on():
                    await self.energo.turn_on()
                    await asyncio.sleep(1)

                if ok:
                    return True

                return False

        except asyncio.CancelledError:
            log("Профиль остановлен вручную", window_id)
            raise

    # ── Утилиты захвата экрана ──────────────────────────────────────────
    def _grab_window_rect(self, wx, wy, x_rel, y_rel, w, h):
        """
        Сделать скриншот прямоугольника окна.
        x_rel, y_rel — координаты ВНУТРИ окна (relative).
        Возвращает BGR numpy array или None при ошибке mss.
        Создаёт local_sct если глобальный _sct упал (srcdc crash).
        """
        monitor = {"left": wx + x_rel, "top": wy + y_rel,
                   "width": w, "height": h}
        try:
            shot = _sct.grab(monitor)
            arr = np.array(shot)  # BGRA
            return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
        except Exception as e:
            log(f"Данжи: _sct.grab упал: {e} — пробую local mss", level="WARNING")
            try:
                local_sct = mss.mss()
                shot = local_sct.grab(monitor)
                arr = np.array(shot)
                return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
            except Exception as e2:
                log(f"Данжи: и local mss не смог: {e2}", level="ERROR")
                return None

    def _save_debug(self, name, img):
        """Сохранить отладочный PNG рядом с dungeon.py."""
        try:
            out_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(out_dir, name)
            cv2.imwrite(path, img)
            log(f"Данжи: сохранён {name}", self.window_id)
        except Exception as e:
            log(f"Данжи: не удалось сохранить {name}: {e}",
                self.window_id, level="WARNING")

    def _ocr_find_text(self, gray_img, needles):
        """
        Ищет текст (или его часть) через pytesseract.
        needles — список строк (lowercase), ищем любое вхождение.
        Возвращает (found: bool, y_pixel: int) — y пиксель в исходном gray_img.
        """
        pt = _get_pytesseract()
        if pt is None or gray_img is None:
            return False, 0
        try:
            # x2 для OCR (мелкий шрифт лучше читается)
            big = cv2.resize(gray_img, (gray_img.shape[1] * 2, gray_img.shape[0] * 2),
                             interpolation=cv2.INTER_CUBIC)
            # Бинаризация — повышает точность OCR
            _, thresh = cv2.threshold(big, 0, 255,
                                      cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            text = pt.image_to_string(thresh, lang="rus+eng",
                                      config="--psm 6").lower()
            for n in needles:
                if n in text:
                    # Нашли — ищем координату слова через image_to_data
                    data = pt.image_to_data(thresh, lang="rus+eng",
                                            config="--psm 6",
                                            output_type=pt.Output.DICT)
                    for i, word in enumerate(data["text"]):
                        if n in word.lower():
                            # координаты в big (x2) → делим на 2 для оригинала
                            y_orig = data["top"][i] // 2 + data["height"][i] // 4
                            return True, y_orig
                    # Если слово найдено в тексте, но не в data — берём центр
                    return True, gray_img.shape[0] // 2
        except Exception as e:
            log(f"Данжи: OCR ошибка: {e}", level="DEBUG")
        return False, 0

    def _match_icon_multiscale(self, gray_scene, icon_gray,
                              scales=(0.7, 0.85, 1.0, 1.15, 1.3),
                              threshold=0.55):
        """
        Мульти-скейл matchTemplate. Возвращает (score, (x,y)) или (0.0, None).
        """
        best_score = 0.0
        best_loc = None
        if gray_scene is None or icon_gray is None:
            return best_score, best_loc
        for scale in scales:
            new_w = int(icon_gray.shape[1] * scale)
            new_h = int(icon_gray.shape[0] * scale)
            if new_w <= 5 or new_h <= 5:
                continue
            if new_w > gray_scene.shape[1] or new_h > gray_scene.shape[0]:
                continue
            scaled = cv2.resize(icon_gray, (new_w, new_h),
                                 interpolation=cv2.INTER_AREA)
            try:
                result = cv2.matchTemplate(gray_scene, scaled,
                                           cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if max_val > best_score:
                    best_score = max_val
                    best_loc = max_loc
            except cv2.error:
                continue
        return best_score, best_loc

    async def _blessed_land_loop(self):
        """
        Благословенная Земля — одиночный данж.

        Алгоритм:
        1. Выйти из сна (БЕЗ телепорта в город!)
        2. Открыть меню → Подземелья
        3. ДВОЙНОЙ поиск по списку данжей (с прокруткой):
           а) OCR — ищем текст "благословен" (русский)
           б) matchTemplate — ищем иконку blessed_land_icon.jpg (мульти-скейл)
           Сработал любой → клик по строке
        4. Проверить "Время доступа": красный 0 → усыпить окно
        5. Нажать "Вход"
        6. Выбрать последний яркий уровень
        7. Нажать стрелку телепорта
        8. Отправить окно в сон
        """
        window_id = self.window_id
        try:
            game = PartyDungeon(self)

            window = self.window_info[window_id]
            wx, wy = window["Position"]
            ww, wh = window["Width"], window["Height"]

            log(f"Данжи: окно wx={wx} wy={wy} {ww}x{wh}", window_id)

            # 1. Выйти из сна (БЕЗ телепорта в город!)
            if await self.energo.is_on():
                await self.energo.turn_off()
                await asyncio.sleep(2)

            # 2. Открыть меню → Подземелья
            if not await game.wait_and_click("main_menu_gui", timeout=7):
                log("Данжи: не открыл главное меню", window_id)
                return False
            await asyncio.sleep(1)

            if not await game.wait_and_click("dungeon_button_menu", timeout=5):
                log("Данжи: не нашёл кнопку подземелий", window_id)
                await game.wait_and_click("main_menu_gui", timeout=2)
                return False
            await asyncio.sleep(2)
            log("Данжи: меню подземелий открыто", window_id)

            # 3. Загрузить иконку для matchTemplate
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "blessed_land_icon.jpg")
            icon_gray = None
            if not os.path.exists(icon_path):
                log(f"Данжи: файл иконки не найден: {icon_path}",
                    window_id, level="WARNING")
            else:
                icon_bgr = cv2.imread(icon_path)
                if icon_bgr is None:
                    log("Данжи: иконка не загрузилась cv2.imread",
                        window_id, level="WARNING")
                else:
                    icon_gray = cv2.cvtColor(icon_bgr, cv2.COLOR_BGR2GRAY)
                    log(f"Данжи: иконка {icon_gray.shape[1]}x{icon_gray.shape[0]} загружена",
                        window_id)

            # Зона списка данжей — относительно окна (для кликов!)
            # list_x_rel, list_y_rel — offset внутри окна
            list_x_rel = 0
            list_y_rel = int(wh * 0.20)
            list_w = int(ww * 0.55)
            list_h = int(wh * 0.65)

            # Абсолютные координаты для mss.grab (нужны для скриншота)
            abs_x = wx + list_x_rel
            abs_y = wy + list_y_rel

            found = False
            click_x_rel, click_y_rel = 0, 0

            MAX_SCROLL_ATTEMPTS = 12
            for scroll_attempt in range(MAX_SCROLL_ATTEMPTS):
                # Скриншот зоны списка (mss.grab использует абсолютные!)
                scene_bgr = self._grab_window_rect(wx, wy,
                                                    list_x_rel, list_y_rel,
                                                    list_w, list_h)
                if scene_bgr is None:
                    log(f"Данжи: попытка {scroll_attempt+1} — скриншот пустой, скроллю дальше",
                        window_id, level="WARNING")
                    # НЕ выходим — пробуем скроллить и снова
                    await self.mouse.wheel(self.window_info,
                                            [(list_x_rel + list_w // 2,
                                              list_y_rel + list_h // 2)],
                                            direction="down", times=3)
                    await asyncio.sleep(0.6)
                    continue

                scene_gray = cv2.cvtColor(scene_bgr, cv2.COLOR_BGR2GRAY)

                # Сохраняем первый скриншот — пользователь увидит что бот видел
                if scroll_attempt == 0:
                    self._save_debug("blessed_search_start.png", scene_bgr)

                # Способ 1: OCR — ищем "благословен" (русский, lowercase)
                ocr_needles = ["благословен", "благослов", "благос"]
                ocr_found, ocr_y = self._ocr_find_text(scene_gray, ocr_needles)

                # Способ 2: matchTemplate — multi-scale
                tm_score, tm_loc = (0.0, None)
                if icon_gray is not None:
                    tm_score, tm_loc = self._match_icon_multiscale(
                        scene_gray, icon_gray,
                        scales=(0.7, 0.85, 1.0, 1.15, 1.3),
                        threshold=0.55)

                log(f"Данжи: попытка {scroll_attempt+1}/{MAX_SCROLL_ATTEMPTS} — "
                    f"TM={tm_score:.3f} OCR={'да' if ocr_found else 'нет'}",
                    window_id, level="DEBUG")

                # Нашли — выбираем более надёжный способ
                if tm_score >= 0.55 and tm_loc is not None:
                    # matchTemplate нашёл — кликаем по центру иконки
                    click_x_rel = list_x_rel + tm_loc[0] + icon_gray.shape[1] // 2
                    click_y_rel = list_y_rel + tm_loc[1] + icon_gray.shape[0] // 2
                    found = True
                    log(f"Данжи: найден через matchTemplate "
                        f"({click_x_rel},{click_y_rel}) score={tm_score:.3f}",
                        window_id)
                    # Сохраняем найденный кадр
                    self._save_debug("blessed_found_tm.png", scene_bgr)
                    break

                if ocr_found:
                    # OCR нашёл — кликаем чуть правее текста (по строке)
                    click_x_rel = list_x_rel + int(list_w * 0.15)
                    click_y_rel = list_y_rel + min(max(ocr_y, 10), list_h - 10)
                    found = True
                    log(f"Данжи: найден через OCR "
                        f"({click_x_rel},{click_y_rel})",
                        window_id)
                    self._save_debug("blessed_found_ocr.png", scene_bgr)
                    break

                # Скролл вниз (relative coords — mouse.wheel добавит Position)
                await self.mouse.wheel(self.window_info,
                                       [(list_x_rel + list_w // 2,
                                         list_y_rel + list_h // 2)],
                                       direction="down", times=3)
                await asyncio.sleep(0.6)

            # Сохраняем финальный скриншот для отладки если не нашли
            if not found:
                self._save_debug("blessed_not_found.png", scene_bgr)
                log("Данжи: 'Благословенная Земля' не найдена после всех попыток",
                    window_id, level="WARNING")
                await game.wait_and_click("npc_global_quit_button", timeout=2)
                await asyncio.sleep(1)
                # Возвращаем окно в сон
                if not await self.energo.is_on():
                    await self.energo.turn_on()
                    await asyncio.sleep(1)
                return False

            # 4. Кликнуть по найденной строке → проверить "Время доступа"
            log(f"Данжи: клик по строке ({click_x_rel},{click_y_rel})",
                window_id)
            await self.mouse.click(self.window_info, click_x_rel, click_y_rel)
            await asyncio.sleep(1.5)
            log("Данжи: кликнул, проверяю время доступа", window_id)

            # Проверка "Время доступа" — красный 0 = уже был сегодня
            time_zone_bgr = self._grab_window_rect(
                wx, wy,
                int(ww * 0.45), int(wh * 0.55),
                int(ww * 0.50), int(wh * 0.13))
            if time_zone_bgr is not None:
                self._save_debug("blessed_time_check.png", time_zone_bgr)
                b_tz, g_tz, r_tz = cv2.split(time_zone_bgr)
                red_mask = (r_tz > 180) & (g_tz < 80) & (b_tz < 80)
                red_count = int(np.sum(red_mask))
                white_mask = (r_tz > 180) & (g_tz > 180) & (b_tz > 180)
                white_count = int(np.sum(white_mask))

                if red_count > 20 and white_count < 10:
                    log(f"Данжи: время доступа = 0 (красный={red_count}) — "
                        f"сегодня уже был, усыпляю", window_id, level="WARNING")
                    await game.wait_and_click("npc_global_quit_button", timeout=2)
                    await asyncio.sleep(1)
                    if not await self.energo.is_on():
                        await self.energo.turn_on()
                        await asyncio.sleep(1)
                    return True
                else:
                    log(f"Данжи: время доступа есть (белый={white_count}, "
                        f"красный={red_count}) — иду в данж", window_id)
            else:
                log("Данжи: не удалось снять зону времени доступа — "
                    "продолжаю на свой страх и риск", window_id, level="WARNING")

            # 5. Нажать "Вход" (оранжевая кнопка, правый нижний угол)
            await asyncio.sleep(1)
            await self.mouse.click(self.window_info,
                                    int(ww * 0.85), int(wh * 0.90))
            await asyncio.sleep(2)
            log("Данжи: нажал Вход", window_id)

            # 6. Выбрать последний яркий уровень
            # Скроллим в самый низ
            await self.mouse.wheel(self.window_info,
                                    [(ww // 2, wh // 2)],
                                    direction="down", times=10)
            await asyncio.sleep(1)

            # Скроллим вверх и ищем последний яркий
            level_found = False
            level_click_y = 0
            for attempt in range(10):
                full_bgr = self._grab_window_rect(wx, wy, 0, 0, ww, wh)
                if full_bgr is None:
                    await self.mouse.wheel(self.window_info,
                                           [(ww // 2, wh // 2)],
                                           direction="up", times=2)
                    await asyncio.sleep(0.5)
                    continue
                gray = cv2.cvtColor(full_bgr, cv2.COLOR_BGR2GRAY)
                h, w = gray.shape
                level_zone = gray[:, int(w * 0.25):int(w * 0.5)]
                bright_rows = np.sum(level_zone > 180, axis=1)
                bright_lines = np.where(bright_rows > 10)[0]

                if len(bright_lines) > 0:
                    level_click_y = int(bright_lines[-1])
                    await self.mouse.click(self.window_info,
                                            int(w * 0.35), level_click_y)
                    await asyncio.sleep(1)
                    level_found = True
                    log(f"Данжи: выбран последний яркий уровень "
                        f"(y={level_click_y})", window_id)
                    break

                await self.mouse.wheel(self.window_info,
                                       [(ww // 2, wh // 2)],
                                       direction="up", times=2)
                await asyncio.sleep(0.5)

            if not level_found:
                log("Данжи: не нашёл доступный уровень",
                    window_id, level="WARNING")
                await game.wait_and_click("npc_global_quit_button", timeout=2)
                return False

            # 7. Нажать стрелку телепорта (справа от уровня)
            await self.mouse.click(self.window_info,
                                    int(ww * 0.65), level_click_y)
            await asyncio.sleep(2)
            log("Данжи: нажал телепорт, отправляю в сон", window_id)

            # 8. Отправить окно в сон (персонаж сам вернётся на спот)
            await asyncio.sleep(2)
            if not await self.energo.is_on():
                await self.energo.turn_on()
                await asyncio.sleep(1)

            log("Данжи: Благословенная Земля запущена, окно в сне",
                window_id)
            return True

        except asyncio.CancelledError:
            log("Данжи: остановлен вручную", window_id)
            raise
        except Exception as e:
            log(f"Данжи: непредвиденная ошибка: {e}",
                window_id, level="ERROR")
            try:
                await game.wait_and_click("npc_global_quit_button", timeout=2)
            except Exception:
                pass
            return False
