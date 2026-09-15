import json
import os
import time
import keyboard

from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QPoint, QSize
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QDialog,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from bot.controller import ProfileController
from bot.utils import findAllWindows
from bot.windows.settings_loader import load_settings
from bot.clogger import log
from gui.cache import load_cache, save_cache
from gui.single import WindowControlDialog
from gui.alch_gui import AlchemyDialog
from gui.alch_presets import PresetDialog
from gui.settings_changer import SettingsChanger
from gui.styles import STYLE, UPD
from gui.donate import Donate
from gui.tiling import TilingDialog
from gui.windows_selector import WorkAccs
from gui.windows_selector import load_workaccs
from gui.region_selector import Selector
from bot.updater import needs_update, update, get_my_version


PROJECT_ROOT = os.getcwd()
WINDOWS_CACHE = os.path.join(PROJECT_ROOT, "settings", "gui", "windows_cache.json")
FAVICON = os.path.join(os.path.dirname(__file__), 'images', 'favicon.ico')


class UpdateChecker(QThread):
    update_available = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True

    def run(self):
        log("Запустил чекер обнов")
        while self._running:
            try:
                log("Проверяю обновы...")
                if needs_update():
                    log("Доступна обнова! Спавню кнопку")
                    self.update_available.emit()
                else:
                    log(f"Установлена последняя версия бота | {get_my_version()}")
            except Exception:
                pass
            # Проверка раз в 30 секунд (было 60) — пользователь видит кнопку быстрее
            for _ in range(30):
                if not self._running:
                    break
                time.sleep(1)

    def stop(self):
        log("Стопнул чекер обнов")
        self._running = False


