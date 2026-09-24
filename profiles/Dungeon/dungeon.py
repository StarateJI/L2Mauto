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

    def _take_fullscreen_dungeon(self, name: str = "dungeon_full.png") -> None:
        """Сделать ПОЛНЫЙ скрин монитора и сохранить рядом с dungeon.py."""
        try:
            out_dir = os.path.dirname(os.path.abspath(__file__))
            path = os.path.join(out_dir, name)
            monitors = _sct.monitors
            if len(monitors) > 1:
                monitor = monitors[1]
            else:
                monitor = monitors[0]
            try:
                shot = _sct.grab(monitor)
            except Exception as e:
                if 'srcdc' in str(e) or 'memdc' in str(e):
                    try:
                        local_sct = mss.mss()
                    except Exception:
                        local_sct = mss.MSS()
                    shot = local_sct.grab(monitor)
                    try:
                        local_sct.close()
                    except Exception:
                        pass
                else:
                    raise
            arr = np.array(shot)
            img = cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
            ok, buf = cv2.imencode(".png", img)
            if ok:
                with open(path, "wb") as f:
                    f.write(buf.tobytes())
                log(f"Данги: фуллскрин {name} ({monitor['width']}x{monitor['height']})",
                    self.window_id)
        except Exception as e:
            log(f"Данги: фуллскрин {name} не удался: {e}", self.window_id, level="WARNING")

    async def _click_snap_dungeon(self, label: str, x: int, y: int,
                                   wait: float = 1.0) -> None:
        """Кликнуть в (x, y) и сделать полный скрин экрана после клика.
        Скрин сохраняется как dun_step_<label>_<ts>.png — видно все окна
        в момент клика, для диагностики."""
        await self.mouse.click(self.window_info, x, y)
        if wait > 0:
            await asyncio.sleep(wait)
        # ts = миллисекунды текущего времени
        import time as _t
        ts = int(_t.time() * 100) % 100000
        fname = f"dun_step_{label}_{ts}.png"
        try:
            self._take_fullscreen_dungeon(fname)
            log(f"Данги: клик {label} ({x},{y}) → скрин {fname}", self.window_id)
        except Exception as e:
            log(f"Данги: клик {label} ({x},{y}) — скрин не удался: {e}",
                self.window_id, level="DEBUG")
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

            # 3. Зона списка данжей
            list_x_rel = 0
            list_y_rel = int(wh * 0.20)
            list_w = int(ww * 0.55)
            list_h = int(wh * 0.65)
            scroll_center = (list_x_rel + list_w // 2, list_y_rel + list_h // 2)

            found = False
            click_x_rel, click_y_rel = 0, 0
            scene_bgr = None

            ocr_needles = [
                "земля", "земл", "благословенн", "благословен",
                "благослов", "благ", "blessed", "bless",
            ]

            MAX_SCROLL_ATTEMPTS = 15
            for scroll_attempt in range(MAX_SCROLL_ATTEMPTS):
                scene_bgr = self._grab_window_rect(wx, wy, list_x_rel, list_y_rel, list_w, list_h)
                if scene_bgr is None:
                    await self.mouse.wheel(self.window_info, [scroll_center],
                                           direction="down", times=5)
                    await asyncio.sleep(0.05)
                    continue

                scene_gray = cv2.cvtColor(scene_bgr, cv2.COLOR_BGR2GRAY)

                if scroll_attempt % 3 == 0:
                    self._save_debug(f"blessed_scroll_{scroll_attempt:02d}.png", scene_bgr)

                ocr_found, ocr_y = self._ocr_find_text(scene_gray, ocr_needles)

                log(f"Данги: попытка {scroll_attempt+1}/{MAX_SCROLL_ATTEMPTS} — "
                    f"OCR={'да' if ocr_found else 'нет'}", window_id, level="DEBUG")

                if ocr_found:
                    # Если OCR нашёл "земля" но текст в самом низу списка
                    # (ocr_y > 90% list_h) — значит виден только краешек иконки.
                    # Клик попадёт в пустую зону. Прокрутить ещё вниз.
                    if ocr_y > int(list_h * 0.90):
                        log(f"Данги: OCR нашёл 'земля' но в самом низу (ocr_y={ocr_y}, "
                            f"list_h={list_h}) — виден краешек. Прокручиваю ещё.",
                            window_id, level="DEBUG")
                        await self.mouse.wheel(self.window_info, [scroll_center],
                                               direction="down", times=3)
                        await asyncio.sleep(0.8)
                        # Переснимаем и пересчитаем OCR
                        scene_bgr = self._grab_window_rect(wx, wy, list_x_rel, list_y_rel, list_w, list_h)
                        if scene_bgr is not None:
                            scene_gray = cv2.cvtColor(scene_bgr, cv2.COLOR_BGR2GRAY)
                            ocr_found, ocr_y = self._ocr_find_text(scene_gray, ocr_needles)
                            log(f"Данги: после прокрутки — OCR={'да' if ocr_found else 'нет'} "
                                f"ocr_y={ocr_y}", window_id, level="DEBUG")
                    if ocr_found:
                        click_x_rel = list_x_rel + int(list_w * 0.15)
                        click_y_rel = list_y_rel + min(max(ocr_y, 10), list_h - 10)
                        found = True
                        log(f"Данги: найден через OCR ({click_x_rel},{click_y_rel}) "
                            f"ocr_y={ocr_y}",
                            window_id)
                        self._save_debug("blessed_found_ocr.png", scene_bgr)
                        break

                await self.mouse.wheel(self.window_info, [scroll_center],
                                       direction="down", times=5)
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

            # 4. Кликнуть по строке → проверить что правая панель изменилась
            # ВАЖНО: клик может не сработать с 1 раза (50/50).
            # Если после клика правая панель НЕ изменилась — повторяем.
            # Если не изменилась за 3 попытки — пропускаем (клик промахивается).
            # Правая панель = зона справа от списка данжей (50-100% ширины).
            # Если клик сработал → панель обновилась (другой данж выбран).
            # Без проверки OCR — просто сравниваем картинки до/после.
            for click_attempt in range(3):
                log(f"Данги: клик по строке ({click_x_rel},{click_y_rel}) "
                    f"попытка {click_attempt+1}/3", window_id)

                # Скрин правой панели ДО клика
                panel_before = self._grab_window_rect(wx, wy,
                                                       int(ww * 0.50), 0,
                                                       int(ww * 0.50), wh)

                await self._click_snap_dungeon('dungeon_row', click_x_rel, click_y_rel, wait=1.5)
                await asyncio.sleep(1.5)

                # Скрин правой панели ПОСЛЕ клика
                panel_after = self._grab_window_rect(wx, wy,
                                                      int(ww * 0.50), 0,
                                                      int(ww * 0.50), wh)

                # Проверка: изменилась ли правая панель
                if panel_before is None or panel_after is None:
                    log("Данги: не удалось снять правую панель",
                        window_id, level="WARNING")
                    continue

                # Сохраняем для диагностики
                self._save_debug(f"blessed_panel_before_{click_attempt+1}.png", panel_before)
                self._save_debug(f"blessed_panel_after_{click_attempt+1}.png", panel_after)

                # Сравнение: diff = средняя разница между кадрами
                diff = cv2.absdiff(panel_before, panel_after)
                diff_mean = float(diff.mean())
                # Считаем сколько пикселей сильно изменилось (> 30)
                gray_diff = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
                changed_pixels = int(np.sum(gray_diff > 30))
                total_pixels = gray_diff.shape[0] * gray_diff.shape[1]
                changed_ratio = changed_pixels / max(total_pixels, 1)

                log(f"Данги: попытка {click_attempt+1} — diff_mean={diff_mean:.1f} "
                    f"changed={changed_ratio:.1%} "
                    f"({'ИЗМЕНИЛОСЬ — клик сработал' if changed_ratio > 0.05 else 'НЕ изменилось — повтор'})",
                    window_id, level="DEBUG")

                # Если >5% пикселей изменилось — клик сработал
                if changed_ratio > 0.05:
                    log(f"Данги: клик сработал (changed={changed_ratio:.1%}) — "
                        f"проверяю время доступа", window_id)

                    # Теперь проверяем время доступа (красный 0 = уже был)
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
                            log(f"Данги: время доступа = 0 — сегодня уже был, усыпляю",
                                window_id, level="WARNING")
                            await game.wait_and_click("npc_global_quit_button", timeout=2)
                            await asyncio.sleep(1)
                            if not await self.energo.is_on():
                                await self.energo.turn_on()
                                await asyncio.sleep(1)
                            return True

                        log(f"Данги: время доступа есть (red={red_count}, white={white_count}) — иду в данж",
                            window_id)
                    else:
                        log("Данги: не удалось снять зону времени доступа",
                            window_id, level="WARNING")
                    break

                # Клик не сработал — повтор
                log(f"Данги: клик НЕ сработал (changed={changed_ratio:.1%}) — повтор",
                    window_id, level="WARNING")
            else:
                # 3 попытки клика не сработали — пропускаем
                log(f"Данги: 3 клика не сработали — правая панель не изменилась. "
                    f"Пропускаю данж.", window_id, level="ERROR")
                await game.wait_and_click("npc_global_quit_button", timeout=2)
                await asyncio.sleep(1)
                if not await self.energo.is_on():
                    await self.energo.turn_on()
                    await asyncio.sleep(1)
                return False

            # Скриншот после клика
            after_click = self._grab_window_rect(wx, wy, 0, 0, ww, wh)
            if after_click is not None:
                self._save_debug("blessed_after_dungeon_click.png", after_click)

            # 5. Нажать "Вход"
            await asyncio.sleep(1)
            await self._click_snap_dungeon('vhod', int(ww * 0.85), int(wh * 0.90), wait=2.0)
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
                await self._click_snap_dungeon('arrow', arrow_x, arrow_y, wait=2.0)
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

                await self._click_snap_dungeon('energo_sleep', 200, 188, wait=2.0)
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
