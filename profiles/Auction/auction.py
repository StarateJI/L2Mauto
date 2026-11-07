import random

from profiles.base import BaseProfile
from bot.clogger import log
import asyncio


class Auction(BaseProfile):
    def __init__(self, window_info, settings=None, **kwargs):
        super().__init__(window_info, settings=settings)
        # Режим аука из диалога запуска:
        #   "register"   — выставить (новый режим: снять+найти+поставить, цена min-1)
        #   "reregister" — перевыставить (старый режим: кнопка «Перевыставить всё» в игре)
        # По умолчанию "register" (как работало последние версии).
        self._auction_mode = kwargs.pop("auction_mode", "register")

    def profile_version(self):
        return "1.1.0"

    def profile_name(self):
        return "Auction Rereger"

    async def main_loop(self):
        window_id = self.window_id
        try:
            x = await self.energo.is_on()
            if x:
                await self.energo.turn_off()
                await asyncio.sleep(1)

            if self._auction_mode == "reregister":
                # Старый режим — кнопка «Перевыставить всё» в игре (как на боте v5.0.x)
                log(f"Аук: режим ПЕРЕВЫСТАВИТЬ (кнопка игры)", window_id)
                rereged = await self.auction.reregister_all()
            else:
                # Новый режим — снять каждый лот + найти + поставить с ценой min-1
                log(f"Аук: режим ВЫСТАВИТЬ (снять+найти+поставить)", window_id)
                rereged = await self.auction.reregister()

            if not rereged:
                log("Шось сломалось либо не смог перевыставить аук", window_id)

            if x:
                await self.energo.turn_on()
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            log("Профиль остановлен вручную", window_id)
            raise

    async def on_stop(self):
        for task in self._child_tasks:
            task.cancel()
        await asyncio.gather(*self._child_tasks, return_exceptions=True)
        await super().on_stop()

    def is_running(self):
        return self.running
