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
            # Кнопка «Начать расписание» не найдена. Частая причина —
            # расписание уже запущено, тогда на её месте кнопка «Остановить».
            # schedule_stop не имеет RGB в CBT (rgb="no"), поэтому проверить
            # пикселем не выйдет. Просто выходим из меню и усыпляем окно —
            # безопасно для любого случая (уже запущено / меню глюкнуло).
            # Пользователь: «ему надо просто выйти отсюда и уйти в сон,
            # выход я подметил так же как кнопки со стрелочкой (цифра 3).»
            log("Кнопка «Начать расписание» не найдена — выхожу из меню "
                "и усыпаю окно (возможно расписание уже идёт)",
                self.window_id, level="WARNING")
            # Кнопка выхода из меню шедули — стрелочка в ПРАВОМ ВЕРХНЕМ углу
            # заголовка «Расписание». npc_global_quit_button на (377,10) может
            # промахиваться (чуть выше). Кликаем по (385, 30) — точные
            # координаты кнопки выхода в окне 400×225 (подтверждено VLM).
            await self.mouse.click(self.window_info, 385, 30)
            log("Шедуля: клик выхода из меню (385, 30) — стрелочка",
                self.window_id, level="DEBUG")
            await asyncio.sleep(1.5)
            # Если всё ещё в меню — пробуем npc_global_quit_button как запас
            await self.wait_and_click("npc_global_quit_button", timeout=2)
            await asyncio.sleep(0.5)
            # Запас — главное меню (закрыть всё)
            await self.wait_and_click("main_menu_gui", timeout=2)
            await asyncio.sleep(1)
            # Усыпить окно
            if not await self.profile.energo.is_on():
                await self.profile.energo.turn_on()
            return None  # не ошибка — просто выходим

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
