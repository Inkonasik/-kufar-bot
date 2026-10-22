"""Общее для тестов: путь к боту, быстрые паузы, свежая копия бота во временной папке (seen.json рядом с настоящим не трогаем)."""
import os
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOT = Path(os.environ.get("BOT_FILE") or HERE.parent / "kufar_bot.py")
for _name in ("HTTP_BACKOFF", "SEND_PAUSE", "KUFAR_PAUSE"):
    os.environ.setdefault(_name, "0")  # в тестах не ждём


def fresh_dir(seen_file=None):
    """Новая временная папка с копией бота (и, если нужно, со своим seen.json)."""
    d = Path(tempfile.mkdtemp(prefix="kufar_test_"))
    shutil.copy(BOT, d / "kufar_bot.py")
    if seen_file:
        shutil.copy(seen_file, d / "seen.json")
    return d
