import asyncio

from bot.clogger import log
from bot.methods.base import parseCBT
from bot.methods.game._base import GameAction


class Scheduler(GameAction):

    async def start(self) -> bool | None:
        return await self._run("on")

    async def stop(self) -> bool | None:
        return await self._run("off")

    async def _run(self, state: str) -> bool | None:
        tag = ""

        if state == "on":
            log("Пробую запустить расписание", self.window_id)
            self.profile.notify("info", "Пробую включить шедулю")
            tag = "schedule_start"

        if state == "off":
            log("Пробую остановить расписание", self.window_id)
            self.profile.notify("info", "Пробую оффнуть шедулю")
            await self.profile.tp.safe_home()
            tp1 = await self.profile.tp.wait_arrived()
            if tp1:
                await self.profile.energo.turn_on()
                return True

        if await self.profile.energo.is_on():
            await self.profile.energo.turn_off()

        if not await self.wait_and_click("main_menu_gui", timeout=7):
            return False

        if not await self.wait_and_click("schedule_menu", timeout=5):
            await self.wait_and_click("main_menu_gui", timeout=3)
            return False

        await asyncio.sleep(1)

        if tag == "schedule_start":
            xy, rgb = parseCBT("schedule_cant_start", profile=self.profile)
            is_true = await self.profile.check_pixel(xy, rgb, timeout=3, thr=2)
            if is_true:
                await self.wait_and_click("main_menu_gui", timeout=2)
                await asyncio.sleep(1)
                return None

        if not await self.wait_and_click(tag, timeout=5):
            # Кнопка «Начать расписание» не найдена. Возможно расписание
            # уже запущено — тогда на её месте кнопка «Остановить расписание»
            # (schedule_stop, серый/коричневый цвет). Проверим.
            xy_stop, rgb_stop = parseCBT("schedule_stop", profile=self.profile)
            already_running = False
            if xy_stop:
                already_running = await self.profile.check_pixel(
                    xy_stop, rgb_stop, timeout=2, thr=4,
                )

            if already_running:
                # Расписание уже идёт — выходим из меню и усыпляем окно.
                # Пользователь: «ему надо просто выйти отсюда и уйти в сон,
                # выход я подметил так же как кнопки со стрелочкой (цифра 3)
                # нажал, он вышел из меню шедули и усыпляем окно».
                log("Расписание уже запущено (кнопка «Остановить» вместо "
                    "«Начать») — выхожу из меню и усыпаю окно",
                    self.window_id, level="WARNING")
                # Кнопка выхода из меню шедули (стрелочка в левом верхнем углу)
                await self.wait_and_click("npc_global_quit_button", timeout=3)
                await asyncio.sleep(1)
                # Усыпить окно
                if not await self.profile.energo.is_on():
                    await self.profile.energo.turn_on()
                return None  # не ошибка — просто расписание уже идёт

            # Не schedule_stop и не schedule_start — окно реально сломалось
            log("Окно сломалось?", self.window_id)
            self.profile.notify(
                "error",
                f"Возможно окно залипло, подойди глянь плиз\n\ntry schedule {state} | {tag}",
            )
            self.profile.notify_screenshot("Кажись залипли, #важно")
            return False

        if state == "off":
            if await self.wait_and_click("main_menu_gui", timeout=7):
                await asyncio.sleep(2)
                await self.profile.energo.turn_on()
                return True

        await asyncio.sleep(2)
        tp = await self.profile.tp.wait_arrived()
        if tp:
            await self.profile.energo.turn_on()
            return True

        return False
