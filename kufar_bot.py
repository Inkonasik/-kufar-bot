#!/usr/bin/env python3
"""
Куфар -> Telegram: мониторинг новых объявлений (iPhone / Samsung).

Запуск:
  pip install requests
  export TG_TOKEN=...          # токен от @BotFather
  export TG_CHAT_ID=...        # твой chat id: python kufar_bot.py --get-chat-id
  python kufar_bot.py
  python kufar_bot.py --once   # один проход и выход (для запуска по расписанию)
  python kufar_bot.py --report # недельная аналитика цен в Telegram (по истории из seen.json)

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
HISTORY = {}  # id объявления -> запись для недельной аналитики (хранится в seen.json)

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


# ---------- Основной цикл ----------

def load_seen():
    """seen.json: {"seen": [id...], "history": {...}}. Старый формат (просто список id) тоже читается."""
    try:
        data = json.loads(SEEN_FILE.read_text())
    except Exception:
        return None  # None = первый запуск
    if isinstance(data, list):
        return set(data)
    HISTORY.update(data.get("history", {}))
    return set(data.get("seen", []))


def save_seen(seen):
    cutoff = time.time() - 35 * 86400  # историю старше 5 недель не храним
    for k in [k for k, r in HISTORY.items() if r.get("t", 0) < cutoff]:
        del HISTORY[k]
    SEEN_FILE.write_text(json.dumps({"seen": sorted(seen)[-5000:], "history": HISTORY}, ensure_ascii=False))


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
        for ad in new_ads.values():
            if basic_filter(ad):
                record_ad(ad, True)
        log(f"Первый запуск: запомнил {len(new_ads)} существующих объявлений")
        return ok_queries

    for ad_id, ad in sorted(new_ads.items()):
        if basic_filter(ad):
            ok, comment = llm_check(ad)
            record_ad(ad, ok)
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

    if "--report" in sys.argv:
        load_seen()  # заполняет HISTORY
        return send_report()

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
