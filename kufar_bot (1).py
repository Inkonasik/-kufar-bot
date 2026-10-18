#!/usr/bin/env python3
"""
Куфар -> Telegram: мониторинг новых объявлений (iPhone / Samsung).

Запуск:
  pip install requests
  export TG_TOKEN=...          # токен от @BotFather
  export TG_CHAT_ID=...        # твой chat id: python kufar_bot.py --get-chat-id
  python kufar_bot.py
  python kufar_bot.py --once   # один проход и выход (для запуска по расписанию)

Необязательные переменные:
  GEMINI_API_KEY     включает проверку нейросетью Gemini (бесплатный ключ: aistudio.google.com)
  GEMINI_MODEL       модель Gemini (по умолчанию gemini-3.1-flash-lite)
  ANTHROPIC_API_KEY  включает проверку объявлений нейросетью (Claude), если нет GEMINI_API_KEY
  LLM_MODEL          модель для проверки (по умолчанию claude-haiku-5-5)
  QUERIES            что искать через запятую (по умолчанию iphone,samsung,ipod touch)
  MAX_PRICE_BYN      потолок цены в рублях BYN (0 = без лимита)
  ONLY_PRIVATE       1 = только частники, без магазинов
  INTERVAL           период опроса в секундах (по умолчанию 90)
  MODELS             свой список моделей через запятую, каждая — регулярка
                     (по умолчанию: все iPhone до 7, iPod touch и Galaxy S1-S7, см. DEFAULT_MODELS)
                     MODELS="" = любые iPhone/Samsung
"""
import html
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

TG_TOKEN = os.getenv("TG_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-5-5")
MAX_PRICE_BYN = float(os.getenv("MAX_PRICE_BYN", "0"))
ONLY_PRIVATE = os.getenv("ONLY_PRIVATE", "0") == "1"
INTERVAL = int(os.getenv("INTERVAL", "90"))
QUERIES = [q.strip() for q in os.getenv("QUERIES", "iphone,samsung,ipod touch").split(",") if q.strip()]

# Нужные модели (регулярки, поиск по названию объявления в нижнем регистре)
DEFAULT_MODELS = [
    # Все iPhone до 7: 2G, 3G, 3GS, 4, 4s, 5, 5c, 5s, 6, 6 Plus, 6s, 6s Plus (7 и новее, SE не берём)
    r"(?:iphone|айфон)\s*(?:2g|3gs|3g|4s|4|5[cс]|5[sс]|5|6[sс]?\s*plus|6[sс]?\s*\+|6[sс]|6)(?![0-9a-zа-я])",
    # iPod touch любых поколений
    r"(?:ipod|айпод)\s*-?(?:touch|тач)",
    # Samsung Galaxy S1-S7 (+ edge, mini, plus, active, duos...), S20/S21 и т.п. не пропускаем
    r"(?:galaxy|галакси|samsung|самсунг)\s*(?:[sс]\s?[1-7](?![0-9])|s(?![0-9a-zа-я])(?!\s*\d+(?!\d)(?!\s*(?:gb|гб))))",
    # Коды моделей на случай, если в названии нет «S3» и т.п.
    r"\b(?:gt-?)?i9(?:000|100|105|190|195|295|300|305|500|505)\b",
    r"\bsm-?g(?:800|870|890|891|900|903|920|925|928|930|935)",
]
_models_env = os.getenv("MODELS")
MODELS = DEFAULT_MODELS if _models_env is None else [m.strip().lower() for m in _models_env.split(",") if m.strip()]

KUFAR_URL = "https://api.kufar.by/search-api/v2/search/rendered-paginated"
CATEGORY = 17010  # Мобильные телефоны
SEEN_FILE = Path(__file__).with_name("seen.json")

