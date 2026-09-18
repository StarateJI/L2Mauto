from profiles.event_driven import EventDrivenProfile
from bot.methods.game import PartyDungeon
from bot.events.enums import MonitorType
from bot.clogger import log
import asyncio


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

    async def _blessed_land_loop(self):
        """
        Благословенная Земля — одиночный данж.

        1. Выйти из сна (БЕЗ телепорта в город!)
        2. Открыть меню → Подземелья
        3. Найти иконку "Благословенная Земля" через matchTemplate (скроллим список)
        4. Кликнуть по ней → проверить "Время доступа" (красный 0 = спать)
        5. Нажать "Вход"
        6. Выбрать последний яркий уровень
        7. Нажать стрелку телепорта
        8. Отправить окно в сон (персонаж сам вернётся на спот после окончания)
        """
        window_id = self.window_id
        try:
            from bot.methods.game import PartyDungeon
            game = PartyDungeon(self)
            import mss
            import numpy as np
            import cv2
            import os

            window = self.window_info[window_id]
            wx, wy = window["Position"]
            ww, wh = window["Width"], window["Height"]

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

            # 3. Загрузить иконку и искать через matchTemplate
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "blessed_land_icon.jpg")
            if not os.path.exists(icon_path):
                log("Данжи: файл иконки blessed_land_icon.jpg не найден", window_id, level="ERROR")
                await game.wait_and_click("npc_global_quit_button", timeout=2)
                return False

            icon = cv2.imread(icon_path)
            icon_gray = cv2.cvtColor(icon, cv2.COLOR_BGR2GRAY)

            # Зона списка данжей — левая часть, ниже вкладок
            list_x = wx
            list_y = wy + int(wh * 0.25)
            list_w = int(ww * 0.55)
            list_h = int(wh * 0.65)

            found = False
            click_x, click_y = 0, 0

            for scroll_attempt in range(8):
                monitor = {"left": list_x, "top": list_y, "width": list_w, "height": list_h}
                try:
                    with mss.mss() as sct:
                        shot = np.array(sct.grab(monitor))
                except Exception:
                    log("Данжи: mss grab failed", window_id, level="WARNING")
                    return False

                gray = cv2.cvtColor(shot, cv2.COLOR_BGR2GRAY)

                # matchTemplate — multi-scale
                best_score = 0.0
                best_loc = None
                for scale in [0.8, 0.9, 1.0, 1.1, 1.2]:
                    new_w = int(icon_gray.shape[1] * scale)
                    new_h = int(icon_gray.shape[0] * scale)
                    if new_w > gray.shape[1] or new_h > gray.shape[0]:
                        continue
                    scaled = cv2.resize(icon_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
                    try:
                        result = cv2.matchTemplate(gray, scaled, cv2.TM_CCOEFF_NORMED)
                        _, max_val, _, max_loc = cv2.minMaxLoc(result)
                        if max_val > best_score:
                            best_score = max_val
                            best_loc = max_loc
                    except cv2.error:
                        continue

                log(f"Данжи: matchTemplate попытка {scroll_attempt+1} — score={best_score:.3f}",
                    window_id, level="DEBUG")

                if best_score >= 0.60:
                    # Нашли иконку — кликаем по центру
                    click_x = list_x + best_loc[0] + icon_gray.shape[1] // 4
                    click_y = list_y + best_loc[1] + icon_gray.shape[0] // 2
                    found = True
                    log(f"Данжи: иконка найдена на попытке {scroll_attempt+1} "
                        f"({click_x},{click_y}) score={best_score:.3f}", window_id)
                    break

                # Скролл вниз
                await self.mouse.wheel(self.window_info, [(list_x + list_w // 2, list_y + list_h // 2)],
                                       direction="down", times=3)
                await asyncio.sleep(0.5)

            if not found:
                log("Данжи: иконка 'Благословенная Земля' не найдена", window_id, level="WARNING")
                await game.wait_and_click("npc_global_quit_button", timeout=2)
                return False

            # 4. Кликнуть по иконке → проверить "Время доступа"
            await self.mouse.click(self.window_info, click_x, click_y)
            await asyncio.sleep(1)
            log("Данжи: кликнул по иконке, проверяю время доступа", window_id)

            try:
                monitor = {"left": wx, "top": wy, "width": ww, "height": wh}
                with mss.mss() as sct:
                    shot = np.array(sct.grab(monitor))
                h_img, w_img = shot.shape[:2]
                time_zone = shot[int(h_img * 0.55):int(h_img * 0.68),
                                 int(w_img * 0.45):int(w_img * 0.95)]
                b_tz, g_tz, r_tz = cv2.split(time_zone)
                red_mask = (r_tz > 180) & (g_tz < 80) & (b_tz < 80)
                red_count = int(np.sum(red_mask))
                white_mask = (r_tz > 180) & (g_tz > 180) & (b_tz > 180)
                white_count = int(np.sum(white_mask))

                if red_count > 20 and white_count < 10:
                    log("Данжи: время доступа = 0 (красным) — сегодня уже был, усыпляю",
                        window_id, level="WARNING")
                    await game.wait_and_click("npc_global_quit_button", timeout=2)
                    await asyncio.sleep(1)
                    if not await self.energo.is_on():
                        await self.energo.turn_on()
                        await asyncio.sleep(1)
                    return True
                else:
                    log(f"Данжи: время доступа есть (белый={white_count}, красный={red_count}) — иду в данж",
                        window_id)
            except Exception as e:
                log(f"Данжи: проверка времени не удалась: {e}", window_id, level="WARNING")

            # 5. Нажать "Вход" (оранжевая кнопка, правый нижний угол)
            await asyncio.sleep(1)
            await self.mouse.click(self.window_info, int(ww * 0.85), int(wh * 0.9))
            await asyncio.sleep(2)
            log("Данжи: нажал Вход", window_id)

            # 6. Выбрать последний яркий уровень
            # Скроллим в самый низ
            await self.mouse.wheel(self.window_info, [(ww // 2, wh // 2)],
                                   direction="down", times=10)
            await asyncio.sleep(1)

            # Скроллим вверх и ищем последний яркий
            level_found = False
            level_click_y = 0
            for attempt in range(10):
                try:
                    monitor = {"left": wx, "top": wy, "width": ww, "height": wh}
                    with mss.mss() as sct:
                        shot = np.array(sct.grab(monitor))
                    gray = cv2.cvtColor(shot, cv2.COLOR_BGR2GRAY)
                    h, w = gray.shape
                    level_zone = gray[:, int(w * 0.25):int(w * 0.5)]
                    bright_rows = np.sum(level_zone > 180, axis=1)
                    bright_lines = np.where(bright_rows > 10)[0]

                    if len(bright_lines) > 0:
                        level_click_y = int(bright_lines[-1])
                        await self.mouse.click(self.window_info, int(w * 0.35), level_click_y)
                        await asyncio.sleep(1)
                        level_found = True
                        log(f"Данжи: выбран последний яркий уровень (y={level_click_y})", window_id)
                        break
                except Exception:
                    pass
                await self.mouse.wheel(self.window_info, [(ww // 2, wh // 2)],
                                       direction="up", times=2)
                await asyncio.sleep(0.5)

            if not level_found:
                log("Данжи: не нашёл доступный уровень", window_id, level="WARNING")
                await game.wait_and_click("npc_global_quit_button", timeout=2)
                return False

            # 7. Нажать стрелку телепорта (справа от уровня)
            await self.mouse.click(self.window_info, int(ww * 0.65), level_click_y)
            await asyncio.sleep(2)
            log("Данжи: нажал телепорт, отправляю в сон", window_id)

            # 8. Отправить окно в сон (персонаж сам вернётся на спот после окончания)
            await asyncio.sleep(2)
            if not await self.energo.is_on():
                await self.energo.turn_on()
                await asyncio.sleep(1)

            log("Данжи: Благословенная Земля запущена, окно в сне", window_id)
            return True

        except asyncio.CancelledError:
            log("Данжи: остановлен вручную", window_id)
            raise
