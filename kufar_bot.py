#!/usr/bin/env python3
"""
Куфар -> Telegram: мониторинг новых объявлений (iPhone / iPod touch / Samsung) с оценкой цены и перепродажи.

Запуск:
  pip install requests
  export TG_TOKEN=...          # токен от @BotFather
  export TG_CHAT_ID=...        # твой chat id: python kufar_bot.py --get-chat-id
  python kufar_bot.py
  python kufar_bot.py --once   # один проход и выход (для запуска по расписанию)
  python kufar_bot.py --report # недельная аналитика цен в Telegram (по истории из seen.json)

Что ищет (по умолчанию): iPhone 2G…11 (включая X/XR/XS/XS Max), iPhone SE 2016–2022, iPod touch, Galaxy S1–S9.
iPhone 12 и новее, Galaxy S10 и новее, планшеты, чехлы/стёкла/запчасти и «куплю» отбрасываются.

К каждому объявлению бот добавляет: разбор (память, состояние, дефекты, аккумулятор, блокировка, комплект, торг),
сравнение цены с РЕАЛЬНЫМИ активными объявлениями Куфара той же модели (это цены объявлений, а не сделок),
целевую цену покупки и расчёт перепродажи (за сколько выставлять, быстро продать, максимум покупки, прибыль).
Если аналогов мало, бот прямо пишет «недостаточно данных» / «оценка приблизительная».

Необязательные переменные:
  GEMINI_API_KEY     включает разбор объявлений нейросетью Gemini (бесплатный ключ: aistudio.google.com); без него работают правила
  GEMINI_MODEL       модель Gemini (по умолчанию gemini-3.1-flash-lite)
  ANTHROPIC_API_KEY  то же через Claude, если нет GEMINI_API_KEY
  LLM_MODEL          модель для проверки (по умолчанию claude-haiku-5-5)
  QUERIES            основные запросы через запятую, ходят каждый запуск
                     (по умолчанию iphone,samsung,ipod touch,айфон,самсунг; если задан — дополнительные запросы выключены)
  EXTRA_QUERIES      дополнительные запросы (каждый раз в ~15 минут по очереди; "" = выключить)
  MAX_PRICE_BYN      потолок цены в рублях BYN (0 = без лимита)
  ONLY_PRIVATE       1 = только частники, без магазинов
  INTERVAL           период опроса в секундах (по умолчанию 90)
  MODELS             свой список моделей через запятую, каждая — регулярка (отключает новые модели; "" = любые iPhone/Samsung)
Оценка цены и перепродажи (значения по умолчанию подходят, менять необязательно):
  MARKET_TTL_HOURS   как часто обновлять аналоги по модели, часов (6)
  MARKET_MAX_REFRESH сколько моделей обновлять за один запуск (6)
  MARKET_SIZE        сколько объявлений-аналогов запрашивать по модели (100)
  MIN_COMPS          меньше стольких аналогов — «недостаточно данных» (5; для дефектных — 3)
  MIN_PROFIT_BYN     минимальная прибыль перепродажи, BYN (15)
  MIN_PROFIT_PCT     …или столько процентов от цены быстрой продажи — берётся большее (12)
  EXTRA_COSTS_BYN    прочие расходы на сделку в BYN: дорога, упаковка… (0)
  REPAIR_COSTS       известные цены ремонта в BYN, JSON, например {"screen": 80, "battery": 40} (по умолчанию неизвестны)
  HOME_REGION        где продаёшь, например «минск»: аналоги из этого региона в приоритете при расчёте перепродажи
  RUN_BUDGET_S       сколько секунд отводится на один запуск --once (200)
  KUFAR_PAUSE        пауза между запросами к Куфару, сек (0.4)
"""
import html
import json
import os
import re
import statistics
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
_queries_env = os.getenv("QUERIES")
# Основные запросы ходят каждый запуск. Если QUERIES задан вручную — ищем только по нему (как раньше).
QUERIES = [q.strip() for q in (_queries_env if _queries_env is not None else "iphone,samsung,ipod touch,айфон,самсунг").split(",") if q.strip()]

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
USE_NEW_MODELS = _models_env is None  # iPhone 7–11, SE, Galaxy S8–S9 добавляются к DEFAULT_MODELS (см. identify_model)
# Дополнительные запросы (написания, отдельные модели): каждый ходит раз в ~15 минут, по очереди. EXTRA_QUERIES="" — отключить.
_extra_env = os.getenv("EXTRA_QUERIES")
EXTRA_QUERIES = [q.strip() for q in (_extra_env if _extra_env is not None else (
    "apple,galaxy,айпод,iphone 7,iphone 8,iphone x,iphone 11,iphone se,galaxy s8,galaxy s9,айфон 7,айфон 11"
    if _queries_env is None and USE_NEW_MODELS else "")).split(",") if q.strip()]
LEGACY_QUERIES = ("iphone", "samsung", "ipod touch")  # эти запросы работали до обновления: их выдача уже в seen.json
NOTICE_VERSION = 1  # версия разового уведомления «бот обновлён»

KUFAR_URL = "https://api.kufar.by/search-api/v2/search/rendered-paginated"
CATEGORY = 17010  # Мобильные телефоны
SEEN_FILE = Path(__file__).with_name("seen.json")
HISTORY = {}  # id объявления -> запись для недельной аналитики (хранится в seen.json)
STATE = {"market": {}, "baseline": [], "notice": 0}  # кеш аналогов, уже «запомненные» запросы, версия уведомления


def _env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