# Объявление должно содержать хотя бы одно из этих слов (название + производитель)
WANT = ("iphone", "айфон", "apple", "ipod", "айпод", "samsung", "самсунг", "galaxy", "галакси")
# Объявления с этими словами пропускаем
BAD_WORDS = ("куплю", "скупк", "запчаст", "на детали", "на разбор", "муляж")


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


# ---------- Куфар ----------

def fetch(query):
    params = {"query": query, "sort": "lst.d", "size": 30, "lang": "ru"}
    # iPod touch лежит в «Аудиотехнике» (иногда в «Мобильных телефонах») — для него ищем по всем категориям
    if not any(w in query.lower() for w in ("ipod", "айпод")):
        params["cat"] = CATEGORY
    r = requests.get(KUFAR_URL, params=params, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json().get("ads", [])


def param(ad, key):
    for p in ad.get("ad_parameters", []):
        if p.get("p") == key:
            v = p.get("vl")
            return ", ".join(v) if isinstance(v, list) else v
    return None


def price_byn(ad):
    """Цена в BYN. В API она в копейках; 0 = не указана."""
    try:
        return int(ad.get("price_byn") or 0) / 100
    except ValueError:
        return 0


def price_usd(ad):
    try:
        return int(ad.get("price_usd") or 0) / 100
    except ValueError:
        return 0


def basic_filter(ad):
    if ad.get("type") != "sell":
        return False
    if ONLY_PRIVATE and ad.get("company_ad"):
        return False
    text = " ".join(
        f"{ad.get('subject', '')} {param(ad, 'phones_brand') or ''} {param(ad, 'phones_model') or ''}".lower().split()
    )
    if not any(w in text for w in WANT):
        return False
    if any(w in text for w in BAD_WORDS):
        return False
    if MODELS and not any(re.search(m, text) for m in MODELS):
        return False
    p = price_byn(ad)
    if MAX_PRICE_BYN and p and p > MAX_PRICE_BYN:
        return False
    return True


# ---------- Нейросеть (необязательно) ----------

def llm_check(ad):
    """Возвращает (ok, комментарий). Без ключа или при ошибке — (True, '')."""
    if not (GEMINI_KEY or ANTHROPIC_KEY):
        return True, ""
    info = (
        f"Название: {ad.get('subject')}\n"
        f"Цена: {price_byn(ad):.0f} BYN (~${price_usd(ad):.0f})\n"
        f"Состояние: {param(ad, 'condition')}\n"
        f"Модель: {param(ad, 'phones_model')}\n"
        f"Память: {param(ad, 'phablet_phones_memory')}\n"
        f"Регион: {param(ad, 'region')}, {param(ad, 'area')}\n"
        f"Продавец: {'магазин' if ad.get('company_ad') else 'частное лицо'}"
    )
    prompt = (
        "Ты помогаешь искать телефоны на Куфаре (Беларусь). Вот объявление:\n\n"
        f"{info}\n\n"
        'Ответь ТОЛЬКО JSON вида {"ok": true, "comment": "..."}.\n'
        "ok=false, если это не сам iPhone/iPod touch/Samsung (аксессуар, запчасти, «куплю», муляж) "
        "или цена подозрительно низкая для такой модели (похоже на развод).\n"
        "comment — одна короткая фраза по-русски: что за модель/состояние и адекватна ли цена."
    )
    try:
        if GEMINI_KEY:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
                headers={"x-goog-api-key": GEMINI_KEY, "content-type": "application/json"},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 400},
                },
                timeout=30,
            )
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={"model": LLM_MODEL, "max_tokens": 200, "messages": [{"role": "user", "content": prompt}]},
                timeout=30,
            )
            r.raise_for_status()
            text = r.json()["content"][0]["text"]
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])
        return bool(data.get("ok", True)), str(data.get("comment", ""))[:200]
    except Exception as e:
        log("Ошибка нейросети:", e)
        return True, ""


# ---------- Telegram ----------

