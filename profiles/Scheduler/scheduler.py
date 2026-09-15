import asyncio

from bot.clogger import log
from profiles.base import BaseProfile


class Scheduler(BaseProfile):

    def profile_version(self):
        return "1.2.0"

    def profile_name(self):
        return "Scheduler"

    async def main_loop(self):
        try:
            log("Запуск Scheduler профиля", self.window_id)

            # если окно в энерго — выходим из него (Шедуля сама телепортируется в город)
            if await self.energo.is_on():
                log("Был в энерго, вырубаю перед запуском Шедули", self.window_id)
                if not await self.energo.turn_off():
                    log("Не смог выйти из энерго — остановка", self.window_id)
                    self.notify("error", "Шедуля: не смог выйти из энерго")
                    self.notify_screenshot("Шедуля: не смог выйти из энерго")
                    return
                await asyncio.sleep(1)  # пауза после пробуждения окна

            sch = self.scheduler

            if not await sch.wait_and_click("main_menu_gui", timeout=10):
                log("Не открыл главное меню", self.window_id)
                self.notify("error", "Scheduler: не открыл главное меню")
                self.notify_screenshot("Scheduler: не открыл главное меню")
                return

            await asyncio.sleep(1)  # даём меню дорисоваться

            if not await sch.wait_and_click("schedule_menu", timeout=7):
                log("Не нашёл schedule_menu", self.window_id)
                self.notify("error", "Scheduler: schedule_menu не найден")
                self.notify_screenshot("Scheduler: schedule_menu не найден")
                return

            await asyncio.sleep(2)  # меню расписания прогрузится

            if not await sch.wait_and_click("schedule_start", timeout=7):
                # Кнопка «Начать расписание» не найдена. Частая причина —
                # расписание уже запущено, тогда на её месте кнопка «Остановить».
                # Пользователь: «если уже окно в шедуле и я запускаю кнопку Шедуля,
                # бот ломается — там кнопка Остановить вместо Начать. Надо просто
                # выйти отсюда и уйти в сон, выход кнопка со стрелочкой.»
                log("Кнопка «Начать расписание» не найдена — выхожу из меню "
                    "и усыпаю окно (возможно расписание уже идёт)",
                    self.window_id, level="WARNING")
                # Кнопка выхода из меню шедули — стрелочка в ПРАВОМ ВЕРХНЕМ углу
                # заголовка «Расписание» (VLM подтвердил координаты по скрину).
                await self.mouse.click(self.window_info, 365, 45)
                log("Шедуля: клик выхода из меню (365, 45) — стрелочка",
                    self.window_id, level="DEBUG")
                await asyncio.sleep(1.5)
                # Запас — npc_global_quit_button (правый верхний угол)
                await sch.wait_and_click("npc_global_quit_button", timeout=2)
                await asyncio.sleep(0.5)
                # Запас — главное меню (закрыть всё)
                await sch.wait_and_click("main_menu_gui", timeout=2)
                await asyncio.sleep(1)
                # Усыпить окно
                if not await self.energo.is_on():
                    await self.energo.turn_on()
                log("Шедуля: окно уложено спать (расписание уже идёт или "
                    "кнопка не найдена)", self.window_id)
                return

            log("Schedule запущен, жду 40 сек (окно само летит в город и закупается)", self.window_id)
            await asyncio.sleep(40)

            # энерго — с подтверждением и повторной попыткой
            for attempt in range(1, 3):
                if await self.energo.turn_on():
                    await asyncio.sleep(2)
                    if await self.energo.is_on():
                        log(f"Энерго подтверждён (попытка {attempt})", self.window_id)
                        break
                    log(f"Энерго не подтвердился (попытка {attempt}), пробую ещё раз", self.window_id)
                    await asyncio.sleep(2)
                else:
                    log(f"turn_on вернул False (попытка {attempt})", self.window_id)
                    await asyncio.sleep(2)
            else:
                log("Энерго так и не включился — сообщаю владельцу", self.window_id)
                self.notify("error", "Шедуля: не включился энерго после 2 попыток — глянь окно!")
                self.notify_screenshot("Шедуля: не включился энерго")
                return

            log("Энерго включён, профиль завершён", self.window_id)
            self.notify("info", "Расписание запущено, энерго включён")

        except asyncio.CancelledError:
            log("Scheduler остановлен вручную", self.window_id)
            raise