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
            tag = "schedule_stop"
            log("Пробую остановить расписание", self.window_id)
            self.profile.notify("info", "Пробую оффнуть шедулю")
            await self.profile.tp.safe_home()
            try:
                tp1 = await asyncio.wait_for(self.profile.tp.wait_arrived(), timeout=30)
            except asyncio.TimeoutError:
                log("Шедуля: wait_arrived таймаут 30с — пропускаю", self.window_id, level="WARNING")
                tp1 = False
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
            if xy is not None:
                is_true = await self.profile.check_pixel(xy, rgb, timeout=3, thr=2)
                if is_true:
                    await self.wait_and_click("main_menu_gui", timeout=2)
                    await asyncio.sleep(1)
                    return None

        if not await self.wait_and_click(tag, timeout=5):
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
        try:
            tp = await asyncio.wait_for(self.profile.tp.wait_arrived(), timeout=30)
        except asyncio.TimeoutError:
            log("Шедуля: wait_arrived таймаут 30с — пропускаю", self.window_id, level="WARNING")
            tp = False
        if tp:
            await self.profile.energo.turn_on()
            return True

        return False