def _env_json(name):
    try:
        v = json.loads(os.getenv(name, "") or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


MARKET_TTL_H = _env_float("MARKET_TTL_HOURS", 6)      # через сколько часов обновлять кеш аналогов
MARKET_MAX_REFRESH = int(_env_float("MARKET_MAX_REFRESH", 6))  # сколько моделей обновлять за один запуск
MARKET_SIZE = int(_env_float("MARKET_SIZE", 100))      # сколько объявлений-аналогов запрашивать по модели
MIN_COMPS = int(_env_float("MIN_COMPS", 5))            # меньше аналогов — оценка «недостаточно данных»
MIN_PROFIT_BYN = _env_float("MIN_PROFIT_BYN", 15)      # минимальная прибыль перепродажи, BYN
MIN_PROFIT_PCT = _env_float("MIN_PROFIT_PCT", 12)      # …или столько процентов от цены быстрой продажи (берётся большее)
EXTRA_COSTS_BYN = _env_float("EXTRA_COSTS_BYN", 0)     # прочие расходы на сделку (дорога, упаковка…), по умолчанию 0
REPAIR_COSTS = _env_json("REPAIR_COSTS")               # известные цены ремонта, напр. {"screen": 80, "battery": 40}
HOME_REGION = os.getenv("HOME_REGION", "").strip().lower()  # где продаёшь (напр. «минск»): аналоги оттуда в приоритете
RUN_BUDGET_S = _env_float("RUN_BUDGET_S", 200)         # сколько секунд на один запуск --once
KUFAR_PAUSE = _env_float("KUFAR_PAUSE", 0.4)           # пауза между запросами к Куфару

# Объявление должно содержать хотя бы одно из этих слов (название + производитель)
WANT = ("iphone", "айфон", "apple", "ipod", "айпод", "samsung", "самсунг", "galaxy", "галакси")
# Объявления с этими словами пропускаем
BAD_WORDS = ("куплю", "скупк", "муляж")
# Телефон «на запчасти» — это всё же телефон (помечаем в сообщении); а вот сами запчасти/аксессуары отбрасываем
PARTS_RE = re.compile(r"на запчаст|на детал|на разбор|запчасти|донор|для разбора|на з/ч|на зч")
_ACC_STEMS = ("чехл", "чехол", "бампер", "стекл", "защитн", "плен", "дисплей", "экран", "модул", "аккумулятор", "акб",
              "батаре", "коробк", "упаковк", "зарядк", "зарядн", "кабел", "шнур", "адаптер", "наушник", "держател",
              "ремешок", "корпус", "крышк", "рамк", "шлейф", "динамик", "плата", "платы", "запчаст", "детал",
              "разбор", "ремонт", "замена", "услуг", "лоток", "кнопк", "камера для", "стилус", "сумка")


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


# ---------- Куфар ----------

def fetch(query, size=30):
    params = {"query": query, "sort": "lst.d", "size": size, "lang": "ru"}
    # iPod touch лежит в «Аудиотехнике» (иногда в «Мобильных телефонах») — для него ищем по всем категориям
    if not any(w in query.lower() for w in ("ipod", "айпод")):
        params["cat"] = CATEGORY
    for attempt in (1, 2):
        r = requests.get(KUFAR_URL, params=params, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code in (429, 500, 502, 503, 504) and attempt == 1:
            time.sleep(2)  # один повтор, без долбёжки
            continue
        break
    r.raise_for_status()
    return r.json().get("ads", [])


ITEM_URL = "https://api.kufar.by/search-api/v2/item/{}/rendered"


def fetch_body(ad_id):
    """Описание объявления из карточки (в списке Куфар отдаёт body = null). При любой ошибке — пустая строка."""
    for attempt in (1, 2):
        try:
            r = requests.get(ITEM_URL.format(ad_id), timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code in (429, 500, 502, 503, 504) and attempt == 1:
                time.sleep(2)
                continue
            r.raise_for_status()
            body = (r.json().get("result") or {}).get("body")
            return body if isinstance(body, str) else ""
        except Exception as e:
            log(f"Описание {ad_id} не получено:", e)
            return ""
    return ""


def param(ad, key):
    for p in ad.get("ad_parameters") or []:
        if isinstance(p, dict) and p.get("p") == key:
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
    if looks_like_accessory(ad.get("subject", "")):
        return False
    if MODELS and not (any(re.search(m, text) for m in MODELS) or (USE_NEW_MODELS and identify_model(text))):
        return False
    p = price_byn(ad)
    if MAX_PRICE_BYN and p and p > MAX_PRICE_BYN:
        return False
    return True


# ---------- Нейросеть (необязательно) ----------

def _llm_call(prompt, max_tokens=400, json_mode=False):
    """Текст ответа нейросети: Gemini, если есть GEMINI_API_KEY, иначе Claude. При ошибке бросает исключение."""
    if GEMINI_KEY:
        config = {"maxOutputTokens": max_tokens}
        if json_mode:
            config["responseMimeType"] = "application/json"
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": GEMINI_KEY, "content-type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": config},
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={"model": LLM_MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["content"][0]["text"]


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
        text = _llm_call(prompt, 400, json_mode=True)
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])
        return bool(data.get("ok", True)), str(data.get("comment", ""))[:200]
    except Exception as e:
        log("Ошибка нейросети:", e)
        return True, ""


# ---------- Telegram ----------

def tg_send(text, parse_mode="HTML"):
    payload = {"chat_id": TG_CHAT_ID, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json=payload, timeout=20)
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


# ---------- История и недельная аналитика ----------

_IPHONE_RE = re.compile(
    r"(?:iphone|айфон)\s*-?(2g|3gs|3g|4s|4|5[cс]|5[sс]|5|6[sс]?\s*plus|6[sс]?\s*\+|6[sс]|6)(?![0-9a-zа-я])"
)
_IPOD_RE = re.compile(r"(?:ipod|айпод)\s*-?(?:touch|тач)\s*([1-7])?(?!\d)")
_GALAXY_NUM_RE = re.compile(r"(?<![a-zа-я0-9])(?:s\s?|с)([1-7])(?!\d)")
_GALAXY_ROMAN_RE = re.compile(r"(?:galaxy|галакси)\s*s\s?(iii|ii|iv)(?![a-z])")
_GALAXY_FIRST_RE = re.compile(r"(?:galaxy|галакси)\s*s(?![0-9a-zа-я])")
_GALAXY_SUFFIX_RE = re.compile(r"\b(mini|edge\s*(?:\+|plus)?|plus|neo|active|duos)(?![a-z])")


def model_label(text):
    """Название модели для группировки в отчёте: «iPhone 6s Plus», «Galaxy S5 Mini», «iPod touch 4»."""
    new = identify_model(text)
    if new:
        return new
    m = _IPHONE_RE.search(text)
    if m:
        g = re.sub(r"\s+", "", m.group(1)).replace("с", "c").replace("+", "plus")
        plus = g.endswith("plus")
        g = g[:-4] if plus else g
        if g in ("2g", "3g", "3gs"):
            g = g.upper()
        return f"iPhone {g}" + (" Plus" if plus else "")
    m = _IPOD_RE.search(text)
    if m:
        return "iPod touch" + (f" {m.group(1)}" if m.group(1) else "")
    if any(w in text for w in ("samsung", "самсунг", "galaxy", "галакси")):
        num = None
        m = _GALAXY_NUM_RE.search(text)
        if m:
            num = m.group(1)
        else:
            m = _GALAXY_ROMAN_RE.search(text)
            if m:
                num = {"ii": "2", "iii": "3", "iv": "4"}[m.group(1)]
        if num or _GALAXY_FIRST_RE.search(text):
            label = f"Galaxy S{num or ''}"
            m = _GALAXY_SUFFIX_RE.search(text)
            if m:
                s = re.sub(r"\s+", "", m.group(1))
                if s.startswith("edge"):
                    s = "Edge+" if ("+" in s or "plus" in s) else "Edge"
                label += " " + s.capitalize() if not s.startswith("Edge") else " " + s
            return label
    return "Другое"


def record_ad(ad, ok):
    """Запоминает объявление для недельной аналитики (повторная запись того же id просто обновляет её)."""
    text = " ".join(
        f"{ad.get('subject', '')} {param(ad, 'phones_brand') or ''} {param(ad, 'phones_model') or ''}".lower().split()
    )
    HISTORY[str(ad["ad_id"])] = {
        "t": int(time.time()),
        "m": model_label(text),
        "p": price_byn(ad),
        "c": param(ad, "condition") or "не указано",
        "s": (ad.get("subject") or "")[:80],
        "l": ad.get("ad_link", ""),
        "ok": bool(ok),  # False = нейросеть сочла объявление мусором или обманом, в цены не берём
    }


def _stats(prices):
    return {
        "n": len(prices),
        "avg": sum(prices) / len(prices),
        "med": statistics.median(prices),
        "min": min(prices),
        "max": max(prices),
    }


def build_report(now=None):
    """Недельная аналитика. Возвращает (текст для Telegram, цифры для нейросети) или None, если данных нет."""
    now = now or time.time()
    week = 7 * 86400
    rows = [r for r in HISTORY.values() if r.get("ok", True)]
    cur = [r for r in rows if now - week <= r["t"] <= now]
    prev = [r for r in rows if now - 2 * week <= r["t"] < now - week]
    if not cur:
        return None

    def prices_by(rs, key):
        d = {}
        for r in rs:
            if r["p"] > 0:
                d.setdefault(key(r), []).append(r["p"])
        return d

    cur_m, prev_m = prices_by(cur, lambda r: r["m"]), prices_by(prev, lambda r: r["m"])
    cur_mc = prices_by(cur, lambda r: (r["m"], r["c"]))
    esc = html.escape
    d1, d2 = (time.strftime("%d.%m", time.localtime(t)) for t in (now - week, now))
    lines = [
        f"📊 <b>Итоги недели {d1}–{d2}</b>",
        f"Подходящих объявлений: {len(cur)}, из них с ценой: {sum(len(v) for v in cur_m.values())}",
    ]
    facts = [f"Период {d1}–{d2}, объявлений {len(cur)}."]

    for label, prices in sorted(cur_m.items(), key=lambda kv: -len(kv[1]))[:12]:
        s = _stats(prices)
        line = (
            f"\n<b>{esc(label)}</b>: {s['n']} шт · средняя {s['avg']:.0f} · медиана {s['med']:.0f} BYN "
            f"(от {s['min']:.0f} до {s['max']:.0f})"
        )
        fact = f"{label}: {s['n']} шт, средняя {s['avg']:.0f}, медиана {s['med']:.0f}, мин {s['min']:.0f}, макс {s['max']:.0f}"
        pp = prev_m.get(label)
        if pp and s["n"] >= 3 and len(pp) >= 3:
            pm = statistics.median(pp)
            delta = (s["med"] - pm) / pm * 100
            line += f" · {'▲' if delta > 0 else '▼'} {abs(delta):.0f}% к прошлой неделе"
            fact += f"; прошлая неделя: медиана {pm:.0f} ({len(pp)} шт), изменение {delta:+.0f}%"
        lines.append(line)
        conds = sorted(((c, p) for (m, c), p in cur_mc.items() if m == label), key=lambda x: -len(x[1]))
        for c, p in conds:
            lines.append(f"   • {esc(c)}: {len(p)} шт · средняя {sum(p) / len(p):.0f}")
            fact += f"; {c}: {len(p)} шт, средняя {sum(p) / len(p):.0f}"
        facts.append(fact)

    deals = []
    for r in cur:
        ps = cur_m.get(r["m"])
        if r["p"] > 0 and ps and len(ps) >= 4:
            med = statistics.median(ps)
            if r["p"] <= med * 0.7:
                deals.append((r["p"] / med, r, med))
    if deals:
        lines.append("\n🔥 <b>Дешевле медианы на 30% и больше</b> (проверяй состояние и продавца)")
        for _, r, med in sorted(deals, key=lambda x: x[0])[:5]:
            lines.append(f"• {esc(r['s'])} — {r['p']:.0f} BYN (медиана {med:.0f})\n  {r['l']}")
    return "\n".join(lines), "\n".join(facts)


def tg_send_long(text):
    """Telegram принимает до 4096 символов в сообщении, поэтому режем по строкам."""
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > 3800:
            tg_send(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        tg_send(chunk)


def send_report():
    res = build_report()
    if not res:
        tg_send("📊 Недельный отчёт: за последние 7 дней данных пока нет.")
        return
    text, facts = res
    if GEMINI_KEY or ANTHROPIC_KEY:
        prompt = (
            "Ты аналитик рынка б/у телефонов на Куфаре (Беларусь). Ниже итоги недели по моделям: "
            "количество объявлений, средняя и медиана цены в BYN, цены по состоянию и сравнение с прошлой неделей.\n"
            "Напиши 3-5 коротких наблюдений по-русски: что подорожало или подешевело, какие модели выглядят выгодно, "
            "где данных слишком мало для выводов. Опирайся ТОЛЬКО на эти цифры, ничего не выдумывай и не пересчитывай. "
            "Без вступлений, списком.\n\n" + facts
        )
        try:
            comment = _llm_call(prompt, 700).strip()
            text += "\n\n🤖 <b>Выводы нейросети</b>\n" + html.escape(comment[:1500])
        except Exception as ex:
            log("Ошибка нейросети (отчёт без выводов):", ex)
    tg_send_long(text)


# ---------- Новые модели: iPhone 7–11, SE, Galaxy S7–S9 (расширяемый словарь + нормализация) ----------

def looks_like_accessory(title):
    """Чехол, стекло, дисплей, коробка, услуга и т.п. вместо самого телефона (смотрим на начало названия и «для iPhone»)."""
    t = normalize_text(title)
    if re.search(r"(?<![а-я])для\s+(?:iphone|apple|samsung|galaxy|ipod)", t):
        return True
    first = t.split()[:2]
    return any(w.startswith(stem) for w in first for stem in _ACC_STEMS)


def normalize_text(text):
    """Приводит название к единому виду: русские и английские написания, опечатки, слитное написание."""
    t = (text or "").lower().replace("ё", "е")
    for pat, rep in _NORM_RULES:
        t = pat.sub(rep, t)
    # «iphone7» -> «iphone 7»; кириллические х/с/р сразу после iphone -> латиница (айфон хr, айфон хс)
    t = re.sub(r"iphone(?=[0-9a-zа-я])", "iphone ", t)
    t = re.sub(
        r"(iphone\s*-?\s*)([хx])(?:\s*([рсrs]))?(?![а-яa-z])",
        lambda m: m.group(1) + "x" + (m.group(3).translate(_CYR2LAT) if m.group(3) else ""),
        t,
    )
    return " ".join(t.split())


_CYR2LAT = str.maketrans({"р": "r", "с": "s", "х": "x"})
_NORM_RULES = [(re.compile(p), r) for p, r in (
    (r"(?<![a-zа-я])i[\s\-]?phone", "iphone"),
    (r"(?<![а-я])(?:айфон|афон|айфн|аифон|эйфон|айфоун)[а-я]*", "iphone"),
    (r"(?<![a-z])(?:iphon|ifon|aifon|ayfon|ayphone|iphne|ipone|iphoen|ihpone|iphome)(?![a-z])", "iphone"),
    (r"(?<![а-я])(?:самсунг|самсанг|самсун)[а-я]*", "samsung"),
    (r"(?<![a-z])(?:samsun|samsumg|samsong|samsunk|samung)(?![a-z])", "samsung"),
    (r"(?<![а-я])(?:гэлакси|галакси|гелакси|галакс[ие]|гэлэкси)", "galaxy"),
    (r"(?<![a-z])(?:galaxi|galaksy|galacsy|gelaxy|galaxe|galxy)(?![a-z])", "galaxy"),
    (r"(?<![а-я])плюс(?![а-я])", "plus"),
    (r"(?<![а-я])про(?![а-я])", "pro"),
    (r"(?<![а-я])(?:макс|мах|макc)(?![а-я])", "max"),
    (r"(?<=[0-9a-z])\s*\+", " plus "),
    (r"(?<![а-я])семь(?![а-я])", "7"),
    (r"(?<![а-я])восемь(?![а-я])", "8"),
    (r"(?<![а-я])девять(?![а-я])", "9"),
    (r"(?<![а-я])десять(?![а-я])", "10"),
    (r"(?<![а-я])одиннадцать(?![а-я])", "11"),
    (r"(?<![а-я])икс\s*(?:эс|с)\s*max", "xs max"),
    (r"(?<![а-я])икс\s*(?:эс|с)(?![а-я])", "xs"),
    (r"(?<![а-я])икс\s*(?:эр|р)(?![а-я])", "xr"),
    (r"(?<![а-я])икс(?![а-я])", "x"),
)]

_IP = r"iphone\s*-?\s*"
_NOMEM = r"(?!\s*(?:gb|гб))"  # «iphone 8gb» — это память, а не модель
_IPHONE_NEW = [
    ("iPhone 11 Pro Max", re.compile(_IP + r"11\s*pro\s*max")),
    ("iPhone 11 Pro", re.compile(_IP + r"11\s*pro(?![a-z])")),
    ("iPhone 11", re.compile(_IP + r"11(?![0-9])")),
    ("iPhone XS Max", re.compile(_IP + r"(?:xs|10\s*s|x)\s*max")),
    ("iPhone XS", re.compile(_IP + r"(?:xs|10\s*s)(?![a-z0-9])")),
    ("iPhone XR", re.compile(_IP + r"(?:xr|10\s*r)(?![a-z0-9])")),
    ("iPhone X", re.compile(_IP + r"(?:x|10)(?![a-z0-9])")),
    ("iPhone 8 Plus", re.compile(_IP + r"8\s*plus")),
    ("iPhone 8", re.compile(_IP + r"8(?![0-9])" + _NOMEM)),
    ("iPhone 7 Plus", re.compile(_IP + r"7\s*plus")),
    ("iPhone 7", re.compile(_IP + r"7(?![0-9])" + _NOMEM)),
]
# «apple 11 pro» без слова iphone (редко): только для моделей, которые не спутать с другой техникой Apple
_APPLE_BARE = re.compile(r"(?<![a-z])apple\s*(11\s*pro\s*max|11\s*pro|xs\s*max|xs|xr|11)(?![a-z0-9])")
_SE_RE = re.compile(_IP + r"se(?![a-z])")
_IPHONE_OLD_POS = re.compile(_IP + r"(?:2g|3gs|3g|4s|4|5[cs]|5|6s?\s*plus|6s?)(?![0-9a-z])")  # только для сравнения позиций
_NOT_PHONE_SAMSUNG = re.compile(r"(?<![a-zа-я])(?:tab|таб|tablet|планшет\w*|watch|buds|gear)(?![a-zа-я])")
_GAL_RE = re.compile(r"(?<![a-zа-я0-9])(?:s\s?|с)(7|8|9)(?![0-9])(?!\s*(?:gb|гб|ядр|mp|мп|дюйм))")
_GAL_CODES = {
    "930": "Galaxy S7", "935": "Galaxy S7 Edge", "891": "Galaxy S7 Active",
    "950": "Galaxy S8", "955": "Galaxy S8+", "892": "Galaxy S8 Active",
    "960": "Galaxy S9", "965": "Galaxy S9+",
}
_GAL_CODE_RE = re.compile(r"(?<![a-z0-9])sm-?g(930|935|891|950|955|892|960|965)")


def _se_label(t, end):
    """iPhone SE: поколение определяем по тексту рядом (2016/2020/2022, 1/2/3, 1st/2nd/3rd)."""
    win = t[end:end + 28]
    first = re.match(r"\s*[\(\-]?\s*(2016|2020|2022|1st|2nd|3rd|[123])(?![0-9])(?!\s*(?:gb|гб))", win)
    gen = None
    if first:
        gen = {"2016": 2016, "1": 2016, "1st": 2016, "2020": 2020, "2": 2020, "2nd": 2020,
               "2022": 2022, "3": 2022, "3rd": 2022}[first.group(1)]
    else:
        m = re.search(r"(?<![0-9])(2016|2020|2022)(?![0-9])", win)
        if m:
            gen = int(m.group(1))
        elif re.search(r"перв|first", win[:12]):
            gen = 2016
        elif re.search(r"втор|second", win[:12]):
            gen = 2020
        elif re.search(r"трет|third", win[:12]) or re.search(r"(?<![0-9])5g", win):
            gen = 2022
    return f"iPhone SE ({gen})" if gen else "iPhone SE"


def identify_model(text):
    """Точная метка НОВОЙ модели (iPhone 7–11, SE, Galaxy S7–S9) или None. Старые модели — в model_label()."""
    t = normalize_text(text)
    if "iphone" in t or "apple" in t:
        hits = []
        old_m = _IPHONE_OLD_POS.search(t)
        for label, rx in _IPHONE_NEW:
            m = rx.search(t)
            if m:
                hits.append((m.start(), label))
                break
        m = _SE_RE.search(t)
        if m:
            hits.append((m.start(), _se_label(t, m.end())))
        if not hits:
            m = _APPLE_BARE.search(t)
            if m and not re.search(r"watch|ipad|macbook|airpods|pencil", t):
                g = m.group(1)
                g = re.sub(r"\s+", " ", g)
                label = {"11 pro max": "iPhone 11 Pro Max", "11 pro": "iPhone 11 Pro", "11": "iPhone 11",
                         "xs max": "iPhone XS Max", "xs": "iPhone XS", "xr": "iPhone XR"}.get(g)
                if label:
                    hits.append((m.start(), label))
        if hits and not (old_m and old_m.start() < min(hits)[0]):
            return min(hits)[1]
    if ("samsung" in t or "galaxy" in t or "sm-g" in t) and not _NOT_PHONE_SAMSUNG.search(t):
        m = _GAL_RE.search(t)
        if m:
            n = m.group(1)
            win = t[m.end():m.end() + 12]
            if n == "7" and re.match(r"\s*edge", win):
                return "Galaxy S7 Edge"
            if re.match(r"\s*(?:plus|\+)", win) and n in ("8", "9"):
                return f"Galaxy S{n}+"
            if re.match(r"\s*active", win) and n in ("7", "8"):
                return f"Galaxy S{n} Active"
            return f"Galaxy S{n}"
        m = _GAL_CODE_RE.search(t)
        if m:
            return _GAL_CODES[m.group(1)]
    return None


# ---------- Разбор объявления: память, состояние, дефекты, батарея, торг (правила; без нейросети тоже работает) ----------

# код дефекта -> (регулярка, короткая пометка, тяжесть: 0 косметика, 1 терпимо, 2 серьёзно, 3 критично)
_NEG_BEFORE = re.compile(r"(?:без|нет|не|ни|отсутств\w*|исключая)\s*$")
DEFECT_RULES = [
    ("lock", r"icloud|айклауд|activation\s*lock|блокировк\w*|заблокирован\w*|залочен\w*|на\s+оператор\w*|\bmdm\b|\bfrp\b|google\s*(?:account|аккаунт)", "блокировка/привязка", 3),
    ("water", r"после\s+воды|залит\w*|влаг\w*|утоплен\w*|попала\s+вода|окислен\w*", "следы воды", 3),
    ("board", r"не\s+включа\w+|не\s+загружа\w+|яблок\w*\s+(?:висит|горит)|bootloop|бутлуп|нет\s+изображени\w+|материнск\w+|мат\.?\s*плат\w+|не\s+работает\s+полностью|кирпич", "не включается/плата", 3),
    ("charging", r"не\s+заряжа\w+|(?:разъ[её]м|порт|зарядк\w*)\s+(?:не\s+работа\w+|барахл\w+|глючит|разбит)", "проблемы с зарядкой", 2),
    ("screen", r"разбит\w*|трещин\w*|треснут\w*|битые?\s+пиксел\w*|мертв\w+\s+пиксел\w*|полос\w+\s+на\s+экран\w*|пятн\w+\s+на\s+экран\w*|выгорани\w+|(?:тач|сенсор)\w*\s+не\s+работа\w+|экран\w*\s+не\s+работа\w+|дисплей\s+не\s+работа\w+", "проблемы с экраном", 2),
    ("biometric", r"(?:face\s*id|touch\s*id|фейс\s*айди|тач\s*айди|отпечат\w+|сканер\w*)\s*(?:не\s+работа\w*|неисправ\w*|отсутств\w*|сломан\w*)|(?:без|нет|не\s+работает)\s+(?:face\s*id|touch\s*id|фейс\s*айди|тач\s*айди)", "не работает Face ID/Touch ID", 2),
    ("camera", r"камер\w*\s+(?:не\s+работа\w+|не\s+фокусир\w+|размыт\w*|разбит\w*|треснул\w*)|пятн\w+\s+на\s+камер\w*", "проблемы с камерой", 2),
    ("comms", r"(?:wi-?fi|вай-?фай|bluetooth|блютуз|микрофон|динамик|nfc|gps|сеть|связь|сим\w*|sim)\s+(?:не\s+работа\w+|не\s+видит|не\s+ловит|пропада\w+|хрипит|сломан\w*)|нет\s+(?:сети|звука|связи)", "проблемы со связью/звуком", 2),
    ("battery", r"(?:акб|аккумулятор\w*|батаре\w*)\s+(?:слаб\w+|быстро\s+(?:садится|разряжа\w+)|не\s+держит|вздул\w+|умира\w+|требуется\s+замен\w+|на\s+замен\w+|изношен\w+)|быстро\s+(?:садится|разряжается)|вздут\w+\s+(?:акб|аккумулятор\w*|батаре\w*)", "слабый аккумулятор", 1),
    ("screen_replaced", r"(?:замен\w+|менян\w+|менял\w*|не\s+оригинал\w*|копи\w+|китайск\w+)\s+(?:экран\w*|дисплей\w*|стекл\w*)|(?:экран\w*|дисплей\w*)\s+(?:заменен\w*|не\s+оригинал\w*|копия)", "экран заменён/не оригинал", 1),
    ("repaired", r"(?:был\w*\s+)?(?:после\s+ремонта|ремонтировал\w*|вскрывал\w*|паян\w+)", "был ремонт/вскрывался", 1),
    ("cosmetic", r"царапин\w*|потертост\w*|потёртост\w*|скол\w*|вмятин\w*|помят\w*|следы\s+использования", "косметические следы", 0),
    ("parts", r"на\s+запчаст\w*|на\s+детал\w*|на\s+разбор|донор|на\s+з/ч", "на запчасти", 3),
]
_DEFECT_RX = [(c, re.compile(p), note, sev) for c, p, note, sev in DEFECT_RULES]
SEVERITY = {c: sev for c, _, _, sev in DEFECT_RULES}
_BARGAIN_NO = re.compile(r"без\s+(?:обмена\s+и\s+)?торга|торга\s+нет|не\s+торгуюсь|цена\s+окончательн\w+|торг\s+не\s*уместен|торг\s+исключ\w+|торга\s+не\s+будет|фикс\b")
_BARGAIN_YES = re.compile(r"торг\w*|уступлю|сброшу|скидк\w+")
_NEGOTIABLE = re.compile(r"договорн\w+")
_REFURB = re.compile(r"восстановленн\w+|refurb\w*|реф(?![а-я])|reburb")
_SEALED = re.compile(r"запечатан\w*|sealed|не\s+вскрывался|не\s+активирован\w*|новый\s+в\s+плен\w+|новый\s+в\s+упаковк\w+")


def parse_memory(text):
    """Объём памяти в ГБ или 0. «4/64gb» -> 64; «1tb» -> 1024."""
    t = (text or "").lower()
    if re.search(r"(?<![0-9])1\s*(?:tb|тб)\b", t):
        return 1024
    m = re.search(r"(?<![0-9])(?:\d{1,2}\s*/\s*)?(16|32|64|128|256|512)\s*(?:gb|гб|g\b|г\b|gig)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(?<![0-9a-zа-я.,])(32|64|128|256|512)(?![0-9a-zа-я.,])", t)
    return int(m.group(1)) if m else 0


def parse_battery(text):
    t = (text or "").lower()
    m = re.search(r"(?:акб|аккумулятор\w*|батаре\w*|емкость|ёмкость|battery|здоровье)\D{0,18}?(\d{2,3})\s*%", t) or \
        re.search(r"(\d{2,3})\s*%\s*(?:акб|аккумулятор\w*|батаре\w*|емкост\w*|ёмкост\w*|battery)", t)
    if m and 40 <= int(m.group(1)) <= 100:
        return int(m.group(1))
    return None


def find_defects(text):
    """{код: пометка}. Фразы с отрицанием («без царапин», «не заблокирован», «icloud чистый») не считаются."""
    t = " ".join((text or "").lower().replace("ё", "е").split())
    found = {}
    for code, rx, note, _sev in _DEFECT_RX:
        for m in rx.finditer(t):
            before = t[max(0, m.start() - 14):m.start()]
            after = t[m.end():m.end() + 16]
            if _NEG_BEFORE.search(before) and code not in ("biometric", "comms", "board", "charging"):
                continue
            if code == "lock" and re.match(r"\s*(?:чист\w*|нет|отсутств\w*|отвязан\w*|свобод\w*|снят\w*|clean|ок\b)", after):
                continue
            if code == "lock" and re.search(r"(?:без|не|нет)\s+(?:привязк\w*|блокировк\w*)\s*$", before + m.group(0)):
                continue
            found[code] = note
            break
    return found


def kit_from_text(text):
    t = (text or "").lower()
    kit = []
    if re.search(r"без\s+(?:коробки|комплекта|зарядк\w*)|только\s+телефон|телефон\s+без\s+всего", t):
        return ["только телефон"]
    for label, rx in (("коробка", r"коробк\w*|упаковк\w*"), ("зарядка/кабель", r"зарядк\w*|кабел\w*|шнур\w*|блок\s+питания"),
                      ("наушники", r"наушник\w*"), ("документы/чек", r"чек\b|документ\w*|гаранти\w*"),
                      ("чехол/стекло", r"чехол\w*|стекл\w*|бампер\w*")):
        if re.search(rx, t):
            kit.append(label)
    if re.search(r"полный\s+комплект|полная\s+комплектац\w*", t):
        kit.insert(0, "полный комплект")
    return kit


def ad_description(ad):
    for key in ("body_short", "body", "description", "text"):
        v = ad.get(key)
        if isinstance(v, str) and v.strip():
            return " ".join(v.split())[:2000]
    return ""


def rule_facts(ad):
    """Факты об объявлении по правилам (названию, параметрам и описанию, если оно есть в ответе Куфара)."""
    title = ad.get("subject") or ""
    desc = ad_description(ad)
    brand, model = param(ad, "phones_brand") or "", param(ad, "phones_model") or ""
    base = " ".join(f"{title} {brand} {model}".lower().split())
    full = f"{title}. {desc}".lower()
    label = model_label(base)
    cond_param = (param(ad, "condition") or "").lower()
    if "нов" in cond_param and "б/у" not in cond_param:
        cond = "new"
    elif _REFURB.search(full):
        cond = "refurb"
    elif _SEALED.search(full):
        cond = "new"
    elif "б/у" in cond_param or cond_param.startswith("бу"):
        cond = "used"
    else:
        cond = "unknown"
    mem = parse_memory(f"{title} {param(ad, 'phablet_phones_memory') or ''} {param(ad, 'phones_memory') or ''}") or parse_memory(desc)
    defects = find_defects(full)
    if PARTS_RE.search(full):
        defects["parts"] = "на запчасти"
    bat = parse_battery(full)
    if bat is not None and bat < 80 and "battery" not in defects:
        defects["battery"] = f"аккумулятор {bat}%"
    if _BARGAIN_NO.search(full):
        bargain = "no"
    elif _BARGAIN_YES.search(full):
        bargain = "yes"
    else:
        bargain = None
    return {
        "label": label, "mem": mem, "cond": cond, "defects": defects, "battery_pct": bat, "bargain": bargain,
        "negotiable_price": bool(_NEGOTIABLE.search(full)), "kit": kit_from_text(full), "desc": desc,
        "region": param(ad, "region") or "", "area": param(ad, "area") or "",
        "seller": "магазин" if ad.get("company_ad") else "частник",
        "price": price_byn(ad), "is_phone": True, "summary": "", "risks": [], "llm": False, "repair_cost": None,
        "model_conflict": False,
    }


def max_severity(defects):
    return max((SEVERITY.get(c, 0) for c in defects), default=-1)


# ---------- Нейросеть: разбор объявления одним запросом (JSON) ----------

_LLM = {"fails": 0, "off": False}
_DEFECT_TYPES = ["lock", "water", "board", "charging", "screen", "biometric", "camera", "comms", "battery",
                 "screen_replaced", "repaired", "cosmetic", "parts"]


def llm_enabled():
    return bool(GEMINI_KEY or ANTHROPIC_KEY) and not _LLM["off"]


def llm_json(prompt, max_tokens=700):
    """Вызов нейросети с JSON-ответом. После 2 подряд ошибок (или лимита 429) отключается до конца запуска."""
    try:
        text = _llm_call(prompt, max_tokens, json_mode=True)
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])
        _LLM["fails"] = 0
        return data if isinstance(data, dict) else None
    except Exception as e:
        _LLM["fails"] += 1
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status == 429 or _LLM["fails"] >= 2:
            _LLM["off"] = True
        log("Ошибка нейросети:", e)
        return None


def llm_analyze(ad, facts):
    """Нейросеть читает объявление и возвращает структурированные факты. Без ключа/при ошибке — None."""
    if not llm_enabled():
        return None
    info = (
        f"Название: {ad.get('subject')}\n"
        f"Цена: {facts['price']:.0f} BYN" + (" (0 = не указана/договорная)" if not facts["price"] else "") + "\n"
        f"Параметры: состояние={param(ad, 'condition')}; модель={param(ad, 'phones_model')}; "
        f"память={param(ad, 'phablet_phones_memory') or param(ad, 'phones_memory')}\n"
        f"Регион: {facts['region']}, {facts['area']}\nПродавец: {facts['seller']}\n"
        f"Модель по нашему определению: {facts['label']}\n"
        f"Описание: {facts['desc'] or 'в данных нет (только название)'}"
    )
    prompt = (
        "Ты помогаешь покупать и перепродавать телефоны на Куфаре (Беларусь). Разбери объявление.\n\n" + info + "\n\n"
        "Ответь ТОЛЬКО JSON такого вида (все тексты по-русски, коротко):\n"
        '{"is_phone": true, "memory_gb": null, "condition": "новый|б/у|восстановленный|неисправный|на запчасти|не указано", '
        '"defects": [{"type": "' + "|".join(_DEFECT_TYPES) + '", "note": "что именно"}], '
        '"screen": "не указано", "body": "не указано", "battery_pct": null, "face_touch_id": "работает|не работает|не указано", '
        '"lock": "нет|есть|не указано", "kit": [], "bargain": "торг|без торга|не указано", "repair_cost_byn": null, '
        '"summary": "1-2 коротких предложения: что продаётся и на что смотреть", "risks": ["до 3 коротких рисков"]}\n'
        "Правила: is_phone=false, только если продаётся НЕ целый телефон (чехол, стекло, коробка, запчасти для телефона, услуга, «куплю»); "
        "телефон «на запчасти» — это is_phone=true с дефектом parts. НЕ ВЫДУМЫВАЙ: чего нет в тексте — null или «не указано». "
        "repair_cost_byn заполняй только если продавец прямо назвал стоимость ремонта в BYN. Дефект записывай, только если он назван "
        "в объявлении; «без царапин», «icloud чистый» дефектами не считаются."
    )
    return llm_json(prompt, 700)


def merge_llm(facts, data):
    """Дополняет правила ответом нейросети. Дефекты складываются, неизвестное заполняется, правила не затираются."""
    if not data:
        return facts
    facts["llm"] = True
    if data.get("is_phone") is False:
        facts["is_phone"] = False
    for d in data.get("defects") or []:
        if isinstance(d, dict) and d.get("type") in _DEFECT_TYPES:
            facts["defects"].setdefault(d["type"], str(d.get("note") or d["type"])[:60])
    mem = data.get("memory_gb")
    if not facts["mem"] and isinstance(mem, (int, float)) and int(mem) in (16, 32, 64, 128, 256, 512, 1024):
        facts["mem"] = int(mem)
    bat = data.get("battery_pct")
    if facts["battery_pct"] is None and isinstance(bat, (int, float)) and 40 <= bat <= 100:
        facts["battery_pct"] = int(bat)
        if bat < 80:
            facts["defects"].setdefault("battery", f"аккумулятор {int(bat)}%")
    if facts["bargain"] is None:
        facts["bargain"] = {"торг": "yes", "без торга": "no"}.get(str(data.get("bargain")).lower())
    if facts["cond"] == "unknown":
        facts["cond"] = {"новый": "new", "б/у": "used", "восстановленный": "refurb"}.get(str(data.get("condition")).lower(), "unknown")
    rc = data.get("repair_cost_byn")
    if isinstance(rc, (int, float)) and rc > 0:
        facts["repair_cost"] = float(rc)
    if not facts["kit"] and isinstance(data.get("kit"), list):
        facts["kit"] = [str(x)[:25] for x in data["kit"][:4]]
    facts["summary"] = str(data.get("summary") or "")[:260]
    facts["risks"] = [str(x)[:80] for x in (data.get("risks") or [])[:3]]
    facts["screen"] = str(data.get("screen") or "")[:80]
    facts["body"] = str(data.get("body") or "")[:80]
    facts["face_touch"] = str(data.get("face_touch_id") or "")[:20]
    facts["lock_text"] = str(data.get("lock") or "")[:20]
    return facts


def analyze_ad(ad):
    """Правила + нейросеть (если есть) -> словарь фактов. Всегда возвращает словарь."""
    facts = rule_facts(ad)
    try:
        facts = merge_llm(facts, llm_analyze(ad, facts))
    except Exception as e:  # разбор не должен ронять мониторинг
        log("Ошибка разбора объявления:", e)
    return facts


# ---------- Рынок: реальные активные объявления-аналоги с Куфара (кеш хранится в seen.json) ----------

REGION_NAMES = ["", "Минск", "Минская обл.", "Брестская обл.", "Витебская обл.", "Гомельская обл.",
                "Гродненская обл.", "Могилёвская обл."]
F_DEF, F_NEW, F_REFURB, F_PARTS, F_SHOP, F_CRIT = 1, 2, 4, 8, 16, 32  # битовые флаги аналога
_MARKET_REFRESHES = {"n": 0}
RUN = {"deadline": 0.0}  # время (time.time()), после которого не делаем новых запросов за аналогами


def region_code(name):
    n = (name or "").lower().replace("ё", "е")
    if n.startswith("минск"):
        return 2 if "обл" in n else 1
    for i, p in enumerate(("брест", "витеб", "гомел", "гродн", "могил"), 3):
        if n.startswith(p):
            return i
    return 0


def market_key(label):
    """Ключ кеша: у iPhone SE одна выдача на все поколения."""
    return "iPhone SE" if label.startswith("iPhone SE") else label


def market_query(label):
    """Поисковая фраза для аналогов. None — модель неизвестна."""
    if not label or label == "Другое":
        return None
    if label.startswith("iPhone SE"):
        return "iphone se"
    return re.sub(r"\s+", " ", label.lower().replace("+", " plus")).strip()


def comp_item(ad, key):
    """Сжатая запись об аналоге [id, цена BYN, память ГБ, флаги, код региона, поколение SE] или None."""
    if ad.get("type") != "sell":
        return None
    title = ad.get("subject") or ""
    if looks_like_accessory(title):
        return None
    base = " ".join(f"{title} {param(ad, 'phones_brand') or ''} {param(ad, 'phones_model') or ''}".lower().split())
    lab = model_label(base)
    gen = 0
    if key == "iPhone SE":
        if not lab.startswith("iPhone SE"):
            return None
        m = re.search(r"\((\d{4})\)", lab)
        gen = int(m.group(1)) if m else 0
    elif lab != key:
        return None
    price = price_byn(ad)
    if price <= 0:
        return None
    desc = ad_description(ad)
    full = f"{title}. {desc}".lower()
    defects = find_defects(full)
    if PARTS_RE.search(full):
        defects["parts"] = "на запчасти"
    flags = 0
    sev = max_severity(defects)
    if sev >= 2 or "battery" in defects:
        flags |= F_DEF
    if sev >= 3:
        flags |= F_DEF | F_CRIT
    if "parts" in defects:
        flags |= F_PARTS
    cond_param = (param(ad, "condition") or "").lower()
    if "нов" in cond_param and "б/у" not in cond_param or _SEALED.search(full):
        flags |= F_NEW
    elif _REFURB.search(full):
        flags |= F_REFURB
    if ad.get("company_ad"):
        flags |= F_SHOP
    mem = parse_memory(f"{title} {param(ad, 'phablet_phones_memory') or ''} {param(ad, 'phones_memory') or ''}") or parse_memory(desc)
    return [int(ad["ad_id"]), int(round(price)), mem, flags, region_code(param(ad, "region")), gen]


def refresh_market(label):
    """Скачивает свежие объявления по модели и оставляет только настоящие аналоги этой модели."""
    key, query = market_key(label), market_query(label)
    ads = None
    for size in (MARKET_SIZE, 30):
        try:
            ads = fetch(query, size)
            break
        except requests.HTTPError as e:
            code = getattr(e.response, "status_code", None)
            if code in (400, 422) and size != 30:
                continue  # Куфар не принял большой размер — повторяем с обычным
            raise
    items, ids = [], set()
    for ad in ads or []:
        try:
            it = comp_item(ad, key)
        except Exception:
            continue
        if it and it[0] not in ids:
            ids.add(it[0])
            items.append(it)
    return items


def market_items(label, now=None):
    """(аналоги, возраст кеша в секундах, устарел ли, причина). Свежий кеш не трогаем; при сбое берём старый и помечаем."""
    now = now or time.time()
    key = market_key(label)
    entry = STATE["market"].get(key)
    age = (now - entry["t"]) if entry else None
    if entry and age < MARKET_TTL_H * 3600:
        return entry["items"], age, False, None
    reason = "capped"  # обновление не разрешено: лимит запросов за запуск или вышло время запуска
    if _MARKET_REFRESHES["n"] < MARKET_MAX_REFRESH and not (RUN["deadline"] and time.time() > RUN["deadline"]):
        _MARKET_REFRESHES["n"] += 1
        reason = "failed"
        try:
            items = refresh_market(label)
            STATE["market"][key] = {"t": int(now), "items": items[:150]}
            time.sleep(KUFAR_PAUSE)
            return items, 0, False, None
        except Exception as e:
            log(f"Не удалось обновить аналоги ({label}):", e)
    if entry:
        return entry["items"], age, True, None
    return None, None, False, reason


# ---------- Оценка цены и перепродажи по реальным аналогам (цены АКТИВНЫХ объявлений, не сделок) ----------

MIN_DEFECT_COMPS = 3  # аналогов с такими же проблемами обычно мало


def rnd5(x):
    return int(round(x / 5.0)) * 5


def percentile(vals, p):
    """Перцентиль с линейной интерполяцией по отсортированному списку."""
    if not vals:
        return 0.0
    k = (len(vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    return vals[f] + (vals[c] - vals[f]) * (k - f)


def price_stats(prices):
    """Статистика цен без выбросов («1 BYN» для привлечения, «99999» для отпугивания)."""
    vals = sorted(p for p in prices if p > 0)
    if not vals:
        return None
    med0 = statistics.median(vals)
    kept = sorted(p for p in vals if 0.4 * med0 <= p <= 2.2 * med0) or vals
    return {
        "n": len(kept), "dropped": len(vals) - len(kept), "min": kept[0], "max": kept[-1],
        "p10": percentile(kept, 0.10), "q1": percentile(kept, 0.25), "med": statistics.median(kept),
        "q3": percentile(kept, 0.75), "prices": kept,
    }


def _cond_ok(flags, cond):
    new, ref = bool(flags & F_NEW), bool(flags & F_REFURB)
    if cond == "new":
        return new
    if cond == "refurb":
        return ref
    return not new and not ref  # б/у и «не указано» сравниваем с б/у


def facts_gen(label):
    m = re.search(r"\((\d{4})\)", label or "")
    return int(m.group(1)) if m else 0


def select_pool(items, facts, ad_id, region=None, force_clean=False):
    """Подбор сопоставимых аналогов: сначала самые точные (модель + память + регион), потом шире, с пометками."""
    cand = [it for it in items if it[0] != ad_id and it[1] > 0]
    gen = facts_gen(facts["label"])
    if gen:
        cand = [it for it in cand if it[5] == gen]
    defects = facts["defects"]
    sev = max_severity(defects)
    bad = sev >= 2 or "battery" in defects
    mem = facts["mem"]
    reg = region_code(facts["region"]) if region is None else region
    cond = facts["cond"] if facts["cond"] != "unknown" else "used"
    if not force_clean and "parts" in defects:
        base, kind = [it for it in cand if it[3] & F_PARTS], "на запчасти"
    elif not force_clean and bad:
        base, kind = [it for it in cand if it[3] & F_DEF and not it[3] & F_PARTS], "с дефектами"
    else:
        base = [it for it in cand if not it[3] & (F_DEF | F_PARTS) and _cond_ok(it[3], cond)]
        kind = "без дефектов в названии"
    need = MIN_DEFECT_COMPS if kind != "без дефектов в названии" else MIN_COMPS
    tiers = []  # (имя, аналоги, описание, пометки, минимум аналогов)
    reg_need = max(need, 8)  # регион сужает выборку — берём его, только если аналогов всё ещё достаточно для статистики
    if mem and reg:
        tiers.append(("T1", [it for it in base if it[2] == mem and it[4] == reg], f"{mem} ГБ, регион {REGION_NAMES[reg]}", [], reg_need))
    if mem:
        tiers.append(("T2", [it for it in base if it[2] == mem], f"{mem} ГБ, вся Беларусь", [], need))
    if reg:
        tiers.append(("T3", [it for it in base if it[4] == reg], f"любая память, регион {REGION_NAMES[reg]}",
                      ["память аналогов может отличаться"], reg_need))
    tiers.append(("T4", list(base), "любая память, вся Беларусь",
                  ["память аналогов может отличаться"] if mem else ["память в объявлении не указана"], need))
    for name, pool, desc, notes, tier_need in tiers:
        priv = [it for it in pool if not it[3] & F_SHOP]
        if len(priv) >= tier_need:
            pool = priv  # частники в приоритете: магазины ставят цену «с наценкой»
        if len(pool) >= tier_need:
            return {"items": pool, "kind": kind, "tier": name, "desc": f"{kind}: {desc}", "notes": list(notes), "need": need}
    return {"items": tiers[-1][1], "kind": kind, "tier": "none", "desc": kind, "notes": [], "need": need}


def rank_verdict(price, st):
    """Вердикт по положению цены среди аналогов (пороги берутся из распределения цен, а не задаются в BYN)."""
    prices = st["prices"]
    less = sum(1 for p in prices if p < price)
    eq = sum(1 for p in prices if p == price)
    r = (less + 0.5 * eq) / len(prices)
    disc = (st["med"] - price) / st["med"]
    if r <= 0.10 and disc >= 0.10:
        return "ОЧЕНЬ ВЫГОДНО", disc
    if r <= 0.30 and disc >= 0.05:
        return "ВЫГОДНО", disc
    if r <= 0.65:
        return "СРЕДНИЙ ВАРИАНТ", disc
    if r <= 0.85:
        return "ДОРОГО", disc
    return "НЕВЫГОДНО", disc


def known_repair_cost(facts):
    """Сумма ИЗВЕСТНЫХ расходов на ремонт; None, если у какого-то дефекта цена ремонта неизвестна."""
    needs = [c for c, _ in facts["defects"].items() if SEVERITY.get(c, 0) >= 1 and c not in ("repaired", "screen_replaced")]
    total = 0.0
    for c in needs:
        v = REPAIR_COSTS.get(c)
        if isinstance(v, (int, float)):
            total += float(v)
        elif facts.get("repair_cost") and len(needs) == 1:
            total += float(facts["repair_cost"])  # продавец сам назвал цену ремонта
        else:
            return None
    return total


def confidence_of(n, tier, st, stale, mem_known, sev):
    score = 2 if n >= 12 else 1.5 if n >= 8 else 1 if n >= MIN_COMPS else 0
    score += {"T1": 1, "T2": 1, "T3": 0.5}.get(tier, 0)
    spread = (st["q3"] - st["q1"]) / st["med"] if st["med"] else 1
    score += 1 if spread <= 0.25 else 0.5 if spread <= 0.40 else 0
    score += 0 if stale else 0.5
    score -= 0 if mem_known else 1
    score -= 1 if sev >= 2 else 0
    return "высокая" if score >= 3.5 else "средняя" if score >= 2 else "низкая"


def pick_comps(pool, st, price, k=3):
    """До 3 реальных аналогов для показа: самый дешёвый, ближайший к медиане и ближайший к цене объявления."""
    items = sorted((it for it in pool if st["min"] <= it[1] <= st["max"]), key=lambda it: it[1])
    if not items:
        return []
    chosen = [items[0], min(items, key=lambda it: abs(it[1] - st["med"]))]
    if price:
        chosen.append(min(items, key=lambda it: abs(it[1] - price)))
    out = []
    for it in chosen:
        if it not in out:
            out.append(it)
    return sorted(out, key=lambda it: it[1])[:k]


def resale_eval(price, facts, st, conf):
    """Перепродажа: за сколько брать, выставлять, продавать быстро и какая прибыль. Только по известным данным."""
    r = {"verdict": "НЕ ОЦЕНЕНА", "why": "", "list": None, "quick": None, "max_buy": None, "profit_quick": None,
         "profit_list": None, "costs": None, "min_profit": None, "repair_unknown": False, "repair": None}
    sev = max_severity(facts["defects"])
    have = bool(st and st["n"] >= MIN_COMPS)
    if have:
        r["list"], r["quick"] = rnd5(st["med"]), rnd5(st["q1"])
        r["min_profit"] = max(MIN_PROFIT_BYN, MIN_PROFIT_PCT / 100 * r["quick"])
    if sev >= 3:  # блокировка, вода, плата, запчасти: стоимость и исход ремонта непредсказуемы
        r["verdict"], r["why"] = "ВЫСОКИЙ РИСК", "критичный дефект (блокировка/плата/вода/запчасти): перепродажа рискованна"
        r["repair_unknown"] = True
        return r
    if not have:
        r["why"] = "мало сопоставимых объявлений для расчёта"
        return r
    repair = known_repair_cost(facts)
    if repair is None:
        r["repair_unknown"] = True
        r["why"] = "стоимость ремонта неизвестна — прибыль не считаю"
        r["max_buy_before_repair"] = max(0, int((r["quick"] - EXTRA_COSTS_BYN - r["min_profit"]) // 5) * 5)
        return r
    r["repair"] = repair
    costs = EXTRA_COSTS_BYN + repair
    r["costs"] = costs
    r["max_buy"] = max(0, int((r["quick"] - costs - r["min_profit"]) // 5) * 5)
    if not price:
        r["why"] = "цена продавца не указана"
        return r
    r["profit_quick"] = r["quick"] - price - costs
    r["profit_list"] = r["list"] - price - costs
    if price <= r["max_buy"]:
        r["verdict"] = "ВЫГОДНА"
    elif r["profit_quick"] >= 0:
        r["verdict"], r["why"] = "ГРАНИЧНО", "прибыль ниже порога"
    elif r["profit_list"] >= r["min_profit"]:
        r["verdict"], r["why"] = "РИСКОВАННО", "прибыль только если продать по цене выставления"
    else:
        r["verdict"] = "НЕВЫГОДНА"
    return r


def resale_block(items, facts, ad_id, stale):
    """Перепродажа считается по ИСПРАВНЫМ аналогам (как будет продаваться после ремонта); регион продажи — HOME_REGION."""
    sev = max_severity(facts["defects"])
    home = region_code(HOME_REGION) if HOME_REGION else 0
    pr = select_pool(items, facts, ad_id, region=home, force_clean=True)
    st = price_stats([it[1] for it in pr["items"]]) if len(pr["items"]) >= pr["need"] else None
    conf = confidence_of(st["n"], pr["tier"], st, stale, bool(facts["mem"]), sev) if st else "низкая"
    rs = resale_eval(facts["price"], facts, st, conf)
    rs.update(conf=conf, n=st["n"] if st else len(pr["items"]), desc=pr["desc"], notes=pr["notes"])
    if st:
        rs["stats"] = {k_: st[k_] for k_ in ("min", "max", "q1", "med", "q3")}
    return rs


def appraise(ad, facts, now=None):
    """Полная оценка объявления. Не бросает исключений наружу: при сбое статус error."""
    res = {"status": "ok", "label": facts["label"], "price": facts["price"], "notes": [], "warnings": [],
           "verdict": "НЕДОСТАТОЧНО ДАННЫХ", "comps": [], "resale": None}
    try:
        if not market_query(facts["label"]):
            res["status"] = "no_model"
            return res
        items, age, stale, why = market_items(facts["label"], now)
        if items is None:
            res["status"], res["no_market_reason"] = "no_market", why
            return res
        res["age_h"], res["stale"] = (age / 3600 if age is not None else None), stale
        ad_id = int(ad["ad_id"])
        price, sev = facts["price"], max_severity(facts["defects"])
        if facts["label"] == "iPhone SE":  # поколение не указано — цены поколений сильно отличаются
            by_gen = {}
            for it in items:
                if it[0] != ad_id and it[5] and not it[3] & (F_DEF | F_PARTS):
                    by_gen.setdefault(it[5], []).append(it[1])
            res["se_gens"] = {g: (len(v), statistics.median(v)) for g, v in sorted(by_gen.items()) if len(v) >= 3}
            res["status"] = "se_gen"
            return res
        res["resale"] = resale_block(items, facts, ad_id, stale)
        pool = select_pool(items, facts, ad_id)
        res.update(n=len(pool["items"]), tier=pool["tier"], desc=pool["desc"], notes=list(pool["notes"]), need=pool["need"])
        st = price_stats([it[1] for it in pool["items"]]) if len(pool["items"]) >= pool["need"] else None
        if not st or st["n"] < pool["need"]:
            res["status"] = "few"
            res["comps"] = sorted(pool["items"], key=lambda it: it[1])[:3]
            return res
        res["stats"] = st
        res["conf"] = confidence_of(st["n"], pool["tier"], st, stale, bool(facts["mem"]), sev)
        res["target"] = (rnd5(st["p10"]), rnd5(st["q1"]))  # дешёвый, но реальный край рынка: от 10-го перцентиля до нижнего квартиля
        if not price:
            res["warnings"].append("цена не указана — вердикт невозможен")
        else:
            verdict, disc = rank_verdict(price, st)
            res["pct"] = -disc * 100  # минус — дешевле медианы
            if st["n"] < MIN_COMPS or res["conf"] == "низкая":
                if verdict == "ОЧЕНЬ ВЫГОДНО":
                    verdict = "ВЫГОДНО"  # на малой выборке «очень выгодно» не объявляем
                res["notes"].append("аналогов мало — оценка приблизительная")
            if sev >= 3 and verdict in ("ОЧЕНЬ ВЫГОДНО", "ВЫГОДНО"):
                verdict = "НЕДОСТАТОЧНО ДАННЫХ"
                res["warnings"].append("низкая цена объясняется критичным дефектом — риск высокий")
            elif sev < 2 and price < 0.5 * st["med"]:
                res["warnings"].append("цена вдвое ниже рынка: проверь блокировку/обман")
                if verdict == "ОЧЕНЬ ВЫГОДНО":
                    verdict = "ВЫГОДНО"
            res["verdict"] = verdict
        res["comps"] = pick_comps(pool["items"], st, price)
    except Exception as e:
        log("Ошибка оценки цены:", e)
        res["status"] = "error"
    return res


# ---------- Сообщение в Telegram ----------

VERDICT_ICON = {"ОЧЕНЬ ВЫГОДНО": "🟢", "ВЫГОДНО": "🟢", "СРЕДНИЙ ВАРИАНТ": "🟡", "ДОРОГО": "🔴", "НЕВЫГОДНО": "🔴",
                "НЕДОСТАТОЧНО ДАННЫХ": "⚪"}
RESALE_ICON = {"ВЫГОДНА": "🟢", "ГРАНИЧНО": "🟡", "РИСКОВАННО": "🟠", "НЕВЫГОДНА": "🔴", "ВЫСОКИЙ РИСК": "⛔", "НЕ ОЦЕНЕНА": "⚪"}
COND_RU = {"new": "новый", "used": "б/у", "refurb": "восстановленный", "unknown": "состояние не указано"}
_LOCK_CLEAN = re.compile(r"(?:icloud|айклауд)\s*(?:чист\w*|отвязан\w*|свобод\w*|нет)|без\s+(?:icloud|айклауд|привязк\w*|блокировк\w*)|"
                         r"не\s+(?:заблокирован\w*|залочен\w*)|разблокирован\w*|отвязан\w*|без\s+аккаунт\w*")
_BIO_OK = re.compile(r"(?:face\s*id|touch\s*id|фейс\s*айди|тач\s*айди|отпечат\w+)\s*(?:работает|ок\b|исправн\w*|в\s+порядке)")


def money(x):
    return f"{x:,.0f}".replace(",", " ")


def n_ads(n, adj="активных"):
    """«1 активное объявление», «3 активных объявления», «10 активных объявлений»."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {adj[:-2]}ое объявление" if adj.endswith("ых") else f"{n} объявление"
    return f"{n} {adj} " + ("объявления" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "объявлений")


def item_url(ad_id):
    return f"https://www.kufar.by/item/{ad_id}"


def lock_status(facts, title):
    """«есть» / «нет» / None (в тексте не сказано)."""
    if "lock" in facts["defects"] or str(facts.get("lock_text", "")).lower() == "есть":
        return "есть"
    text = f"{title}. {facts['desc']}".lower().replace("ё", "е")
    if str(facts.get("lock_text", "")).lower() == "нет" or _LOCK_CLEAN.search(text):
        return "нет"
    return None


def bio_status(facts, title):
    if "biometric" in facts["defects"] or str(facts.get("face_touch", "")).lower() == "не работает":
        return "не работает"
    text = f"{title}. {facts['desc']}".lower()
    if str(facts.get("face_touch", "")).lower() == "работает" or _BIO_OK.search(text):
        return "работает"
    return None


def comp_line(it):
    bits = [f"{money(it[1])} BYN"]
    if it[2]:
        bits.append(f"{it[2]} ГБ")
    if it[4]:
        bits.append(REGION_NAMES[it[4]])
    for flag, name in ((F_PARTS, "на запчасти"), (F_DEF, "с дефектами"), (F_NEW, "новый"), (F_REFURB, "восстановл."), (F_SHOP, "магазин")):
        if it[3] & flag and not (flag == F_DEF and it[3] & F_PARTS):
            bits.append(name)
    return f"• {' · '.join(bits)} — {item_url(it[0])}"


def template_summary(facts, ap):
    """Короткая сводка без нейросети: только то, что известно."""
    head = facts["label"] if facts["label"] != "Другое" else "Телефон"
    head += f" {facts['mem']} ГБ" if facts["mem"] else ""
    head += f", {COND_RU[facts['cond']]}"
    pros, cons = [], []
    if facts["battery_pct"] and facts["battery_pct"] >= 85:
        pros.append(f"акб {facts['battery_pct']}%")
    if "полный комплект" in facts["kit"] or len(facts["kit"]) >= 2:
        pros.append("комплект: " + ", ".join(facts["kit"][:3]))
    if facts["bargain"] == "yes":
        pros.append("торг")
    pct = ap.get("pct")
    if pct is not None and pct <= -5:
        pros.append(f"цена на {abs(pct):.0f}% ниже медианы")
    cons += [n for c, n in facts["defects"].items() if SEVERITY.get(c, 0) >= 1]
    if pct is not None and pct >= 5:
        cons.append(f"цена на {pct:.0f}% выше медианы")
    if facts["seller"] == "магазин":
        cons.append("магазин (обычно дороже частника)")
    out = head + "."
    if pros:
        out += " Плюсы: " + "; ".join(pros) + "."
    if cons:
        out += " Минусы: " + "; ".join(cons) + "."
    return out


def pct_text(pct):
    if abs(pct) < 1:
        return "около медианы"
    return f"на {abs(pct):.0f}% {'ниже' if pct < 0 else 'выше'} медианы"


def market_lines(facts, ap):
    st, price = ap["status"], facts["price"]
    if st == "no_model":
        return ["📊 Модель не определена — сравнить не с чем."]
    if st == "error":
        return ["📊 Оценка цены сейчас недоступна (внутренняя ошибка) — вердикт не даю."]
    if st == "no_market":
        why = "лимит запросов за запуск" if ap.get("no_market_reason") == "capped" else "Куфар не ответил"
        return [f"📊 Аналоги пока не загружены ({why}) — ценовой вердикт не даю, появится в следующих сообщениях."]
    if st == "se_gen":
        gens = ", ".join(f"{g} — медиана {money(m)} BYN ({n} шт)" for g, (n, m) in ap.get("se_gens", {}).items())
        return ["📊 iPhone SE: поколение в объявлении не указано, а цены поколений сильно разные" + (f": {gens}" if gens else "") +
                ". Уточни поколение у продавца — вердикт не даю."]
    if st == "few":
        n = ap.get("n", 0)
        found = f"нашёл только {n_ads(n, 'сопоставимых')}" if n else "сопоставимых объявлений не нашёл"
        return [f"📊 {VERDICT_ICON['НЕДОСТАТОЧНО ДАННЫХ']} <b>НЕДОСТАТОЧНО ДАННЫХ</b>: {found} "
                f"({html.escape(ap.get('desc', ''))}), нужно не меньше {ap.get('need', MIN_COMPS)}."]
    v = ap["verdict"]
    st_ = ap["stats"]
    head = f"📊 Цена: {VERDICT_ICON.get(v, '⚪')} <b>{v}</b>"
    if price and ap.get("pct") is not None:
        head += f" — {pct_text(ap['pct'])}"
    out = [head,
           f"   Аналоги: {n_ads(st_['n'])} ({html.escape(ap['desc'])}), медиана {money(st_['med'])}, "
           f"диапазон {money(st_['min'])}–{money(st_['max'])} BYN. Это цены объявлений, а не сделок.",
           f"   Надёжность оценки: {ap['conf']}"]
    for n in ap["notes"] + ap["warnings"]:
        out.append(f"   ⚠ {html.escape(n)}")
    if ap.get("stale") and ap.get("age_h") is not None:
        out.append(f"   ⚠ аналоги обновлялись {ap['age_h']:.0f} ч назад (свежие загрузить не удалось)")
    return out


def target_line(facts, ap):
    t, price = ap.get("target"), facts["price"]
    if not t or ap["status"] != "ok":
        return None
    rng = f"{money(t[0])}–{money(t[1])}" if t[0] != t[1] else money(t[1])
    line = f"🎯 Разумная цена покупки: <b>{rng} BYN</b> (дешёвая четверть активных аналогов)"
    if price:
        if price <= t[1]:
            line += "; цена продавца уже в этом диапазоне"
        else:
            line += f"; продавец просит на {money(price - t[1])} BYN больше верхней границы"
    return line


def bargain_line(facts, ap):
    price, t, b = facts["price"], ap.get("target"), facts["bargain"]
    if not price:
        txt = "цена не указана или договорная — спроси у продавца цену"
        if t:
            txt += f"; по рынку разумно {money(t[0])}–{money(t[1])} BYN"
        return "🤝 " + txt
    if b == "no":
        return "🤝 Продавец пишет «без торга» — рассчитывай на указанную цену."
    txt = "В тексте есть про торг — цена в объявлении, скорее всего, стартовая" if b == "yes" else "Про торг в тексте не сказано"
    txt += ", уступит ли и сколько — неизвестно"
    if t and ap["status"] == "ok" and price > t[1]:
        txt += f"; начни с ~{money(t[0])}, цель — не выше {money(t[1])} BYN"
    return "🤝 " + txt + "."


def signed(x):
    return f"{x:+,.0f}".replace(",", " ")


def resale_lines(facts, ap):
    rs = ap.get("resale")
    if not rs:
        return []
    v = rs["verdict"]
    approx = " (приблизительно)" if rs.get("conf") == "низкая" or rs.get("n", 0) < MIN_COMPS else ""
    why = f" — {html.escape(rs['why'])}" if rs["why"] else ""
    if rs["list"] is None:
        return [f"💎 Перепродажа: {RESALE_ICON.get(v, '⚪')} <b>{v}</b>{why}"] if rs["why"] else []
    out = [f"💎 Перепродажа: {RESALE_ICON.get(v, '⚪')} <b>{v}</b>{approx}{why}"]
    basis = f"по {n_ads(rs['n'], 'сопоставимым')} аналогам (дефекты в выдаче не видны): {html.escape(rs['desc'].split(': ', 1)[-1])}"
    if v == "ВЫСОКИЙ РИСК":
        out.append(f"   Для справки: такие же без пометок о дефектах выставляют ≈ {money(rs['list'])} BYN, быстро продаются ≈ {money(rs['quick'])} BYN "
                   f"({basis}), но стоимость и исход ремонта неизвестны.")
        return out
    out.append(f"   Выставлять ≈ <b>{money(rs['list'])}</b> BYN · быстро продать ≈ <b>{money(rs['quick'])}</b> BYN ({basis})")
    if rs["repair_unknown"]:
        if rs.get("max_buy_before_repair") is not None:
            out.append(f"   Прибыль не считаю: стоимость ремонта неизвестна. Макс. цена покупки ≈ {money(rs['max_buy_before_repair'])} "
                       "BYN минус ремонт.")
        return out
    out.append(f"   Макс. цена покупки ≈ <b>{money(rs['max_buy'])}</b> BYN (чтобы осталось ≥ {money(rs['min_profit'])} BYN прибыли)")
    if rs["profit_quick"] is not None:
        costs = []
        if rs["repair"]:
            costs.append(f"ремонт {money(rs['repair'])} BYN")
        costs.append(f"прочие расходы {money(EXTRA_COSTS_BYN)} BYN" if EXTRA_COSTS_BYN else "прочие расходы не учтены")
        out.append(f"   Прибыль: ≈ {signed(rs['profit_quick'])} BYN при быстрой продаже, ≈ {signed(rs['profit_list'])} BYN при продаже "
                   f"по цене выставления ({', '.join(costs)}). Не гарантия.")
    return out


def build_message(ad, facts, ap):
    """Сообщение в Telegram (HTML, до ~3900 символов). Только известные факты; неизвестное — «не указано»."""
    e = html.escape
    title = ad.get("subject") or facts["label"]
    price, usd = facts["price"], price_usd(ad)
    ptxt = (f"{money(price)} BYN" + (f" (~${money(usd)})" if usd else "")) if price else \
        ("цена договорная" if facts["negotiable_price"] else "цена не указана")
    place = ", ".join(x for x in (facts["region"], facts["area"]) if x) or "регион не указан"
    lines = [f"📱 <b>{e(title)}</b>", f"💰 {e(ptxt)}", f"📍 {e(place)} · {'🏪 магазин' if facts['seller'] == 'магазин' else '👤 частник'}"]
    spec = [facts["label"] if facts["label"] != "Другое" else "модель не определена"]
    spec.append(f"{facts['mem']} ГБ" if facts["mem"] else "память не указана")
    spec.append(COND_RU[facts["cond"]])
    if facts["battery_pct"]:
        spec.append(f"акб {facts['battery_pct']}%")
    if facts["kit"]:
        spec.append("комплект: " + ", ".join(facts["kit"][:3]))
    lines.append("🔧 " + e(" · ".join(spec)))
    lock, bio = lock_status(facts, title), bio_status(facts, title)
    unknown = [n for n, ok in (("блокировка/iCloud", lock is not None), ("комплект", bool(facts["kit"])),
                               ("акб", facts["battery_pct"] is not None)) if not ok]
    if facts["label"].startswith("iPhone") and bio is None:
        unknown.append("Face/Touch ID")
    known = []
    if lock:
        known.append(f"блокировка: {lock}")
    if bio:
        known.append(f"Face/Touch ID: {bio}")
    if known:
        lines.append("🔐 " + e("; ".join(known)))
    if unknown:
        lines.append("ℹ️ Не указано: " + e(", ".join(unknown)))
    if not facts["desc"]:
        lines.append("ℹ️ Описание в выдаче Куфара не получено — оценка по названию и параметрам, открой объявление.")
    defects = [n for _c, n in sorted(facts["defects"].items(), key=lambda kv: -SEVERITY.get(kv[0], 0))]
    lines.append("⚠️ " + (e("Дефекты: " + "; ".join(defects)) if defects else "Дефекты в объявлении не указаны"))
    for r in facts["risks"]:
        lines.append(f"⚠️ {e(r)}")
    lines.append("📝 " + e(facts["summary"] or template_summary(facts, ap)))
    lines.append("")
    lines += market_lines(facts, ap)
    for extra in (target_line(facts, ap), bargain_line(facts, ap)):
        if extra:
            lines.append(extra)
    res_lines = resale_lines(facts, ap)
    if res_lines:
        lines.append("")
        lines += res_lines
    comps = ap.get("comps") or []
    tail = ["🔗 " + e(ad.get("ad_link", item_url(ad["ad_id"])))]
    comp_block = (["", "Сопоставимые активные объявления (не сделки):"] + [comp_line(c) for c in comps]) if comps else []
    text = "\n".join(lines + comp_block + [""] + tail)
    if len(text) > 3900:
        text = "\n".join(lines + [""] + tail)
    return text[:3990]


# ---------- Основной цикл ----------

def load_seen():
    """seen.json: {"seen": [id...], "history": {...}, "market": {...}, "baseline": [...], "notice": N}.
    Старый формат (только seen/history или просто список id) тоже читается. None = первый запуск."""
    try:
        data = json.loads(SEEN_FILE.read_text())
    except Exception:
        return None
    if isinstance(data, list):
        data = {"seen": data}
    if not isinstance(data, dict):
        return None
    HISTORY.update(data.get("history") or {})
    seen = set(data.get("seen") or [])
    market = data.get("market")
    STATE["market"] = market if isinstance(market, dict) else {}
    base = data.get("baseline")
    # файл от старой версии: запросы iphone/samsung/ipod touch уже «запомнены», остальные запомним молча при первом заходе
    STATE["baseline"] = list(base) if isinstance(base, list) else (list(LEGACY_QUERIES) if seen else [])
    STATE["notice"] = int(data.get("notice") or 0)
    return seen


def save_seen(seen):
    """Сохраняет состояние атомарно (временный файл + замена), чтобы оборванный запуск не испортил seen.json."""
    cutoff = time.time() - 35 * 86400  # историю старше 5 недель не храним
    for k in [k for k, r in HISTORY.items() if r.get("t", 0) < cutoff]:
        del HISTORY[k]
    week = time.time() - 7 * 86400
    market = {k: v for k, v in STATE["market"].items() if isinstance(v, dict) and v.get("t", 0) > week}
    data = {"seen": sorted(seen)[-5000:], "history": HISTORY, "market": market,
            "baseline": sorted(set(STATE["baseline"])), "notice": STATE["notice"]}
    tmp = SEEN_FILE.with_name(SEEN_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, SEEN_FILE)


def pick_extra(now=None):
    """Дополнительные запросы на этот запуск: каждый ходит раз в 3 пятиминутных «слота»."""
    slot = int((now or time.time()) // 300)
    return [q for i, q in enumerate(EXTRA_QUERIES) if i % 3 == slot % 3 and q not in QUERIES]


def is_suspicious(facts, ap):
    """Цена вдвое ниже рынка без заметных дефектов — похоже на развод; в цены для недельного отчёта не берём."""
    st = ap.get("stats")
    return bool(st and facts["price"] and facts["price"] < 0.5 * st["med"] and max_severity(facts["defects"]) < 2)


def _plain(text):
    return html.unescape(re.sub(r"</?b>", "", text))


def send_ad(text):
    """'sent' — отправлено; 'retry' — не получилось, повторим в следующем запуске; 'drop' — Telegram стабильно не принимает текст."""
    try:
        tg_send(text)
        return "sent"
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        desc = ""
        try:
            desc = (resp.json().get("description") or "").lower()
        except Exception:
            pass
        if getattr(resp, "status_code", None) == 400 and any(w in desc for w in ("parse", "entit", "too long")):
            try:
                tg_send(_plain(text)[:3900], parse_mode=None)  # разметка не прошла — шлём простым текстом
                return "sent"
            except Exception as e2:
                log("Telegram не принял и простой текст, пропускаю объявление:", e2)
                return "drop"
        log("Ошибка Telegram, повторю в следующем запуске:", e)
        return "retry"
    except Exception as e:
        log("Ошибка Telegram, повторю в следующем запуске:", e)
        return "retry"


def process_ad(ad):
    """Разбор + оценка + сообщение. Возвращает (текст, ok_для_статистики) или (None, False), если это не телефон."""
    try:
        if not ad_description(ad) and not (RUN["deadline"] and time.time() > RUN["deadline"]):
            body = fetch_body(ad["ad_id"])
            if body:
                ad["body"] = body
            time.sleep(KUFAR_PAUSE)
        facts = analyze_ad(ad)
        if not facts["is_phone"]:
            return None, False
        ap = appraise(ad, facts)
        return build_message(ad, facts, ap), not is_suspicious(facts, ap)
    except Exception as e:  # оценка не должна терять объявление: шлём в прежнем формате
        log("Ошибка оценки, шлю обычное сообщение:", e)
        return format_ad(ad, ""), True


def cycle(seen, first_run):
    """Один проход. Возвращает (сколько запросов прошло, сколько запускали)."""
    t0 = time.time()
    RUN["deadline"] = t0 + RUN_BUDGET_S
    _MARKET_REFRESHES["n"] = 0
    queries = list(QUERIES) + pick_extra(t0)
    base = set() if first_run else set(STATE["baseline"])
    new_ads, quiet, learned, ok_queries = {}, {}, [], 0
    for q in queries:
        try:
            ads = [a for a in fetch(q) if isinstance(a, dict) and a.get("ad_id") is not None]
        except Exception as e:
            log(f"Ошибка Куфара ({q}):", e)
            continue
        ok_queries += 1
        if q in base:
            new_ads.update({ad["ad_id"]: ad for ad in ads if ad["ad_id"] not in seen})
        else:  # запрос запускается впервые: то, что уже висит, запоминаем молча, чтобы не завалить чат старым
            quiet.update({ad["ad_id"]: ad for ad in ads})
            learned.append(q)
        time.sleep(KUFAR_PAUSE)
    quiet = {i: a for i, a in quiet.items() if i not in seen and i not in new_ads}
    if quiet:
        seen.update(quiet)
        for ad in quiet.values():
            try:
                if basic_filter(ad):
                    record_ad(ad, True)
            except Exception as e:
                log("Пропускаю странное объявление:", ad.get("ad_id"), e)
        log(f"Новые запросы {learned}: запомнил {len(quiet)} существующих объявлений без уведомлений")
    STATE["baseline"] = sorted(set(STATE["baseline"]) | set(learned))
    if first_run:
        return ok_queries, len(queries)

    for ad_id, ad in sorted(new_ads.items()):
        if time.time() > RUN["deadline"]:
            log("Время запуска вышло — остальное подхвачу в следующий раз")
            break
        try:
            if not basic_filter(ad):
                seen.add(ad_id)
                continue
            text, ok = process_ad(ad)
            record_ad(ad, ok)
        except Exception as e:  # иначе одно «ядовитое» объявление роняло бы каждый запуск
            log("Ошибка обработки объявления, пропускаю его:", ad_id, e)
            seen.add(ad_id)
            continue
        if text is None:
            log("Не телефон (по мнению нейросети), пропускаю:", ad.get("subject"))
            seen.add(ad_id)
            continue
        result = send_ad(text)
        if result == "retry":
            continue  # не помечаем как просмотренное
        seen.add(ad_id)
        if result == "sent":
            log("Отправил:", ad.get("subject"))
            save_seen(seen)  # контрольная точка: оборванный запуск не пришлёт то же самое второй раз
            time.sleep(0.7)  # Telegram не любит очереди из десятков сообщений подряд
    return ok_queries, len(queries)


NOTICE_TEXT = (
    "🔄 Бот обновлён. Теперь он ищет ещё iPhone 7–11 (включая X/XR/XS/XS Max), iPhone SE 2016–2022 и Galaxy S7–S9, "
    "а к каждому объявлению добавляет разбор, оценку цены по аналогам с Куфара и расчёт перепродажи.\n"
    "Цены аналогов — это цены активных объявлений, а не сделок. Оценка приблизительная, прибыль не гарантируется."
)


def main():
    if not TG_TOKEN:
        sys.exit("Нужна переменная TG_TOKEN (токен от @BotFather)")
    if "--get-chat-id" in sys.argv:
        return get_chat_id()
    if not TG_CHAT_ID:
        sys.exit("Нужна переменная TG_CHAT_ID (узнать: python kufar_bot.py --get-chat-id)")

    if "--report" in sys.argv:
        load_seen()  # заполняет HISTORY
        return send_report()

    seen = load_seen()
    first_run = seen is None
    seen = seen or set()

    if "--once" in sys.argv:
        # Один проход и выход — для запуска по расписанию (GitHub Actions)
        ok_queries, total = cycle(seen, first_run)
        # Куфар не ответил (на первом запуске нужны все запросы) — состояние не трогаем и падаем,
        # иначе в следующий раз все старые объявления придут как новые
        if not ok_queries or (first_run and ok_queries < total):
            sys.exit("Куфар ответил не на все запросы — состояние не сохраняю")
        if first_run:
            tg_send("✅ Мониторинг Куфара запущен (по расписанию): " + ", ".join(QUERIES))
            STATE["notice"] = NOTICE_VERSION
        elif STATE["notice"] < NOTICE_VERSION:
            try:
                tg_send(NOTICE_TEXT)
                STATE["notice"] = NOTICE_VERSION
            except Exception as e:
                log("Не отправилось уведомление об обновлении, попробую позже:", e)
        save_seen(seen)
        return

    tg_send("✅ Мониторинг Куфара запущен: " + ", ".join(QUERIES))
    STATE["notice"] = NOTICE_VERSION
    log("Запущено. Запросы:", QUERIES, "| нейросеть:", "вкл" if (GEMINI_KEY or ANTHROPIC_KEY) else "выкл")

    while True:
        try:
            cycle(seen, first_run)
            first_run = False
            save_seen(seen)
        except Exception as e:
            log("Ошибка в цикле, продолжаю:", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
