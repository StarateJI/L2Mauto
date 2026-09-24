import asyncio
import math

from bot.clogger import log
from bot.delays import (
    DELAY_AFTER_CLICK_ENERGO,
    DELAY_CHECK_ENERGO,
    SLEEP_AFTER_UNBLOCK,
)
from bot.events.enums import MonitorType, Region
from bot.methods.base import parseCBT
from bot.methods.game._base import GameAction


class Energo(GameAction):

    async def is_on(self) -> bool:
        xy, rgb = parseCBT("energomode_center_gui", profile=self.profile)
        if xy is None:
            return False
        if not await self.profile.check_pixel(xy, rgb, timeout=DELAY_CHECK_ENERGO):
            log("Не находимся в энерго", self.window_id)
            return False
        log("Находимся в энергорежиме", self.window_id)
        return True

    async def turn_on(self) -> bool:
        button_xy, _ = parseCBT("energo_mode_gui", profile=self.profile)
        if button_xy is None:
            return False
        button_x, button_y = button_xy
        window = self.window_info[self.window_id]
        width = window["Width"]
        height = window["Height"]

        log(f"Energo: turn_on — клик по ({button_x},{button_y}) окно {width}x{height}",
            self.window_id)
        await self.mouse.click(self.window_info, button_x, button_y)
        # Фуллскрин после клика для диагностики
        try:
            import mss as _mss
            import cv2 as _cv2
            import numpy as _np
            import os as _os
            _sct = _mss.mss()
            monitors = _sct.monitors
            monitor = monitors[1] if len(monitors) > 1 else monitors[0]
            try:
                shot = _sct.grab(monitor)
            except Exception as e:
                if 'srcdc' in str(e) or 'memdc' in str(e):
                    local_sct = _mss.mss()
                    shot = local_sct.grab(monitor)
                    local_sct.close()
                else:
                    raise
            arr = _np.array(shot)
            img = _cv2.cvtColor(arr, _cv2.COLOR_BGRA2BGR)
            out_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            out_dir = _os.path.join(out_dir, "methods", "game")
            import time as _t
            fname = f"energo_step_turn_on_{int(_t.time()*100)%100000}.png"
            path = _os.path.join(out_dir, fname)
            _cv2.imwrite(path, img)
            log(f"Energo: фуллскрин {fname}", self.window_id)
        except Exception as e:
            log(f"Energo: фуллскрин не удался: {e}", self.window_id, level="DEBUG")
        await asyncio.sleep(DELAY_AFTER_CLICK_ENERGO)
        await asyncio.sleep(0.1)

        center_x = width // 2
        center_y = height // 2

        if self.settings.PEACE_MODE:
            peace_xy, peace_rgb = parseCBT("peace_off", profile=self.profile)
            if peace_xy is not None:
                peace = await self.profile.check_pixel(peace_xy, peace_rgb, timeout=0.2, thr=5)
                if peace:
                    await self.mouse.click(self.window_info, peace_xy[0], peace_xy[1])
                    log("Врубил мирку, была выключена", self.window_id)
                    await asyncio.sleep(0.15)

        await self.mouse.click(self.window_info, center_x, center_y)
        return True

    async def turn_off(self, ignore: bool = False) -> bool:
        window = self.window_info[self.window_id]
        width = window["Width"]
        height = window["Height"]

        running = self.profile.events_checker.get_running(self.window_id)
        health_was_on = MonitorType.HEALTH in running
        if health_was_on:
            self.profile.events_checker.stop_once(self.window_id, MonitorType.HEALTH)

        center_x = width // 2
        center_y = height // 2
        radius = 15

        points = []
        for i in range(7):
            angle = math.pi / 8 + 2 * math.pi * i / 5
            x = center_x + radius * math.cos(angle)
            y = center_y - radius * math.sin(angle)
            points.append((x, y))

        swipe_points = [points[0], points[2], points[0], points[5]]
        await self.mouse.swipe(self.window_info, swipe_points, delay_points=0.08)

        xy1, rgb1 = parseCBT("zalupka_gui", profile=self.profile)
        await asyncio.sleep(SLEEP_AFTER_UNBLOCK)
        if health_was_on:
            self.profile.events_checker.start_monitoring(
                self.window_id, self.profile, [MonitorType.HEALTH]
            )

        if ignore:
            return True

        if xy1 is None:
            log("Аук: zalupka_gui не найден в CBT — не могу проверить телепорт",
                self.window_id, level="WARNING")
            return False

        eth_err = await self.profile.errors.has_ethernet1()
        if eth_err:
            await self.profile.errors.close_ethernet1()
            await asyncio.sleep(3)

        thr = 17 if self.settings.REGION == Region.RU else 2
        teleported = await self.profile.check_pixel(xy1, rgb1, timeout=10, thr=thr)
        if teleported:
            return True

        if await self.is_on():
            repeat_points = [
                (center_x, center_y),
                (center_x - 75, center_y - 50),
            ]
            await self.mouse.swipe(self.window_info, repeat_points, delay_points=0.2)
            await asyncio.sleep(0.2)

        await asyncio.sleep(SLEEP_AFTER_UNBLOCK)
        teleported = await self.profile.check_pixel(xy1, rgb1, timeout=3)
        if teleported:
            return True

        return False

    async def check_lvl_up(self) -> bool:
        need = ["lvl_up_black_2", "lvl_up_black"]
        results = []
        for lvl_name in need:
            xy, rgb = parseCBT(lvl_name, profile=self.profile)
            if xy is None:
                results.append(False)
                continue
            results.append(await self.profile.check_pixel(
                xy, rgb, timeout=0.3, wsize="1x1", thr=1,
            ))

        if all(results):
            log("Лвл ап вылез, закрываю", self.window_id)
            xy_close, _ = parseCBT("lvl_up_close", profile=self.profile)
            if xy_close is None:
                return False
            await self.mouse.click(self.window_info, *xy_close)
            self.profile.notify("info", "Перс апнул лвл, будь во внимании и качни поинт!")
            await asyncio.sleep(1.3)
            return True

        log(f"Вероятно лвл апа не было {results}", self.window_id)
        return False

    async def has_quiver(self) -> bool | None:
        if not await self.is_on():
            return None
        xy1, rgb1 = parseCBT("q_quiver", profile=self.profile)
        if xy1 is None:
            return None
        quiver = await self.profile.check_pixel(xy1, rgb1, timeout=2, thr=2, wsize="1x1")
        return not quiver
