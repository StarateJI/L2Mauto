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

    async def on_stop(self):
        for task in self._child_tasks:
            task.cancel()
        await asyncio.gather(*self._child_tasks, return_exceptions=True)
        await super().on_stop()

    async def _blessed_land_loop(self):
        """
        Благословенная Земля — одиночный данж.

        Процесс:
        1. Выйти из сна (БЕЗ телепорта в город!)
        2. Открыть меню → Подземелья → вкладка "Простые"
        3. Найти "Благословенная Земля" в списке
        4. Кликнуть по ней → нажать "Вход"
        5. В окне выбора уровня — выбрать ПОСЛЕДНИЙ яркий (доступный) уровень
        6. Нажать стрелку телепорта
        7. Включить автоохоту
        8. Ждать пока не закончится время
        9. После окончания — персонаж сам вернётся на спот
        """
        window_id = self.window_id
        try:
            # PartyDungeon наследуется от GameAction — у него есть wait_and_click
            from bot.methods.game import PartyDungeon
            game = PartyDungeon(self)

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

            # 3. Найти "Благословенная Земля" в списке
            # Список данжей — скроллим вниз пока не найдём или не дойдём до конца
            found = False
            import mss
            import numpy as np
            import cv2
            window = self.window_info[window_id]
            wx, wy = window["Position"]
            ww, wh = window["Width"], window["Height"]

            # Зона ТОЛЬКО списка данжей — левая половина, ниже заголовка
            list_x = wx
            list_y = wy + int(wh * 0.25)  # ниже вкладок
            list_w = int(ww * 0.55)       # только левая часть (список)
            list_h = int(wh * 0.65)       # до низа окна

            for scroll_attempt in range(10):
                monitor = {"left": list_x, "top": list_y, "width": list_w, "height": list_h}
                try:
                    with mss.mss() as sct:
                        shot = np.array(sct.grab(monitor))
                except Exception:
                    log("Данжи: mss grab failed", window_id, level="WARNING")
                    return False

                # Ищем "Благословенная Земля" через OCR — только зону списка
                try:
                    gray = cv2.cvtColor(shot, cv2.COLOR_BGR2GRAY)
                    # Увеличиваем x2 для лучшего OCR
                    big = cv2.resize(gray, (list_w * 2, list_h * 2), interpolation=cv2.INTER_CUBIC)
                    text = self._ocr_dungeon_list(big)
                    log(f"Данжи: OCR попытка {scroll_attempt+1}: '{text[:60]}...'", window_id, level="DEBUG")
                    if "благословен" in text.lower() or "благослов" in text.lower():
                        found = True
                        log(f"Данжи: 'Благословенная Земля' найдена на попытке {scroll_attempt+1}", window_id)
                        break
                except Exception as e:
                    log(f"Данжи: OCR failed: {e}", window_id, level="WARNING")

                # Проверить "Время доступа" — если 0 (красным) → уже был сегодня
                # "Время доступа" — это строка с описанием данжа (правая панель).
                # Справа от неё — значение времени. Белый = есть время, красный 0 = нет.
                try:
                    import cv2
                    # Зона справа от "Время доступа" — правая панель, НО выше "Бонусное время"
                    # "Время доступа" — 3-я строка, "Бонусное время" — 4-я строка (ниже)
                    # Берём зону ВЫШЕ бонусного времени, чтобы не поймать красный 0 оттуда
                    time_zone_x1 = int(w_img * 0.45)
                    time_zone_x2 = int(w_img * 0.95)
                    time_zone_y1 = int(h_img * 0.55)
                    time_zone_y2 = int(h_img * 0.68)  # до 68% — выше "Бонусное время"
                    time_zone = shot[time_zone_y1:time_zone_y2, time_zone_x1:time_zone_x2]

                    b_tz, g_tz, r_tz = cv2.split(time_zone)
                    # Красный текст: R высокий, G и B низкие
                    red_mask = (r_tz > 180) & (g_tz < 80) & (b_tz < 80)
                    red_count = int(np.sum(red_mask))
                    # Белый текст: все каналы высокие
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
                    elif white_count > 10:
                        log(f"Данжи: время доступа есть (белый текст, {white_count} пикс) — иду в данж",
                            window_id)
                except Exception:
                    pass

                # Скролл вниз
                await self.mouse.wheel(self.window_info, [(ww // 2, wh // 2)],
                                       direction="down", times=5)
                await asyncio.sleep(1)

            if not found:
                log("Данжи: 'Благословенная Земля' не найдена в списке", window_id, level="WARNING")
                await game.wait_and_click("npc_global_quit_button", timeout=2)
                return False

            # 4. Кликнуть по "Благословенная Земля" и нажать "Вход"
            # Клик по строке данжа (примерно центр левой части)
            await self.mouse.click(self.window_info, ww // 3, wh // 2)
            await asyncio.sleep(1)

            # Кнопка "Вход" (оранжевая, правый нижний угол)
            await self.mouse.click(self.window_info, int(ww * 0.85), int(wh * 0.9))
            await asyncio.sleep(2)
            log("Данжи: нажал Вход", window_id)

            # 5. Выбрать последний яркий уровень
            # Окно выбора уровня — список строк. Скроллим в самый низ.
            await self.mouse.wheel(self.window_info, [(ww // 2, wh // 2)],
                                   direction="down", times=10)
            await asyncio.sleep(1)

            # Скроллим вверх по одному и ищем последний яркий уровень
            level_found = False
            for attempt in range(10):
                try:
                    with mss.mss() as sct:
                        shot = np.array(sct.grab(monitor))
                    gray = cv2.cvtColor(shot, cv2.COLOR_BGR2GRAY)

                    # Яркие уровни — белый текст (значение пикселя > 180)
                    # Тусклые — серый текст (значение < 100)
                    # Ищем снизу вверх последний яркий
                    h, w = gray.shape
                    # Зона списка уровней — правая часть, примерно x=30%-50% от ширины
                    level_zone = gray[:, int(w * 0.25):int(w * 0.5)]
                    # Считаем яркие пиксели по строкам
                    bright_rows = np.sum(level_zone > 180, axis=1)
                    # Строки с достаточным количеством ярких пикселей — доступные уровни
                    bright_lines = np.where(bright_rows > 10)[0]

                    if len(bright_lines) > 0:
                        last_bright_y = int(bright_lines[-1])
                        # Клик по последнему яркому уровню
                        click_x = int(w * 0.35)
                        click_y = last_bright_y
                        await self.mouse.click(self.window_info, click_x, click_y)
                        await asyncio.sleep(1)
                        level_found = True
                        log(f"Данжи: выбран последний яркий уровень (y={click_y})", window_id)
                        break
                except Exception as e:
                    log(f"Данжи: level search failed: {e}", window_id, level="WARNING")

                # Скролл вверх на одну позицию
                await self.mouse.wheel(self.window_info, [(ww // 2, wh // 2)],
                                       direction="up", times=2)
                await asyncio.sleep(0.5)

            if not level_found:
                log("Данжи: не нашёл доступный уровень", window_id, level="WARNING")
                await game.wait_and_click("npc_global_quit_button", timeout=2)
                return False

            # 6. Нажать стрелку телепорта (справа от уровня)
            await self.mouse.click(self.window_info, int(ww * 0.65), click_y)
            await asyncio.sleep(2)
            log("Данжи: нажал телепорт", window_id)

            # 7. Автоохота уже включена — персонаж сам фармит
            log("Данжи: автоохота уже включена, жду окончания", window_id)

            # 8. Ждать пока не закончится время данжа
            self.events_checker.start_monitoring(window_id, self, monitors=[MonitorType.DEATH])
            while True:
                hunt = await self.combat.is_autohunt_on()
                if not hunt:
                    self.events_checker.stop_monitoring(window_id)
                    rip, btn = await self.combat.is_dead()
                    if rip:
                        log("Данжи: умер в Благословенной Земле", window_id)
                        await self.combat.respawn()
                        return False
                    break
                await asyncio.sleep(5)

            log("Данжи: Благословенная Земля завершена", window_id)

            # 9. Усыпить окно
            if not await self.energo.is_on():
                await self.energo.turn_on()
                await asyncio.sleep(1)

            return True

        except asyncio.CancelledError:
            log("Данжи: остановлен вручную", window_id)
            raise

    def _ocr_dungeon_list(self, gray_img):
        """OCR списка данжей через pytesseract."""
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
            text = pytesseract.image_to_string(gray_img, lang="rus+eng", config="--psm 6")
            return text
        except Exception:
            return ""