class LogUploader(QThread):
    """
    Периодически (раз в 60 сек) загружает logs/log.log + debug PNG в ветку
    bot-logs. Даже если бот упал и finally не сработал — логи всё равно уйдут.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = True

    def run(self):
        import traceback
        log("Запустил периодический загрузчик логов")
        # Первая загрузка через 30 сек (даём боту время стартовать)
        for _ in range(30):
            if not self._running:
                return
            time.sleep(1)
        while self._running:
            try:
                from bot.log_uploader import upload_run_logs
                log("LogUploader: запускаю upload_run_logs...")
                upload_run_logs("periodic", made=-1, error=None)
                log("LogUploader: upload_run_logs завершён")
            except Exception as e:
                tb = traceback.format_exc()
                log(f"LogUploader: ошибка: {e}\n{tb}", level="ERROR")
            # Раз в 60 секунд
            for _ in range(60):
                if not self._running:
                    return
                time.sleep(1)

    def stop(self):
        log("Стопнул загрузчик логов")
        self._running = False


class NedoGui(QWidget):
    _stop_signal = pyqtSignal()

    def __init__(self, kb: str, m: str):
        super().__init__()
        if m is not None:
            self.setWindowTitle(f"L2Mauto | Клава {kb} | Мышь {m}")
        else:
            # жаль никогда не случится =(
            self.setWindowTitle("L2Monad | Драйвер не найден!")

        self.resize(400, 150)
        self.setMinimumWidth(50)
        self.setWindowIcon(QIcon(FAVICON))
        self.controller = ProfileController()
        self.cache = load_cache()
        self.profiles = self.controller.profiles
        self.load_window_position()
        self.init_ui()
        self._stop_signal.connect(self.stop_profile)
        keyboard.add_hotkey("F10", self._stop_signal.emit)
        self.update_checker = UpdateChecker()
        self.update_checker.update_available.connect(self.show_update_button)
        self.update_checker.start()
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_state)
        self.update_timer.start(1000)

        # ── ПЕРИОДИЧЕСКАЯ ЗАГРУЗКА ЛОГОВ в GitHub (раз в 60 сек) ──────────
        # Даже если бот упал и finally не сработал — логи всё равно уйдут.
        # Запускается в отдельном потоке (LogUploader QThread).
        self.log_uploader_thread = LogUploader()
        self.log_uploader_thread.start()

    def load_window_position(self):
        if os.path.exists(WINDOWS_CACHE):
            try:
                with open(WINDOWS_CACHE, "r") as f:
                    data = json.load(f)
                pos = data.get("main", {}).get("pos")
                size = data.get("main", {}).get("size")
                if pos:
                    self.move(QPoint(pos[0], pos[1]))
                if size:
                    self.resize(QSize(size[0], size[1]))
            except:
                pass

    def save_window_position(self):
        data = {"main": {}, "single": {}}
        if os.path.exists(WINDOWS_CACHE):
            try:
                with open(WINDOWS_CACHE, "r") as f:
                    data = json.load(f)
            except:
                pass
        data["main"]["pos"] = [self.pos().x(), self.pos().y()]
        data["main"]["size"] = [self.size().width(), self.size().height()]
        os.makedirs(os.path.dirname(WINDOWS_CACHE), exist_ok=True)
        with open(WINDOWS_CACHE, "w") as f:
            json.dump(data, f, indent=2)

    def closeEvent(self, event):
        try:
            self.save_window_position()
        except Exception:
            pass
        try:
            self.stop_profile()
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and self.controller.bot_manager.bots:
                time.sleep(0.05)
            self.controller.loop.call_soon_threadsafe(self.controller.loop.stop)
        except Exception:
            pass
        if hasattr(self, 'update_checker') and self.update_checker.isRunning():
            self.update_checker.stop()
            self.update_checker.wait(100)
        if hasattr(self, 'log_uploader_thread') and self.log_uploader_thread.isRunning():
            self.log_uploader_thread.stop()
            self.log_uploader_thread.wait(100)
        # FIX: F10 hotkey registered in __init__ via keyboard.add_hotkey was
        # never removed — leaving a dangling callback that could fire on a
        # destroyed QWidget. Remove it defensively before close.
        try:
            keyboard.remove_hotkey("F10")
        except Exception:
            pass
        super().closeEvent(event)

    def init_ui(self):
        self.layout_main = QVBoxLayout()
        font_btn = QFont("Segoe UI", 9, QFont.Bold)

        # ── Заголовок ───────────────────────────────────────────────────────
        self.title_label = QLabel("🏰 L2Mauto")
        self.title_label.setObjectName("title")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.layout_main.addWidget(self.title_label)

        self.btn_otdel = QPushButton("📋 Отдельное управление")
        self.btn_otdel.setFont(font_btn)
        self.btn_otdel.setCursor(Qt.PointingHandCursor)
        self.btn_otdel.setFixedHeight(28)
        self.btn_otdel.clicked.connect(self.open_otdel)
        self.layout_main.addWidget(self.btn_otdel)

        # Маппинг имён профилей в русские подписи кнопок.
        # Ключ — имя класса профиля (как в self.profiles).
        # Значение — русский текст кнопки.
        PROFILE_LABELS = {
            "Auction":      "Аукцион",
            "Dungeon":      "Данжи",
            "MainAlchemy":  "Химка",
            "PvPDodge":     "ПВП",
            "Rewards":      "Бонусы",
            "Scheduler":    "Шедуля",
            "BuyerProfile": "Байер",
        }

        for name, cls in self.profiles.items():
            # Русская подпись из маппинга, если нет — само имя класса
            label = PROFILE_LABELS.get(name, name)
            btn = QPushButton(f"▶ {label}")
            btn.setFont(font_btn)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(28)
            # Сохраняем имя класса профиля в свойстве кнопки — для подсчёта
            # активных окон (метод _update_running_counters ниже).
            btn.setProperty("profile_name", name)

            if name == "MainAlchemy":
                btn.clicked.connect(lambda _, c=cls: self.start_alchemy(c))
            else:
                btn.clicked.connect(lambda _, c=cls: self.start_all(c))

            self.layout_main.addWidget(btn)

        # ── СТОП — красная, крупная ────────────────────────────────────────
        self.btn_stop_all = QPushButton("⏹ СТОП")
        self.btn_stop_all.setObjectName("stop_all")
        self.btn_stop_all.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.btn_stop_all.setCursor(Qt.PointingHandCursor)
        self.btn_stop_all.setFixedHeight(32)
        self.btn_stop_all.clicked.connect(self.stop_profile)
        self.layout_main.addWidget(self.btn_stop_all)

        layout_mini = QHBoxLayout()

        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setFixedSize(32, 32)
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.clicked.connect(self.open_settings)
        layout_mini.addWidget(self.btn_settings, alignment=Qt.AlignLeft)

        self.windows_sel = QPushButton("👤")
        self.windows_sel.setFixedSize(32, 32)
        self.windows_sel.setCursor(Qt.PointingHandCursor)
        self.windows_sel.clicked.connect(self.winsel)
        layout_mini.addWidget(self.windows_sel, alignment=Qt.AlignLeft)

        self.don = QPushButton("💰")
        self.don.setFixedSize(32, 32)
        self.don.setCursor(Qt.PointingHandCursor)
        self.don.clicked.connect(self.donate)
        layout_mini.addWidget(self.don, alignment=Qt.AlignLeft)

        self.btn_tiling = QPushButton("📐")
        self.btn_tiling.setFixedSize(32, 32)
        self.btn_tiling.setCursor(Qt.PointingHandCursor)
        self.btn_tiling.clicked.connect(self.open_tiling)
        layout_mini.addWidget(self.btn_tiling, alignment=Qt.AlignLeft)

        version = QLabel(f"v{get_my_version()}")
        version.setStyleSheet("color: #6e7681; font-size: 8pt;")
        version.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout_mini.addWidget(version, stretch=1)

        self.layout_main.addLayout(layout_mini)

        self.setLayout(self.layout_main)
        self.setStyleSheet(STYLE)

        def _deferred_check():
            try:
                if needs_update():
                    self.show_update_button()
            except Exception:
                pass
        QTimer.singleShot(0, _deferred_check)

    def start_alchemy(self, profile_class):
        dlg = AlchemyDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return

        selected = dlg.get_selected()
        if not selected:
            QMessageBox.information(self, "Info", "Окна не выбраны")
            return

        preset_dlg = PresetDialog(self)
        if preset_dlg.exec_() != QDialog.Accepted:
            return

        preset = preset_dlg.get_selected()
        if not preset:
            QMessageBox.information(self, "Info", "Пресет не выбран")
            return

        windows_map = dlg.windows
        nicks = [nick for nick in selected if nick in windows_map]
        if not nicks:
            QMessageBox.information(self, "Info", "Выбранные окна не найдены")
            return

        new_windows = [nick for nick in nicks if load_settings(nick) is None]
        if new_windows:
            regions = self.ask_region(new_windows)
            for nick, region in regions.items():
                load_settings(nick, region=region)

        total_slots = sum(mon["grid_all"] for mon in dlg.monitors["monitors"])
        last_value = self.cache.get("AlchemyConcurrent", 1)
        max_active, ok = QInputDialog.getInt(
            self, "Очередь алхимики",
            f"Сколько окон крутить одновременно? (1-{total_slots})",
            last_value, 1, total_slots
        )
        if not ok:
            return

        self.cache["AlchemyConcurrent"] = max_active
        save_cache(self.cache)

        self._alchemy_pending = nicks.copy()
        self._alchemy_running = set()
        self._alchemy_profile_class = profile_class
        self._alchemy_preset = preset
        self._alchemy_max_active = max_active

        if not hasattr(self, "_alchemy_timer"):
            from PyQt5.QtCore import QTimer
            self._alchemy_timer = QTimer(self)
            self._alchemy_timer.timeout.connect(self._alchemy_check)
            self._alchemy_timer.start(1000)

        self.controller.reset_batch_cancel()
        self._alchemy_start()

    def _alchemy_start(self):
        if self.controller.batch_cancelled:
            return
        while len(
                self._alchemy_running) < self._alchemy_max_active and self._alchemy_pending:
            nick = self._alchemy_pending.pop(0)
            self.start_windows(self._alchemy_profile_class, [nick],
                               preset=self._alchemy_preset)
            self._alchemy_running.add(nick)

    def _alchemy_check(self):
        if self.controller.batch_cancelled:
            self._alchemy_pending.clear()
            self._alchemy_running.clear()
            self._alchemy_timer.stop()
            return

        finished = {nick for nick in self._alchemy_running if
                    not self.controller.is_running(nick)}

        if finished:
            self._alchemy_running.difference_update(finished)
            self._alchemy_start()

        if not self._alchemy_pending and not self._alchemy_running:
            self._alchemy_timer.stop()

    def open_settings(self):
        self.settings_win = SettingsChanger()
        self.settings_win.setWindowModality(Qt.NonModal)
        self.settings_win.show()

    def winsel(self):
        dlg = WorkAccs(self)
        dlg.exec_()

    def donate(self):
        dlg = Donate(self)
        dlg.exec_()

    def open_tiling(self):
        dlg = TilingDialog(self)
        dlg.exec_()

    def open_otdel(self):
        self.dlg = WindowControlDialog(self)
        self.dlg.show()

    def start_windows(self, profile_class, nicks, **kwargs):
        self.controller.start_windows(profile_class, nicks, **kwargs)

    def stop_windows(self, nicks):
        self.controller.stop_windows(nicks)

    def start_all(self, profile_class):
        # FIX: Concurrent start_all calls (e.g. user double-clicks a profile
        # button) would schedule two independent batch chains via QTimer,
        # doubling window launches and corrupting shared state
        # (_batch_stop, _skipped_windows). Guard with a re-entrancy flag.
        if getattr(self, "_batch_running", False):
            log("start_all: уже идёт прогон, игнорирую повторный вызов",
                level="WARNING")
            return

        windows = list(findAllWindows().keys())
        if not windows:
            QMessageBox.information(self, "Info", "Окон не найдено")
            return

        work = load_workaccs()
        enabled = set(work.get("enabled", []))
        windows = [w for w in windows if w in enabled]

        if not windows:
            QMessageBox.information(self, "Info", "Готовых к запуску окон не найдено\nНастрой их в кнопке на 1 правее настроек!")
            return

        new_windows = [nick for nick in windows if load_settings(nick) is None]
        if new_windows:
            regions = self.ask_region(new_windows)
            for nick, region in regions.items():
                load_settings(nick, region=region)

        profile_name = profile_class.__name__

        if profile_name == "PvPDodge":
            self.start_windows(profile_class, windows)
            return

        # Для Auction — диалог выбора кол-ва окон (как у всех профилей).
        # Дефолт = 2 (проверено, работает). Пользователь может выбрать 1, 2, 3 или 4.
        # 4 окна — экспериментально, возможно перекрытие.
        last_value = self.cache.get(profile_name, 2)
        num, ok = QInputDialog.getInt(
            self, "Батчер для ВСЕХ",
            f"Сколько окон запускать одновременно для {profile_name}?",
            last_value, 1
        )
        if not ok:
            return
        self.cache[profile_name] = num
        save_cache(self.cache)

        batches = [windows[i:i + num] for i in range(0, len(windows), num)]
        self.controller.reset_batch_cancel()
        self._batch_stop = False  # флаг жёсткой остановки process_batch
        self._skipped_windows = []  # окна которые не загрузились (Поиск информации)
        # FIX: re-entrancy flag — set True here, cleared at every exit point
        # of process_batch / wait_c / wait_f / stop_profile.
        self._batch_running = True

        # Запоминаем время старта всего прогона — для финального отчёта.
        # `time` уже импортирован в начале модуля, отдельный алиас не нужен.
        _run_start_ts = time.monotonic()

        def process_batch(batch_idx=0):
            if batch_idx >= len(batches):
                # Все пачки прошли — проверяем пропущенные окна
                if self._skipped_windows and not getattr(self, '_batch_stop', False):
                    log(f"Прогон завершён. Повторяю {len(self._skipped_windows)} пропущенных окон: {self._skipped_windows}")
                    retry_windows = self._skipped_windows.copy()
                    self._skipped_windows.clear()
                    retry_batches = [retry_windows[i:i + num] for i in range(0, len(retry_windows), num)]
                    batches.extend(retry_batches)
                    QTimer.singleShot(5000, lambda: process_batch(batch_idx))
                else:
                    # Финал — всё прошло, пропущенных нет
                    total_sec = time.monotonic() - _run_start_ts
                    log(f"Прогон завершён за {total_sec:.0f}с ({total_sec/60:.1f} мин). "
                        f"Пачек: {batch_idx}.")
                    # FIX: re-entrancy guard released at natural end of run
                    self._batch_running = False
                return
            if self.controller.batch_cancelled:
                # FIX: re-entrancy guard released on cancel
                self._batch_running = False
                return
            if getattr(self, '_batch_stop', False):
                log(f"start_all: СТОП — process_batch прерван (batch_idx={batch_idx})")
                # FIX: re-entrancy guard released on hard stop
                self._batch_running = False
                return

            batch = batches[batch_idx]
            # Лог старта пачки — пользователь видит прогресс в консоли
            log(f"Пачка {batch_idx + 1}/{len(batches)}: старт ({len(batch)} окон: {batch})")
            _batch_start_ts = time.monotonic()
            self.start_windows(profile_class, batch)

            def wait_c(attempts=0):
                if self.controller.batch_cancelled or self._batch_stop:
                    # FIX: re-entrancy guard released on early exit
                    self._batch_running = False
                    return
                stalled = [nick for nick in batch
                           if self.controller.bot_manager.get_bot(nick) is None]
                if not stalled:
                    wait_f()
                    return
                # 16 попыток × 500ms = 8 сек.
                if attempts >= 16:
                    log(f"Пачка {batch_idx + 1}: не завелись {stalled} за 8 сек, пропускаю дальше", level="WARNING")
                    wait_f()
                    return
                QTimer.singleShot(500, lambda: wait_c(attempts + 1))

            def wait_f(attempts=0):
                if self.controller.batch_cancelled or getattr(self, '_batch_stop', False):
                    # FIX: re-entrancy guard released on early exit
                    self._batch_running = False
                    return
                running = [nick for nick in batch
                           if self.controller.is_running(nick)]
                if not running:
                    # Тройная проверка стопа
                    if getattr(self, '_batch_stop', False):
                        log(f"start_all: СТОП — wait_f прерван перед batch {batch_idx + 1}")
                        # FIX: re-entrancy guard released on hard stop
                        self._batch_running = False
                        return
                    if self.controller.batch_cancelled:
                        # FIX: re-entrancy guard released on cancel
                        self._batch_running = False
                        return
                    # Лог завершения пачки — пользователь видит прогресс в консоли
                    _batch_dur = time.monotonic() - _batch_start_ts
                    log(f"Пачка {batch_idx + 1}/{len(batches)}: завершена за {_batch_dur:.0f}с")
                    # Пауза 1 сек между пачками
                    def _start_next():
                        if getattr(self, '_batch_stop', False):
                            log(f"start_all: СТОП — _start_next прерван перед batch {batch_idx + 1}")
                            # FIX: re-entrancy guard released on hard stop
                            self._batch_running = False
                            return
                        process_batch(batch_idx + 1)
                    QTimer.singleShot(1000, _start_next)
                    return
                # НЕТ таймаута — ждём пока пачка не закончит.
                QTimer.singleShot(1000, lambda: wait_f(attempts + 1))

            wait_c()
        process_batch()

    def stop_profile(self):
        """ЖЁСТКАЯ остановка всего. Один клик — всё встанет."""
        try:
            log(f"СТОП ВСЕ: нажато, останавливаю...")
            # 1. ЖЁСТКИЙ флаг — убивает цепочку process_batch/wait_c/wait_f
            self._batch_stop = True
            self.controller.cancel_batch()

            # 2. Остановить алхимию если была
            if hasattr(self, '_alchemy_timer') and self._alchemy_timer.isActive():
                self._alchemy_timer.stop()
            if hasattr(self, '_alchemy_pending'):
                self._alchemy_pending.clear()
            if hasattr(self, '_alchemy_running'):
                self._alchemy_running.clear()

            # 3. Остановить ВСЕ запущенные боты — копируем список, т.к. он меняется
            nicks = list(self.controller.bot_manager.bots.copy())
            log(f"СТОП ВСЕ: останавливаю {len(nicks)} окон: {nicks}")
            if nicks:
                self.stop_windows(nicks)

            # 4. Очистить список пропущенных
            if hasattr(self, '_skipped_windows'):
                self._skipped_windows.clear()

            # FIX: re-entrancy guard released on manual stop — start_all may
            # be invoked again immediately after the user hits STOP.
            self._batch_running = False

            log(f"СТОП ВСЕ: команда отправлена, _batch_stop={self._batch_stop}")
        except Exception as e:
            log(f"СТОП ВСЕ: exception: {e}", level="ERROR")
            import traceback
            log(traceback.format_exc(), level="ERROR")
            self._batch_stop = True
            self.controller.cancel_batch()

    def ask_region(self, new_windows: list[str]) -> dict[str, str]:
        dlg = Selector(new_windows, self)
        if dlg.exec_() == QDialog.Accepted:
            return dlg.get_regions()

        return {nick: "RU" for nick in new_windows}

    def update_state(self):
        try:
            active = list(self.controller.bot_manager.bots.values())
        except Exception:
            return
        running = {}

        for bot in active:
            profile_name = type(bot).__name__
            running[profile_name] = running.get(profile_name, 0) + 1

        for i in range(self.layout_main.count()):
            item = self.layout_main.itemAt(i)
            # FIX: itemAt may return None for empty/spacer slots — without
            # this guard, item.widget() raises AttributeError and crashes
            # the 1-second QTimer that drives the running counters.
            if item is None:
                continue
            w = item.widget()
            if isinstance(w, QPushButton):
                # Профильная кнопка — у неё есть свойство profile_name
                prof_name = w.property("profile_name")
                if prof_name is None:
                    continue
                # Базовый текст без счётчика «(N)»
                base_text = w.text().split(" (")[0]
                count = running.get(prof_name, 0)
                w.setText(f"{base_text} ({count})")

    def show_update_button(self):
        if hasattr(self, 'btn_update'):
            return

        self.btn_update = QPushButton("♿️ Доступна обнова! (жми)")
        self.btn_update.setCursor(Qt.PointingHandCursor)
        self.btn_update.setFixedHeight(18)
        self.btn_update.setFixedWidth(180)
        self.btn_update.setStyleSheet(UPD)
        self.btn_update.clicked.connect(self.show_update)
        self.layout().addWidget(self.btn_update, alignment=Qt.AlignRight)

    def show_update(self):
        reply = QMessageBox.question(
            self,
            "Обнова!",
            "Качаем и ставим?\n\nСохраненный бэкап будет в папочке /backups",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            msg = QMessageBox(self)
            msg.setWindowTitle("Обнове быть!")
            msg.setText("Все гуд, бот сам перезапустится через несколько секунд\nТекущее окно зависнет, НЕ ТРОГАЙ ЕГО")
            msg.setStandardButtons(QMessageBox.Ok)
            msg.setModal(False)
            msg.show()
            # Запускаем update() в отдельном потоке — иначе requests.get
            # блокирует event loop и GUI зависает на 30 сек (до 30 сек
            # скачивание ZIP). Пользователь видит «не обновляется».
            from PyQt5.QtCore import QThread
            class _UpdaterThread(QThread):
                def run(self):
                    try:
                        from bot.updater import update
                        update()
                    except Exception as e:
                        log(f"show_update: updater thread exception: {e}",
                            level="ERROR")
            self._updater_thread = _UpdaterThread()
            self._updater_thread.start()