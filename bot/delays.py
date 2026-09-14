CLICK_DELAY = 0.12 # ЗАДЕРЖКА МЕЖДУ КЛИКАМИ, СНИЖАТЬ ПРИ БОЛЬШОМ ПИНГЕ НЕ РЕКОМЕНДУЮ
MOUSE_SCROLL = 0.05 # проебывает нпс - увеличивай, все ок = не трожь

# ЗАДЕРЖКИ (v5.0.7: ускорены — пользователь жаловался на долгие ожидания)

WAIT_BEFORE_START = 5 # было 10 — слишком долго ждём перед запуском профиля

SLEEP_AFTER_CONNECT = 15 # было 24 — после входа на сервер
SLEEP_AFTER_UNBLOCK = 1.0 # было 1.5 — после разблокировки окна
DELAY_CHECK_ENERGO = 1.5 # было 2.3 — проверка энерго режима
DELAY_WAIT_AUCTION = 2 # было 5 — ожидание после клика по "аукцион" (есть _wait_auction_loaded с polling)
DELAY_WAIT_ADENA_SHOP_ADD = 4 # было 6 — реклама в донат шопе
DELAY_WAIT_ADENA_SHOP_GOOGLE = 4 # было 6 — привязка гугла (япония)
DELAY_CHECK_NPC_POSITIONS = 1.5 # было 2 — проверка ВСЕХ нпс в городе
DELAY_TELEPORT_TO_HOME = 3.4 # НЕ ТРОГАТЬ — критичная задержка для wait_teleport
WAIT_BEFORE_TELEPORT_TO_SPOT = 2.0 # было 3.1 — между автобоем и кнопкой спотов
DELAY_AUTOHUNT_CHECK = 4 # было 6 — проверка автоохоты
PVP_CHECK_DELAY = 0.15 # раз в сколько секунд проверяем пвп триггер (2 меча)
DELAY_WAIT_WAIT_TELEPORT = 2.0 # было 3.2 — перед проверкой телепортнулись
DELAY_AFTER_CLICK_ENERGO = 3 # было 5 — между кликами при блокировке окна
SLEEP_AFTER_CLAIM_ACHIVMENTS = 0.1 # задержка между кликами по "Собрать"
MAX_CLAIM_ACHIEVEMENTS = 150 # максимальное число попыток сбора за один заход

CHECKS_HP_BANK = 8 # скок всего раз смотрим на цвет банки
CHECKS_HP_BANK_TRIGGER = 6 # при скольки успешных срабатываем
CHECKS_HP_BANK_TIMEOUT = 0.5 # было 0.7 — сколько секунд ждем нужного цвета банки

# ПОРОГИ

THR_CHECK_NPC_POSITIONS = 3 # максимальный трешхолд на проверку нпс
THR_CHECK_AUTOHUNT = 27 # включенный автобой