def tg_send(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        json={"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=20,
    )
    r.raise_for_status()


def format_ad(ad, comment):
    e = html.escape
    p, u = price_byn(ad), price_usd(ad)
    price = f"{p:,.0f} BYN (~${u:,.0f})".replace(",", " ") if p else "цена не указана"
    place = ", ".join(x for x in (param(ad, "region"), param(ad, "area")) if x)
    lines = [
        f"📱 <b>{e(ad.get('subject', ''))}</b>",
        f"💰 {e(price)}",
    ]
    if place:
        lines.append(f"📍 {e(place)}")
    if param(ad, "condition"):
        lines.append(f"🔧 {e(param(ad, 'condition'))}")
    lines.append("🏪 магазин" if ad.get("company_ad") else "👤 частник")
    if comment:
        lines.append(f"🤖 {e(comment)}")
    lines.append(ad.get("ad_link", ""))
    return "\n".join(lines)


def get_chat_id():
    r = requests.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates", timeout=20).json()
    for u in reversed(r.get("result", [])):
        m = u.get("message")
        if m:
            print("Твой TG_CHAT_ID:", m["chat"]["id"])
            return
    print("Напиши боту любое сообщение в Telegram и запусти команду ещё раз.")


# ---------- Основной цикл ----------

def load_seen():
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        return None  # None = первый запуск


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(sorted(seen)[-5000:]))


def cycle(seen, first_run):
    new_ads = {}
    ok_queries = 0  # сколько запросов к Куфару прошло успешно
    for q in QUERIES:
        try:
            for ad in fetch(q):
                if ad["ad_id"] not in seen:
                    new_ads[ad["ad_id"]] = ad
            ok_queries += 1
        except Exception as e:
            log(f"Ошибка Куфара ({q}):", e)

    if first_run:
        # Первый запуск: запоминаем всё, что уже висит, чтобы не завалить чат старым
        seen.update(new_ads)
        log(f"Первый запуск: запомнил {len(new_ads)} существующих объявлений")
        return ok_queries

    for ad_id, ad in sorted(new_ads.items()):
        if basic_filter(ad):
            ok, comment = llm_check(ad)
            if ok:
                try:
                    tg_send(format_ad(ad, comment))
                    log("Отправил:", ad.get("subject"))
                except Exception as e:
                    log("Ошибка Telegram, повторю в следующем цикле:", e)
                    continue  # не помечаем как просмотренное
            else:
                log("Нейросеть отсеяла:", ad.get("subject"))
        seen.add(ad_id)
    return ok_queries


def main():
    if not TG_TOKEN:
        sys.exit("Нужна переменная TG_TOKEN (токен от @BotFather)")
    if "--get-chat-id" in sys.argv:
        return get_chat_id()
    if not TG_CHAT_ID:
        sys.exit("Нужна переменная TG_CHAT_ID (узнать: python kufar_bot.py --get-chat-id)")

    seen = load_seen()
    first_run = seen is None
    seen = seen or set()

    if "--once" in sys.argv:
        # Один проход и выход — для запуска по расписанию (GitHub Actions)
        ok_queries = cycle(seen, first_run)
        # Куфар не ответил (на первом запуске нужны все запросы) — состояние не трогаем и падаем,
        # иначе в следующий раз все старые объявления придут как новые
        if not ok_queries or (first_run and ok_queries < len(QUERIES)):
            sys.exit("Куфар ответил не на все запросы — состояние не сохраняю")
        if first_run:
            tg_send("✅ Мониторинг Куфара запущен (по расписанию): " + ", ".join(QUERIES))
        save_seen(seen)
        return

    tg_send("✅ Мониторинг Куфара запущен: " + ", ".join(QUERIES))
    log("Запущено. Запросы:", QUERIES, "| нейросеть:", "вкл" if (GEMINI_KEY or ANTHROPIC_KEY) else "выкл")

    while True:
        cycle(seen, first_run)
        first_run = False
        save_seen(seen)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
