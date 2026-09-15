import atexit
import logging
import logging.handlers
import os
import queue as _queue
from logging.handlers import RotatingFileHandler
import colorlog
from bot.constans import LOG_DIR

os.makedirs(LOG_DIR, exist_ok=True)

LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

_LOG_QUEUE_MAXSIZE = 10000
_file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
_color_formatter = colorlog.ColoredFormatter(
    '%(log_color)s%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    log_colors={
        'DEBUG': 'cyan',
        'INFO': 'green',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }
)

# ──────────────────────────────────────────────────────────────────────────
# ФИЛЬТР КОНСОЛИ — что показывать в окне cmd, а что только в файл
# ──────────────────────────────────────────────────────────────────────────
# Пользователь читает окно cmd.exe (stdout). Раньше туда лилось ВСЁ —
# DEBUG, WARNING, построчные детали аукциона, фоновый энергорежимный цикл
# каждые 94 сек. Невозможно увидеть когда прогон закончился.
#
# Теперь: в файл идёт ВСЁ (как было), в stdout — только важное.
# Фильтр по whitelist паттернов (substring match, case-sensitive).
#
# ВАЖНОЕ = старт/конец прогона, старт/конец предмета, результат, ошибки,
# пачки, обновы. Мусор (сохранения PNG, OCR DEBUG, свайпы, page-by-page
# TM scores, log_uploader, needs_update DEBUG, фоновый энергорежим) —
# только в файл.
# ──────────────────────────────────────────────────────────────────────────

_CONSOLE_WHITELIST = (
    # ── Прогон аукциона: ключевые точки ──────────────────────────────────
    "Аук: запущен relist",            # старт прогона окна
    "Аук: загрузился",                # аукцион прогрузился
    "Аук: вкладка Продажа открыта",   # вкладка открыта
    "Аук: предмет ",                  # старт предмета N/10
    "Аук: лот снят",                  # лот снят с продажи
    "Аук: предмет найден и подтверждён",  # успех поиска
    "Аук: предмет не найден",         # FAIL поиска
    "Аук: ошибка на предмете",         # ERROR стоп
    "Аук: аук закрыт",                # аук закрыт
    "Аук: окно уложено спать",        # прогон завершён (успех или empty)
    "Аук: нечего переставлять",       # финал — нечего делать
    "Аук: OCR цена =",                # прочитана цена
    "Аук: моя цена =",                # цена минус 1
    "Аук: введена цена",              # цена введена
    "Аук: окно подтверждения появилось",
    "Аук: вижу кнопку",                # Отмена/Забрать найдена
    "Аук: первый лот в статусе",      # пропуск (Продаётся)
    "Аук: статус = «Продано»",         # лот продан → Забрать (не Продаётся)
    "Аук: энерго НЕ включился за 3",  # критич — энерго не встало
    "Аук: список лотов пуст",         # пустой список
    "Шось сломалось",                 # финальный статус прогона
    "Прогон завершён",                # все пачки прошли
    "Пропущенных окон",               # возврат к пропущенным

    # ── Пачки ───────────────────────────────────────────────────────────
    "Пачка ",                          # "Пачка N: не завелись"
    "start_all: СТОП",                 # стоп пачки
    "start_all: ПАЧКА",               # таймаут пачки (если будет)

    # ── СТОП ────────────────────────────────────────────────────────────
    "СТОП ВСЕ",                       # пользователь нажал стоп
    "стопнут пользователем",          # CancelledError
    "Профиль остановлен вручную",

    # ── Обновления ──────────────────────────────────────────────────────
    # ВАЖНО: «Доступна обнова» и «needs_update: local=» убраны из консоли —
    # появляются каждые 30 сек и мешают читать прогресс прогона. Пользователь
    # видит саму кнопку обновы в GUI — этого достаточно. Вся инфа по обновам
    # идёт в файл лога (и в GitHub bot-logs) — для отладки.
    "Накатил обнпату",                # старт применения обновы
    "Обнова бахнула",                 # ошибка применения обновы
    "Обнова:",                        # прогресс скачивания/распаковки ZIP

    # ── Запуск/остановка профиля ────────────────────────────────────────
    "Запуск профиля",                 # запуск (любой профиль)
    "main_loop завершился",           # завершение (любой профиль)
    "dodger stopped",
    "Schedule запущен",
    "Энерго включён, профиль завершён",
    "Расписание уже запущено",        # Шедуля: окно уже в расплании → выход+сон
    "Шедуля: клик выхода",            # Шедуля: клик по стрелочке выхода
    "Шедуля: окно уложено спать",      # Шедуля: финал после выхода из меню
    "Кнопка «Начать расписание»",     # Шедуля: не нашёл schedule_start

    # ── Ошибки (всегда в консоль) ───────────────────────────────────────
    # ERROR и CRITICAL уровни пропускаются безусловно (см. _console_filter)
)

