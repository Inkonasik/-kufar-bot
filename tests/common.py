"""Общее для тестов: путь к боту, быстрые паузы, свежая копия бота во временной папке (seen.json рядом с настоящим не трогаем)."""
import os
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT = Path(os.environ.get("BOT_FILE") or HERE.parent / "kufar_bot.py")
for _name in ("HTTP_BACKOFF", "SEND_PAUSE", "KUFAR_PAUSE", "GEMINI_MIN_GAP_S"):
    os.environ.setdefault(_name, "0")  # в тестах не ждём (настоящий ограничитель Gemini проверяет test_ratelimit.py на поддельных часах)
os.environ.setdefault("GEMINI_RPM", "1000")
# Страховка: тесты не должны ходить в сеть. Все запросы подменяются в самих тестах; если где-то подмена забыта, запрос уйдёт
# на несуществующий локальный прокси и сразу упадёт — ни квоты Gemini, ни сообщений в Telegram, ни запросов к Куфару.
for _proxy in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ[_proxy] = "http://127.0.0.1:9"
for _np in ("NO_PROXY", "no_proxy"):
    os.environ.pop(_np, None)
for _key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "TG_TOKEN", "TG_CHAT_ID"):
    os.environ.pop(_key, None)  # настоящие ключи из окружения в тесты не попадают


def fresh_dir(seen_file=None):
    """Новая временная папка с копией бота (и, если нужно, со своим seen.json)."""
    d = Path(tempfile.mkdtemp(prefix="kufar_test_"))
    shutil.copy(BOT, d / "kufar_bot.py")
    if seen_file:
        shutil.copy(seen_file, d / "seen.json")
    return d
