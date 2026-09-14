CLICK_DELAY = 0.12 # ЗАДЕРЖКА МЕЖДУ КЛИКАМИ, СНИЖАТЬ ПРИ БОЛЬШОМ ПИНГЕ НЕ РЕКОМЕНДУЮ
MOUSE_SCROLL = 0.05 # проебывает нпс - увеличивай, все ок = не трожь

# ЗАДЕРЖКИ (v5.1.5: умеренные — не слишком быстрые, не слишком медленные)
# Прошлая версия 5.0.7 была слишком быстрой, на лагающих ПК не успевало
# открыть вкладку Продажа → бот думал «нечего переставлять» и выходил.

WAIT_BEFORE_START = 3 # было 8 — слишком долго ждём перед запуском профиля. wait_c даёт 10 сек на старт.

SLEEP_AFTER_CONNECT = 18 # было 15 → 18 (с запасом на медленный коннект)
SLEEP_AFTER_UNBLOCK = 1.2 # было 1.0 → 1.2 (чуть медленнее, надёжнее)
DELAY_CHECK_ENERGO = 1.8 # было 1.5 → 1.8
DELAY_WAIT_AUCTION = 3 # было 2 → 3 (есть _wait_auction_loaded с polling 60с)
DELAY_WAIT_ADENA_SHOP_ADD = 5 # было 4 → 5
DELAY_WAIT_ADENA_SHOP_GOOGLE = 5 # было 4 → 5
DELAY_CHECK_NPC_POSITIONS = 1.8 # было 1.5 → 1.8
DELAY_TELEPORT_TO_HOME = 3.4 # НЕ ТРОГАТЬ — критичная задержка для wait_teleport
WAIT_BEFORE_TELEPORT_TO_SPOT = 2.5 # было 2.0 → 2.5
DELAY_AUTOHUNT_CHECK = 5 # было 4 → 5
PVP_CHECK_DELAY = 0.15 # раз в сколько секунд проверяем пвп триггер (2 меча)
DELAY_WAIT_WAIT_TELEPORT = 2.5 # было 2.0 → 2.5
DELAY_AFTER_CLICK_ENERGO = 3.5 # было 3 → 3.5
SLEEP_AFTER_CLAIM_ACHIVMENTS = 0.1 # задержка между кликами по "Собрать"
MAX_CLAIM_ACHIEVEMENTS = 150 # максимальное число попыток сбора за один заход

CHECKS_HP_BANK = 8 # скок всего раз смотрим на цвет банки
CHECKS_HP_BANK_TRIGGER = 6 # при скольки успешных срабатываем
CHECKS_HP_BANK_TIMEOUT = 0.6 # было 0.5 → 0.6

# ПОРОГИ

THR_CHECK_NPC_POSITIONS = 3 # максимальный трешхолд на проверку нпс
THR_CHECK_AUTOHUNT = 27 # включенный автобой