# Чёрный список — даже если level ERROR, не показывать эти паттерны
# (потому что они дублируют то что уже в whitelist, или это технический шум)
_CONSOLE_BLACKLIST = (
    "log_uploader:",                  # технический шум загрузки логов
    "_api_put:",                       # HTTP запросы
    "Находимся в энергорежиме",       # фоновый checker каждые 94 сек
    "Не находимся в энерго",          # фоновый checker
    "Аук: энерго не включился (попытка",  # промежуточные попытки (финал в whitelist)
    "Аук: сохранил позицию",          # технический шаг
    "Аук: выбрал позицию",            # технический шаг
    "Аук: окно в рабочем размере",    # технический шаг
    "Аук: окно возвращено",           # технический шаг
    "Аук: принудительный resize",      # технический шаг
    "Аук: сохранён ",                  # save_debug PNG
    "Аук: сохранён фулл-скрин",        # take_fullscreen
    "Аук: SIFT образец",              # SIFT keypoints (DEBUG)
    "Аук: статус лота OCR",           # OCR raw text (DEBUG)
    "Аук: статус зелёных пикселей",   # green pixels (DEBUG)
    "Аук: OCR вернул пусто",          # WARNING — мусор
    "Аук: клик Отмена лота",           # промежуточный клик
    "Аук: клик ОК отмены",            # промежуточный клик
    "Аук: ОК сработал с попытки",      # промежуточный
    "Аук: окно подтверждения",          # промежуточный
    "Аук: свайп инвентаря",            # свайп
    "Аук: сканирую страницу",          # страница
    "Аук: стр ",                       # TM scores (DEBUG)
    "Аук: ищу предмет",                # старт поиска
    "Аук: log_uploader запущен",       # технический
    "Аук: не удалось сохранить",        # save_debug fail
    "Аук: _ensure_foreground",          # технический
    "Аук: _find_red_dots",             # exception
    "Аук: green check failed",          # exception
    "Аук: OCR статуса не удался",       # exception
    "LogUploader:",                    # периодический загрузчик
    "запускаю upload_run_logs",         # периодический
    "upload_run_logs завершён",         # периодический
    "не загружен",                     # PNG upload fail
    "debug PNG не найдены",            # PNG cleanup
    "не смог прочитать",               # token read fail
    "Проверяю обновы",                 # периодическая проверка (30 сек)
    "Доступна обнова",                  # спам кнопки каждые 30 сек
    "Установлена последняя версия",     # каждые 30 сек
    "needs_update:",                    # DEBUG/WARNING каждые 30 сек
    "не смог перевыставить",            # дублирует "Шось сломалось"
)


class _ConsoleFilter(logging.Filter):
    """
    Пропускать в stream_handler (stdout) только важные сообщения.
    Файл получает ВСЁ (без фильтра).
    """
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return False

        # CRITICAL — всегда показывать
        if record.levelno >= logging.CRITICAL:
            return True

        # Сначала чёрный список — если совпало, НЕ показывать
        # (даже ERROR — потому что это технический шум типа log_uploader)
        for bad in _CONSOLE_BLACKLIST:
            if bad in msg:
                return False

        # ERROR — показывать (если не в чёрном списке)
        if record.levelno >= logging.ERROR:
            return True

        # WARNING — показывать только если не в чёрном списке
        # (большинство WARNING — мусор типа "OCR вернул пусто")
        if record.levelno >= logging.WARNING:
            return True

        # INFO/DEBUG — показывать только если в whitelist
        for good in _CONSOLE_WHITELIST:
            if good in msg:
                return True

        return False


_stream_handler = colorlog.StreamHandler()
_stream_handler.setLevel(logging.DEBUG)
_stream_handler.setFormatter(_color_formatter)
_stream_handler.addFilter(_ConsoleFilter())

_logger_cache: dict = {}
_file_handlers: dict = {}
_listeners: dict = {}


def _make_file_handler(log_filename: str) -> RotatingFileHandler:
    handler = _file_handlers.get(log_filename)
    if handler is not None:
        return handler
    handler = RotatingFileHandler(
        os.path.join(LOG_DIR, log_filename),
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding='utf-8',
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(_file_formatter)
    _file_handlers[log_filename] = handler
    return handler


def setup_logger(log_filename: str) -> logging.Logger:
    cached = _logger_cache.get(log_filename)
    if cached is not None:
        return cached

    logger = logging.getLogger(log_filename)
    if not logger.hasHandlers():
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        log_queue: _queue.Queue = _queue.Queue(maxsize=_LOG_QUEUE_MAXSIZE)
        queue_handler = logging.handlers.QueueHandler(log_queue)
        queue_handler.setLevel(logging.DEBUG)
        logger.addHandler(queue_handler)

        file_handler = _make_file_handler(log_filename)
        listener = logging.handlers.QueueListener(
            log_queue,
            file_handler,
            _stream_handler,
            respect_handler_level=True,
        )
        listener.start()
        _listeners[log_filename] = listener

    _logger_cache[log_filename] = logger
    return logger


def _shutdown_listeners() -> None:
    for listener in list(_listeners.values()):
        try:
            listener.stop()
        except Exception:
            pass
    _listeners.clear()


atexit.register(_shutdown_listeners)


def log(message, context="global", level="INFO"):
    if context == "global":
        log_filename = "log.log"
    else:
        log_filename = f"{context}.log"

    logger = setup_logger(log_filename)

    if level == "INFO":
        logger.info(f"[{context}] {message}")
    elif level == "WARNING":
        logger.warning(f"[{context}] {message}")
    elif level == "ERROR":
        logger.error(f"[{context}] {message}")
    elif level == "DEBUG":
        logger.debug(f"[{context}] {message}")
    else:
        logger.info(f"[{context}] {message}")
