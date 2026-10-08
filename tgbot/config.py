from dataclasses import dataclass
from configparser import ConfigParser
from pathlib import Path
import sys

INI_PATH = Path("tg.ini")
parser = ConfigParser()
parser.read(INI_PATH)

# ── УСТОЙЧИВОСТЬ К ОТСУТСТВИЮ tg.ini ────────────────────────────────────────
# На PC2 tg.ini может отсутствовать или быть без секции [bot].
# Раньше это роняло main.py (NoSectionError). Теперь — тихо продолжаем,
# TG-бот просто не запустится (пустой токен).
_has_bot = parser.has_section("bot")
if not _has_bot:
    print("[config] ВНИМАНИЕ: tg.ini не найден или нет секции [bot] — "
          "TG-бот НЕ будет работать. Создай tg.ini:\n"
          "  [bot]\n  token = ТВОЙ_ТОКЕН\n  admins = 123456789", file=sys.stderr)

def _safe_get(section, key, fallback=None):
    """parser.get() который НЕ падает если нет секции."""
    if not parser.has_section(section):
        return fallback
    return parser.get(section, key, fallback=fallback)

def load_notify() -> dict[str, bool]:
    if parser.has_section("notifications"):
        return {
            level.lower(): parser.getboolean("notifications", level, fallback=True)
            for level, _ in parser.items("notifications")
        }
    return {
        "info": True,
        "warning": True,
        "error": True,
        "trash": False,
        "photo": True,
    }

def save_notify(levels: dict[str, bool]) -> dict[str, bool]:
    if not parser.has_section("notifications"):
        parser.add_section("notifications")

    for level, enabled in levels.items():
        parser.set("notifications", level.lower(), str(enabled))

    with open(INI_PATH, "w") as f:
        parser.write(f)

    return levels

notify_levels = load_notify()

@dataclass
class Config:
    BOT_TOKEN: str
    ADMINS: list[int]

    PROXY_HOST: str | None = None
    PROXY_PORT: int | None = None
    PROXY_USER: str | None = None
    PROXY_PASS: str | None = None

    STATE: bool = True
    NOTIFY_LEVELS: dict[str, bool] = None

    @property
    def proxy_url(self) -> str | None:
        if not self.PROXY_HOST or not self.PROXY_PORT:
            return None

        auth = ""
        if self.PROXY_USER and self.PROXY_PASS:
            auth = f"{self.PROXY_USER}:{self.PROXY_PASS}@"

        return f"http://{auth}{self.PROXY_HOST}:{self.PROXY_PORT}"

# Парсинг admins: "123,456,789" → [123, 456, 789]. Пусто/нет секции → []
_admins_raw = _safe_get("bot", "admins", fallback="")
_admins = []
if _admins_raw and _admins_raw.strip():
    _admins = [int(i.strip()) for i in _admins_raw.split(",") if i.strip()]

config = Config(
    BOT_TOKEN=_safe_get("bot", "token", fallback=""),
    ADMINS=_admins,
    PROXY_HOST=_safe_get("proxy", "host", fallback=None),
    PROXY_PORT=int(_safe_get("proxy", "port", fallback="0") or "0") if _safe_get("proxy", "port") else None,
    PROXY_USER=_safe_get("proxy", "user", fallback=None),
    PROXY_PASS=_safe_get("proxy", "pass", fallback=None),
    STATE=parser.getboolean("bot", "state", fallback=True) if _has_bot else True,
    NOTIFY_LEVELS=notify_levels,
)
