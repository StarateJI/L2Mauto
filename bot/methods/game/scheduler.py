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
            tag = "schedule_stop"  # BUG S1: tag был пустым для state=="off"
            await self.profile.tp.safe_home()
            # BUG S7: wait_arrived() без таймаута — может повиснуть навсегда
            try:
                tp1 = await asyncio.wait_for(
                    self.profile.tp.wait_arrived(), timeout=30
                )
            except asyncio.TimeoutError:
                log("wait_arrived() таймаут (off/safe_home)", self.window_id)
                tp1 = False
            if tp1:
                await self.profile.energo.turn_on()
                return True

        if await self.profile.energo.is_on():
            await self.profile.energo.turn_off()
            # BUG S4: нет сна после turn_off() перед открытием главного меню
            await asyncio.sleep(2)

        if not await self.wait_and_click("main_menu_gui", timeout=7):
            return False

        if not await self.wait_and_click("schedule_menu", timeout=5):
            await self.wait_and_click("main_menu_gui", timeout=3)
            return False

        await asyncio.sleep(1)

        if tag == "schedule_start":
            xy, rgb = parseCBT("schedule_cant_start", profile=self.profile)
            # BUG S5: parseCBT("schedule_cant_start") без None guard —
            # если координат нет, check_pixel словит TypeError на None
            if xy is None:
                is_true = False
            else:
                is_true = await self.profile.check_pixel(xy, rgb, timeout=3, thr=2)
            if is_true:
                await self.wait_and_click("main_menu_gui", timeout=2)
                await asyncio.sleep(1)
                return None

        if not await self.wait_and_click(tag, timeout=5):
            # BUG S2: нет аккуратного выхода из «уже запущено/залипло» —
            # кликаем стрелку выхода (365, 45), затем закрываем все окна
            # по цепочке и усыпляем окно через energo.turn_on().
            log("Окно сломалось? Пытаюсь аккуратно выйти", self.window_id)
            self.profile.notify(
                "error",
                f"Возможно окно залипло, подойди глянь плиз\n\ntry schedule {state} | {tag}",
            )
            self.profile.notify_screenshot("Кажись залипли, #важно")
            try:
                await self.mouse.click(self.window_info, 365, 45)
            except Exception as e:
                log(f"Клик по стрелке выхода (365,45) упал: {e}", self.window_id)
            await asyncio.sleep(0.5)
            await self.wait_and_click("npc_global_quit_button", timeout=2)
            await asyncio.sleep(0.5)
            await self.wait_and_click("main_menu_gui", timeout=2)
            await asyncio.sleep(0.5)
            await self.profile.energo.turn_on()
            return None

        if state == "off":
            if await self.wait_and_click("main_menu_gui", timeout=7):
                await asyncio.sleep(2)
                await self.profile.energo.turn_on()
                return True

        await asyncio.sleep(2)
        # BUG S7: wait_arrived() без таймаута — финальная проверка телепорта
        try:
            tp = await asyncio.wait_for(
                self.profile.tp.wait_arrived(), timeout=30
            )
        except asyncio.TimeoutError:
            log("wait_arrived() таймаут (final)", self.window_id)
            tp = False
        if tp:
            await self.profile.energo.turn_on()
            return True

        return False
