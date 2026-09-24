from profiles.event_driven import EventDrivenProfile
from bot.methods.game import PartyDungeon
from bot.events.enums import MonitorType
from bot.clogger import log
import asyncio
import os

import mss
import numpy as np
import cv2

# ── Ленивый импорт pytesseract ────
_pytesseract = None


def _get_pytesseract():
    global _pytesseract
    if _pytesseract is not None:
        return _pytesseract
    try:
        import pytesseract as _pt
        for cand in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                     r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                     r"C:\Tesseract-OCR\tesseract.exe"):
            if os.path.exists(cand):
                _pt.pytesseract.tesseract_cmd = cand
                break
        _pytesseract = _pt
        return _pytesseract
    except ImportError:
        log("Данги: pytesseract не установлен", level="WARNING")
        return None
    except Exception as e:
        log(f"Данги: pytesseract init failed: {e}", level="WARNING")
        return None


try:
    _sct = mss.mss()
except AttributeError:
    _sct = mss.MSS()


class Dungeon(EventDrivenProfile):

    EVENT_HANDLERS = {
        "death": "_handle_death",
    }

    def __init__(self, window_info, settings=None, **kwargs):
        self.dungeon_type = kwargs.pop("dungeon_type", "Пати данж")
        super().__init__(window_info, settings=settings, **kwargs)

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

    # ── Утилиты захвата ──
    def _grab_window_rect(self, wx, wy, x_rel, y_rel, w, h):
        monitor = {"left": wx + x_rel, "top": wy + y_rel, "width": w, "height": h}
        try:
            shot = _sct.grab(monitor)
            arr = np.array(shot)
            return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
        except Exception:
            try:
                local_sct = mss.mss()
                shot = local_sct.grab(monitor)
                arr = np.array(shot)
                return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
            except Exception:
                return None

    def _save_debug(self, name, img):
        try:
            if img is None:
                return False
            out_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(out_dir, name)
            ok, buf = cv2.imencode(".png", img)
            if not ok:
                return False
            with open(path, "wb") as f:
                f.write(buf.tobytes())
            log(f"Данги: сохранён {name} -> {path}", self.window_id)
            return True
        except Exception as e:
            log(f"Данги: не удалось сохранить {name}: {e}", self.window_id, level="WARNING")
            return False

    def _ocr_find_text(self, gray_img, needles):
        pt = _get_pytesseract()
        if pt is None or gray_img is None:
            return False, 0
        try:
            big = cv2.resize(gray_img, (gray_img.shape[1] * 2, gray_img.shape[0] * 2),
                             interpolation=cv2.INTER_CUBIC)
            _, thresh = cv2.threshold(big, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            text = pt.image_to_string(thresh, lang="rus+eng", config="--psm 6").lower()
            text_oneline = " | ".join(text.split())
            log(f"Данги OCR: '{text_oneline[:100]}'", self.window_id, level="DEBUG")
            for n in needles:
                if n in text:
                    data = pt.image_to_data(thresh, lang="rus+eng", config="--psm 6",
                                            output_type=pt.Output.DICT)
                    for i, word in enumerate(data["text"]):
                        if n in word.lower():
                            y_orig = data["top"][i] // 2 + data["height"][i] // 4
                            return True, y_orig
                    return True, gray_img.shape[0] // 2
        except Exception as e:
            log(f"Данги: OCR ошибка: {e}", level="DEBUG")
        return False, 0

    def _match_icon_multiscale(self, gray_scene, icon_gray,
                              scales=(0.95, 1.0, 1.05),
                              threshold=0.65):
        """Мульти-скейл matchTemplate для поиска шаблона."""
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
            scaled = cv2.resize(icon_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
            try:
                result = cv2.matchTemplate(gray_scene, scaled, cv2.TM_CCOEFF_NORMED)
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
        1. Выйти из сна (_wake_up)
        2. Открыть меню → Подземелья
        3. Найти "Благословенная Земля" через OCR (скролл)
        4. Кликнуть → проверить время доступа
        5. Нажать "Вход"
        6. Кликнуть по стрелке Ур.75 (x=65.2%, y=73.3%)
        7. Проверить БЕЛЫЙ ЭКРАН = загрузка данжа
        8. Ждать 8 сек → energo.turn_on() (сон)
        """
        window_id = self.window_id
        try:
            game = PartyDungeon(self)
            window = self.window_info[window_id]
            wx, wy = window["Position"]
            ww, wh = window["Width"], window["Height"]

            log(f"Данги: окно wx={wx} wy={wy} {ww}x{wh}", window_id)

            # 1. Выйти из сна
            await self._wake_up(max_attempts=3)

            # 2. Открыть меню → Подземелья
            if not await game.wait_and_click("main_menu_gui", timeout=7):
                log("Данги: не открыл главное меню", window_id)
                return False
            await asyncio.sleep(1)

            if not await game.wait_and_click("dungeon_button_menu", timeout=5):
                log("Данги: не нашёл кнопку подземелий", window_id)
                await game.wait_and_click("main_menu_gui", timeout=2)
                return False
            await asyncio.sleep(2)
            log("Данги: меню подземелий открыто", window_id)

            # Скриншот после открытия
            menu_shot = self._grab_window_rect(wx, wy, 0, 0, ww, wh)
            if menu_shot is not None:
                self._save_debug("blessed_menu_opened.png", menu_shot)

            # Загрузить шаблон для matchTemplate
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "blessed_zemlya.png")
            if not os.path.exists(icon_path):
                icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "blessed_land_text.png")
            icon_gray = None
            if os.path.exists(icon_path):
                icon_bgr = cv2.imread(icon_path)
                if icon_bgr is not None:
                    icon_gray = cv2.cvtColor(icon_bgr, cv2.COLOR_BGR2GRAY)
                    log(f"Данги: шаблон {icon_gray.shape[1]}x{icon_gray.shape[0]} загружен", window_id)

            # 3. Зона списка данжей
            list_x_rel = 0
            list_y_rel = int(wh * 0.20)
            list_w = int(ww * 0.55)
            list_h = int(wh * 0.65)
            scroll_center = (list_x_rel + list_w // 2, list_y_rel + list_h // 2)

            found = False
            click_x_rel, click_y_rel = 0, 0
            scene_bgr = None

            # OCR слова для поиска "Благословенная Земля"
            # Оставляем только ДЛИННЫЕ слова (10+ символов) чтобы не было
            # ложных срабатываний на ивентовых данжах типа "Родник Лунных
            # Кроликов". Короткие типа "благ" могли совпасть с мусором OCR.
            ocr_needles = [
                "благословенная", "благословенн", "благословен",
            ]

            MAX_SCROLL_ATTEMPTS = 30  # 15 → 30, но times=2 (было 5) — чаще проверяем
            for scroll_attempt in range(MAX_SCROLL_ATTEMPTS):
                scene_bgr = self._grab_window_rect(wx, wy, list_x_rel, list_y_rel, list_w, list_h)
                if scene_bgr is None:
                    await self.mouse.wheel(self.window_info, [scroll_center],
                                           direction="down", times=2)
                    await asyncio.sleep(0.05)
                    continue

                scene_gray = cv2.cvtColor(scene_bgr, cv2.COLOR_BGR2GRAY)

                if scroll_attempt % 3 == 0:
                    self._save_debug(f"blessed_scroll_{scroll_attempt:02d}.png", scene_bgr)

                ocr_found, ocr_y = self._ocr_find_text(scene_gray, ocr_needles)

                # matchTemplate — поиск по шаблону
                tm_score, tm_loc = (0.0, None)
                if icon_gray is not None:
                    tm_score, tm_loc = self._match_icon_multiscale(
                        scene_gray, icon_gray,
                        scales=(0.95, 1.0, 1.05),
                        threshold=0.65)

                log(f"Данги: попытка {scroll_attempt+1}/{MAX_SCROLL_ATTEMPTS} — "
                    f"TM={tm_score:.3f} OCR={'да' if ocr_found else 'нет'}",
                    window_id, level="DEBUG")

                # НАШЛИ — только если matchTemplate нашёл И иконка СВЕТЛАЯ
                # (Благословенная Земля — светлая/день, gray mean > 80)
                # Кролики и другие ивентовые данжи — ТЁМНЫЕ (gray mean < 80)
                # Это защищает от ложных срабатываний на ивентовых данжах
                # которые визуально похожи но тёмные (ночь/вечер).
                if tm_score >= 0.65 and tm_loc is not None:
                    # Вырезаем найденную иконку
                    ix1 = max(0, tm_loc[0])
                    iy1 = max(0, tm_loc[1])
                    ix2 = min(scene_bgr.shape[1], tm_loc[0] + icon_gray.shape[1])
                    iy2 = min(scene_bgr.shape[0], tm_loc[1] + icon_gray.shape[0])
                    icon_found = scene_bgr[iy1:iy2, ix1:ix2]
                    if icon_found.size > 0:
                        icon_gray_found = cv2.cvtColor(icon_found, cv2.COLOR_BGR2GRAY)
                        icon_brightness = float(icon_gray_found.mean())
                        log(f"Данги: найдена иконка TM={tm_score:.3f}, "
                            f"яркость={icon_brightness:.0f} "
                            f"({'СВЕТЛАЯ — Благ Земля' if icon_brightness > 80 else 'ТЁМНАЯ — не Благ Земля'})",
                            window_id, level="DEBUG")
                        if icon_brightness > 80:
                            click_x_rel = list_x_rel + tm_loc[0] + icon_gray.shape[1] // 2
                            click_y_rel = list_y_rel + tm_loc[1] + icon_gray.shape[0] // 2
                            found = True
                            log(f"Данги: НАШЁЛ Благословенную Землю "
                                f"({click_x_rel},{click_y_rel}) score={tm_score:.3f} "
                                f"brightness={icon_brightness:.0f}",
                                window_id)
                            self._save_debug("blessed_found_tm.png", scene_bgr)
                            break
                        else:
                            log(f"Данги: matchTemplate нашёл (score={tm_score:.3f}) "
                                f"НО иконка ТЁМНАЯ (brightness={icon_brightness:.0f}<80) — "
                                f"это НЕ Благ Земля (вероятно Кролики или ивент). "
                                f"Пропускаю.", window_id, level="DEBUG")
                    else:
                        log(f"Данги: иконка пустая после вырезки", window_id,
                            level="DEBUG")

                # Fallback: только OCR (без matchTemplate) — если matchTemplate
                # почему-то не сработал но OCR нашёл "земля"
                if ocr_found:
                    click_x_rel = list_x_rel + int(list_w * 0.15)
                    click_y_rel = list_y_rel + min(max(ocr_y, 10), list_h - 10)
                    found = True
                    log(f"Данги: найден через OCR ({click_x_rel},{click_y_rel})",
                        window_id)
                    self._save_debug("blessed_found_ocr.png", scene_bgr)
                    break

                # Логируем если matchTemplate нашёл но OCR не подтвердил —
                # возможно ивентовый данж с похожей иконкой
                if tm_score >= 0.65 and tm_loc is not None and not ocr_found:
                    log(f"Данги: matchTemplate нашёл (score={tm_score:.3f}) "
                        f"НО OCR не подтвердил 'земля' — пропускаю "
                        f"(возможно ивентовый данж)", window_id, level="DEBUG")

                await self.mouse.wheel(self.window_info, [scroll_center],
                                       direction="down", times=2)
                await asyncio.sleep(0.05)

            if not found:
                if scene_bgr is not None:
                    self._save_debug("blessed_not_found.png", scene_bgr)
                log("Данги: 'Благословенная Земля' не найдена", window_id, level="WARNING")
                await game.wait_and_click("npc_global_quit_button", timeout=2)
                await asyncio.sleep(1)
                if not await self.energo.is_on():
                    await self.energo.turn_on()
                    await asyncio.sleep(1)
                return False

            # 4. Кликнуть по строке → проверить время доступа
            log(f"Данги: клик по строке ({click_x_rel},{click_y_rel})", window_id)
            await self.mouse.click(self.window_info, click_x_rel, click_y_rel)
            await asyncio.sleep(1.5)
            log("Данги: кликнул, проверяю время доступа", window_id)

            # Скриншот после клика
            after_click = self._grab_window_rect(wx, wy, 0, 0, ww, wh)
            if after_click is not None:
                self._save_debug("blessed_after_dungeon_click.png", after_click)

            # Проверка времени доступа
            time_zone = self._grab_window_rect(wx, wy,
                                                int(ww * 0.45), int(wh * 0.55),
                                                int(ww * 0.50), int(wh * 0.13))
            if time_zone is not None:
                self._save_debug("blessed_time_check.png", time_zone)
                b_tz, g_tz, r_tz = cv2.split(time_zone)
                red_mask = (r_tz > 180) & (g_tz < 80) & (b_tz < 80)
                red_count = int(np.sum(red_mask))
                white_mask = (r_tz > 180) & (g_tz > 180) & (b_tz > 180)
                white_count = int(np.sum(white_mask))

                if red_count > 20 and white_count < 10:
                    log(f"Данги: время доступа = 0 — сегодня уже был, усыпляю", window_id, level="WARNING")
                    await game.wait_and_click("npc_global_quit_button", timeout=2)
                    await asyncio.sleep(1)
                    if not await self.energo.is_on():
                        await self.energo.turn_on()
                        await asyncio.sleep(1)
                    return True
                else:
                    log(f"Данги: время доступа есть — иду в данж", window_id)
            else:
                log("Данги: не удалось снять зону времени доступа", window_id, level="WARNING")

            # 5. Нажать "Вход"
            await asyncio.sleep(1)
            await self.mouse.click(self.window_info, int(ww * 0.85), int(wh * 0.90))
            await asyncio.sleep(2)
            log("Данги: нажал Вход", window_id)

            # Скриншот окна выбора уровня
            level_window = self._grab_window_rect(wx, wy, 0, 0, ww, wh)
            if level_window is not None:
                self._save_debug("blessed_level_window.png", level_window)

            # 6. Кликнуть по стрелке Ур.75
            LEVELS_Y = [
                ("Ур.75", 0.733),
                ("Ур.70", 0.649),
                ("Ур.60", 0.551),
                ("Ур.55", 0.462),
                ("Ур.50", 0.373),
                ("Ур.40", 0.284),
                ("Ур.30", 0.141),
            ]
            ARROW_X_PCT = 0.652

            arrow_clicked = False
            for level_name, level_y_pct in LEVELS_Y:
                arrow_x = int(ww * ARROW_X_PCT)
                arrow_y = int(wh * level_y_pct)

                await self._activate()
                await asyncio.sleep(0.3)

                log(f"Данги: пробую {level_name} — клик ({arrow_x},{arrow_y})", window_id)
                await self.mouse.click(self.window_info, arrow_x, arrow_y)
                await asyncio.sleep(2)

                after_click = self._grab_window_rect(wx, wy, 0, 0, ww, wh)
                if after_click is not None:
                    self._save_debug(f"blessed_after_{level_name.replace('.', '_')}.png", after_click)
                    gray = cv2.cvtColor(after_click, cv2.COLOR_BGR2GRAY)
                    mean_brightness = float(gray.mean())

                    if mean_brightness > 200:
                        log(f"Данги: белый экран (mean={mean_brightness:.0f}) — "
                            f"данж запущен через {level_name}", window_id)
                        arrow_clicked = True
                        break
                    else:
                        log(f"Данги: окно ещё открыто (mean={mean_brightness:.0f}) — "
                            f"пробую следующий", window_id)

            if not arrow_clicked:
                log("Данги: не смог кликнуть по стрелке", window_id, level="WARNING")
                await game.wait_and_click("npc_global_quit_button", timeout=2)
                return False

            # 7. Данж запущен — ждём 8 сек и усыпляем
            log("Данги: данж запущен, жду 8 сек на загрузку", window_id)
            await asyncio.sleep(8)

            after_load = self._grab_window_rect(wx, wy, 0, 0, ww, wh)
            if after_load is not None:
                self._save_debug("blessed_after_load.png", after_load)

            # Усыпляем с retry 3 раза
            if not await self.energo.is_on():
                for attempt in range(3):
                    log(f"Данги: попытка усыпления {attempt+1}/3", window_id)
                    await self.energo.turn_on()
                    await asyncio.sleep(2)
                    if await self.energo.is_on():
                        log(f"Данги: уснул с попытки {attempt+1}", window_id)
                        break
                    await asyncio.sleep(2)
            else:
                log("Данги: уже в энергорежиме", window_id)

            log("Данги: Благословенная Земля запущена, окно в сне", window_id)
            return True

        except asyncio.CancelledError:
            log("Данги: остановлен вручную", window_id)
            raise
        except Exception as e:
            log(f"Данги: непредвиденная ошибка: {e}", window_id, level="ERROR")
            try:
                await game.wait_and_click("npc_global_quit_button", timeout=2)
            except Exception:
                pass
            return False

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
                to_back = await dungeon.no_limit()
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
