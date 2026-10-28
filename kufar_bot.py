#!/usr/bin/env python3
"""
Куфар -> Telegram: мониторинг новых объявлений (iPhone / iPod touch / Samsung) с оценкой цены и перепродажи.

Запуск:
  pip install requests
  export TG_TOKEN=...          # токен от @BotFather
  export TG_CHAT_ID=...        # твой chat id: python kufar_bot.py --get-chat-id
  python kufar_bot.py
  python kufar_bot.py --once   # один проход и выход (для запуска по расписанию)
  python kufar_bot.py --report # недельная аналитика цен в Telegram (по истории из seen.json и базе market_history.json)
  python kufar_bot.py --dry-run # проверка на живом Куфаре без Telegram: для каждого объявления — ушло бы оно или нет и почему

ГЛАВНОЕ ПРАВИЛО: в Telegram уходят только публикации не старше 5 минут (FRESH_MAX_AGE_S). Дата берётся из list_time, проверяется
до разбора и ещё раз прямо перед отправкой; поднятые старые объявления отсеиваются по номеру (см. originality). Лучше пропустить
публикацию, чем прислать старую. Всё увиденное (и старое тоже) копится в базе рынка и используется только для оценки цен.

Что ищет (по умолчанию): iPhone 2G…11 (включая X/XR/XS/XS Max), iPhone SE 2016–2022, iPod touch, Galaxy S1–S9.
iPhone 12 и новее, Galaxy S10 и новее, планшеты, чехлы/стёкла/запчасти и «куплю» отбрасываются.

К каждому объявлению бот добавляет: разбор (память, состояние, дефекты, аккумулятор, блокировка, комплект, торг, видимое на фото),
сравнение цены с РЕАЛЬНЫМИ активными объявлениями Куфара той же модели по категориям состояния (исправные / не подтверждено /
небольшие дефекты / заметные дефекты / неисправные; это цены объявлений, а не сделок) и два расчёта перепродажи: без ремонта и
с ремонтом — с тремя уровнями цены покупки (желательная, максимальная, отказ), ожидаемой прибылью и доходностью.
Если данных не хватает, бот пишет конкретно, чего именно (мало аналогов, дефекты у аналогов не подтверждены, не известна цена
ремонта), всё равно показывает рыночные ориентиры с пометкой «уверенность низкая» и заканчивает оценку одним выводом:
«Покупать по текущей цене» / «Покупать только после торга до N BYN» / «Не покупать для перепродажи» /
«Пока недостаточно данных для решения».

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
  MIN_COMPS          меньше стольких аналогов — оценка «приблизительная», вывод «пока недостаточно данных» (5; для аналогов с таким же дефектом — 3)
  TARGET_PROFIT_BYN  целевая ЧИСТАЯ прибыль на одну сделку, BYN. Не задана — берётся большее из MIN_PROFIT_BYN и MIN_PROFIT_PCT %
  MIN_PROFIT_BYN     минимальная целевая прибыль на сделку, BYN (15)
  MIN_PROFIT_PCT     …или столько процентов от цены быстрой продажи — берётся большее (12)
  EXTRA_COSTS_BYN    прочие расходы на сделку в BYN: дорога, упаковка… (0)
  RISK_RESERVE_PCT   резерв на непроверенные функции (скрытые неисправности), % от цены быстрой продажи (5)
  REPAIR_OVERRUN_PCT запас на удорожание ремонта из-за скрытых повреждений, % от цены ремонта (15)
  REPAIR_COSTS       известные цены ремонта в BYN, JSON: число, диапазон [мин, макс] или запчасти и работа отдельно, например
                     {"screen": [70, 100], "battery": 40, "camera": {"parts": 40, "labor": [20, 30]}}. Бот сам цену ремонта не
                     придумывает: пока она не задана, максимум покупки показывается формулой и помечается «предварительный»,
                     а вместо цены ремонта бот считает, при какой цене ремонт ещё выгоднее продажи «как есть»
  PHOTOS_MAX         сколько фото объявления смотрит нейросеть (4; 0 = фото не анализировать; нужен GEMINI_API_KEY или ANTHROPIC_API_KEY)
  HOME_REGION        где продаёшь, например «минск»: аналоги из этого региона в приоритете при оценке цены и перепродажи
                     (если не задан — берётся регион самого объявления)
  RUN_BUDGET_S       сколько секунд отводится на один запуск --once (200)
  KUFAR_PAUSE        пауза между запросами к Куфару, сек (0.4)
Ограничитель запросов к нейросети (значения по умолчанию безопасны для бесплатного лимита Gemini — 15 запросов в минуту):
  GEMINI_RPM         не больше стольких запросов к нейросети за любые 60 секунд (10)
  GEMINI_MIN_GAP_S   пауза между запросами к нейросети, сек: от конца предыдущего запроса до начала следующего (6)
  GEMINI_RETRIES     сколько раз повторять запрос после 503/500/502/504 (2: паузы 5 и 10 с или Retry-After). После 429 — один повтор;
                     второй 429 за запуск, суточная квота или просьба ждать дольше GEMINI_MAX_WAIT_S отключают нейросеть до конца запуска
  GEMINI_MAX_WAIT_S  дольше этого одного ожидания ради повтора бот не ждёт, сек (60)
Свежесть уведомлений (главное правило: в Telegram уходят только публикации не старше FRESH_MAX_AGE_S):
  FRESH_MAX_AGE_S    максимальный возраст публикации, сек (300; больше 300 поставить нельзя — можно только меньше). Граница
                     включительно: ровно 300 с — ещё отправляем, 301 с — уже нет. Возраст считается от поля list_time (единственное
                     время в API Куфара) и проверяется ещё раз прямо перед отправкой; дата «из будущего» в момент отправки не принимается
  BUMP_TOLERANCE_MIN list_time меняется и при поднятии объявления. Номера объявлений Куфар выдаёт по порядку, поэтому если уже видели
                     объявление с БОЛЬШИМ номером, опубликованное раньше чем за BUMP_TOLERANCE_MIN минут до этого, — значит,
                     это объявление создано давно и только поднято: не отправляем (30)
  MAX_PAGES          сколько страниц выдачи читать по запросу, пока на странице есть свежие объявления (3)
База рынка (market_history.json — наблюдения за объявлениями, по ним считаются аналоги):
  MARKET_DB_MAX      сколько объявлений хранить в базе (6000); при переполнении удаляются те, кого дольше всего не видели
  MARKET_DB_DAYS     через сколько дней без появления в выдаче запись удаляется (60)
  MARKET_ACTIVE_DAYS запись считается активной, если объявление видели в выдаче не позже стольких дней назад (3). В ТЕКУЩУЮ оценку цены
                     идут только активные записи (и свежая выдача); более старые — только в отдельную историческую сводку
  MESSAGE_STYLE      short (по умолчанию) — короткое сообщение; full — подробный разбор, как раньше
"""
import base64
import copy
import hashlib
import html
import json
import math
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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
NOTICE_VERSION = 2  # версия разового уведомления «бот обновлён»

KUFAR_URL = "https://api.kufar.by/search-api/v2/search/rendered-paginated"
CATEGORY = 17010  # Мобильные телефоны
SEEN_FILE = Path(__file__).with_name("seen.json")
HISTORY = {}  # id объявления -> запись для недельной аналитики (хранится в seen.json)
STATE = {"market": {}, "baseline": [], "notice": 0, "pending": {}, "marks": {}}  # кеш аналогов, «запомненные» запросы, версия уведомления,
# очередь повторов, метки номеров для защиты от поднятых объявлений (см. originality)
# состояние текущего запуска: крайнее время, счётчики запросов карточек; db_comps — сколько аналогов добавила база рынка;
# no_photo / no_refresh — на фото или обновление аналогов уже нет времени до конца «окна свежести»
RUN = {"deadline": 0.0, "cards": 0, "card_fails": 0, "img_fails": 0, "db_comps": 0, "no_photo": False, "no_refresh": False,
       "ad_until": None}  # ad_until — до какого момента объявление ещё свежее (ограничивает ожидание нейросети и фото)


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


def _env_range(name, default, lo, hi):
    """Число из переменной окружения, зажатое в [lo, hi]. Мусор, пустая строка, nan и inf заменяются значением по умолчанию."""
    try:
        v = float(os.getenv(name, default))
    except ValueError:
        return float(default)
    return float(min(hi, max(lo, v))) if math.isfinite(v) else float(default)


MARKET_TTL_H = _env_float("MARKET_TTL_HOURS", 6)      # через сколько часов обновлять кеш аналогов
MARKET_MAX_REFRESH = int(_env_float("MARKET_MAX_REFRESH", 6))  # сколько моделей обновлять за один запуск
MARKET_SIZE = int(_env_float("MARKET_SIZE", 100))      # сколько объявлений-аналогов запрашивать по модели
MIN_COMPS = int(_env_float("MIN_COMPS", 5))            # меньше аналогов — оценка «приблизительная», вывод «пока недостаточно данных»
MIN_PROFIT_BYN = _env_float("MIN_PROFIT_BYN", 15)      # целевая прибыль на сделку перепродажи, BYN
MIN_PROFIT_PCT = _env_float("MIN_PROFIT_PCT", 12)      # …или столько процентов от цены быстрой продажи (берётся большее)
EXTRA_COSTS_BYN = _env_float("EXTRA_COSTS_BYN", 0)     # прочие расходы на сделку (дорога, упаковка…), по умолчанию 0
REPAIR_COSTS = _env_json("REPAIR_COSTS")               # известные цены ремонта: {"screen": 80, "battery": [30, 50], "camera": {"parts": 40, "labor": [20, 30]}}
TARGET_PROFIT_BYN = _env_float("TARGET_PROFIT_BYN", 0) # >0: фиксированная целевая чистая прибыль на сделку, BYN (иначе max(MIN_PROFIT_BYN, MIN_PROFIT_PCT %))
RISK_RESERVE_PCT = _env_float("RISK_RESERVE_PCT", 5)   # резерв на непроверенные функции (скрытые неисправности), % от цены быстрой продажи
REPAIR_OVERRUN_PCT = _env_float("REPAIR_OVERRUN_PCT", 15)  # запас на удорожание ремонта из-за скрытых повреждений, % от его цены
PHOTOS_MAX = int(_env_float("PHOTOS_MAX", 4))          # сколько фото объявления смотрит нейросеть (0 = фото не анализировать)
HOME_REGION = os.getenv("HOME_REGION", "").strip().lower()  # где продаёшь (напр. «минск»): аналоги оттуда в приоритете
RUN_BUDGET_S = _env_float("RUN_BUDGET_S", 200)         # сколько секунд на один запуск --once
KUFAR_PAUSE = _env_float("KUFAR_PAUSE", 0.4)           # пауза между запросами к Куфару
HTTP_BACKOFF = _env_float("HTTP_BACKOFF", 1.0)         # множитель пауз между повторами запросов (0 = без пауз, для тестов)
SEND_PAUSE = _env_float("SEND_PAUSE", 0.7)             # пауза между сообщениями в Telegram
GEMINI_RPM = int(_env_range("GEMINI_RPM", 10, 1, 1000))              # не больше стольких запросов к нейросети за любые 60 секунд
GEMINI_MIN_GAP_S = _env_range("GEMINI_MIN_GAP_S", 6, 0, 60)          # пауза между запросами к нейросети (от конца предыдущего запроса)
GEMINI_RETRIES = int(_env_range("GEMINI_RETRIES", 2, 0, 5))          # повторов после 503/500/502/504 (после 429 — один повтор)
GEMINI_MAX_WAIT_S = _env_range("GEMINI_MAX_WAIT_S", 60, 0, 600)      # дольше одного такого ожидания не ждём: нейросеть отключается до конца запуска
MAX_CARD_FETCH = int(_env_float("MAX_CARD_FETCH", 25))  # сколько карточек объявлений (описаний) запрашивать за запуск
PENDING_TTL_H = _env_float("PENDING_TTL_HOURS", 24)    # сколько часов повторять неотправленное объявление
DRY_RUN = "--dry-run" in sys.argv or os.getenv("DRY_RUN", "").strip().lower() in ("1", "true", "yes")  # тестовый запуск: без Telegram и без записи
DRY_LIMIT = int(_env_float("DRY_RUN_LIMIT", 5))        # сколько объявлений показать в тестовом запуске
FRESH_MAX_AGE_S = _env_range("FRESH_MAX_AGE_S", 300, 30, 300)  # публикация старше этого (сек) в Telegram не уходит; потолок 300
FRESH_FUTURE_TOL_S = 5.0  # list_time впереди часов бота до 5 с — погрешность часов: бот ждёт, пока время станет прошлым;
# дальше — дата недостоверна. Свежей «будущая» дата не считается никогда: перед отправкой возраст должен быть ≥ 0
BUMP_TOLERANCE_MIN = _env_range("BUMP_TOLERANCE_MIN", 30, 5, 720)  # см. описание выше: защита от поднятых объявлений
REF_WINDOW_H = 1.0  # опорное объявление для проверки номера должно быть опубликовано не раньше чем за 1 ч до границы
SEED_PAGES = 6      # сколько страниц выдачи дочитать, если опорных меток не хватает (первый запуск, долгий простой)
MAX_PAGES = int(_env_range("MAX_PAGES", 3, 1, 10))     # страниц выдачи на запрос, пока на странице есть свежие
MARKET_DB_MAX = int(_env_range("MARKET_DB_MAX", 6000, 100, 100000))
MARKET_DB_DAYS = _env_range("MARKET_DB_DAYS", 60, 7, 3650)
MARKET_ACTIVE_DAYS = _env_range("MARKET_ACTIVE_DAYS", 3, 1, 14)
MESSAGE_STYLE = (os.getenv("MESSAGE_STYLE") or "short").strip().lower()

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

UA = {"User-Agent": "Mozilla/5.0"}


def http_get(url, params=None, timeout=20, tries=3):
    """GET с повтором при сетевых ошибках, 429 и 5xx. Паузы 1, 3, 8 с (или Retry-After, не больше 30 с);
    за время запуска не выходим. Последний неудачный ответ возвращается как есть, сетевая ошибка пробрасывается."""
    delays = (1, 3, 8)
    for attempt in range(1, tries + 1):
        resp = err = None
        try:
            resp = requests.get(url, params=params, timeout=timeout, headers=UA)
        except (requests.ConnectionError, requests.Timeout) as e:
            err = e
        if resp is not None and resp.status_code not in (429, 500, 502, 503, 504):
            return resp
        wait = delays[min(attempt, len(delays)) - 1]
        retry_after = (getattr(resp, "headers", None) or {}).get("Retry-After")
        if retry_after and str(retry_after).isdigit():
            wait = min(30, int(retry_after))
        out_of_time = RUN["deadline"] and time.time() + wait > RUN["deadline"]
        if attempt == tries or out_of_time:
            if err:
                raise err
            return resp
        time.sleep(wait * HTTP_BACKOFF)


_NEXT = {}  # запрос -> курсор следующей страницы из последнего ответа (пагинация Куфара: pagination.pages[label=next].token)


def _next_token(data):
    try:
        for p in (data.get("pagination") or {}).get("pages") or []:
            if isinstance(p, dict) and p.get("label") == "next" and isinstance(p.get("token"), str) and p["token"]:
                return p["token"]
    except AttributeError:
        pass
    return None


def fetch(query, size=30, cursor=None):
    """Одна страница выдачи, отсортированной по list_time (новые сверху). Курсор следующей страницы запоминается в _NEXT."""
    params = {"query": query, "sort": "lst.d", "size": size, "lang": "ru"}
    # iPod touch лежит в «Аудиотехнике» (иногда в «Мобильных телефонах») — для него ищем по всем категориям
    if not any(w in query.lower() for w in ("ipod", "айпод")):
        params["cat"] = CATEGORY
    if cursor:
        params["cursor"] = cursor
    r = http_get(KUFAR_URL, params)
    r.raise_for_status()
    data = r.json() or {}
    _NEXT[query] = _next_token(data)
    return data.get("ads", [])


def fetch_fresh(query, now=None):
    """Выдача по запросу: первая страница и следующие, пока на странице ещё есть свежие объявления (не больше MAX_PAGES).
    Поднятые объявления тоже стоят сверху, поэтому одной страницы при всплеске публикаций может не хватить."""
    _NEXT.pop(query, None)
    ads = list(fetch(query))
    pages = 1
    while pages < MAX_PAGES and _NEXT.get(query) and ads:
        last = parse_list_time((ads[-1] or {}).get("list_time")) if isinstance(ads[-1], dict) else None
        if last is None or (now or time.time()) - last > FRESH_MAX_AGE_S + 60:
            break  # дальше по сортировке только более старые
        if RUN["deadline"] and time.time() > RUN["deadline"]:
            break
        time.sleep(KUFAR_PAUSE)
        try:
            more = fetch(query, cursor=_NEXT[query])
        except Exception as e:
            log(f"Следующая страница ({query}) не получена:", e)
            break
        if not more:
            break
        ads.extend(more)
        pages += 1
    return ads


ITEM_URL = "https://api.kufar.by/search-api/v2/item/{}/rendered"


def fetch_card(ad_id):
    """Карточка объявления (в выдаче Куфар отдаёт body = null): словарь result или {}. При любой ошибке — {}.
    За запуск — не больше MAX_CARD_FETCH карточек; после 3 неудач подряд (не считая 404) карточки до конца запуска не запрашиваем."""
    if RUN["cards"] >= MAX_CARD_FETCH or RUN["card_fails"] >= 3:
        return {}
    RUN["cards"] += 1
    try:
        r = http_get(ITEM_URL.format(ad_id), timeout=15, tries=2)
        if r.status_code == 404:  # объявление уже снято — это не сбой
            return {}
        r.raise_for_status()
        res = (r.json() or {}).get("result") or {}
        RUN["card_fails"] = 0
        return res if isinstance(res, dict) else {}
    except Exception as e:
        RUN["card_fails"] += 1
        log(f"Карточка {ad_id} не получена:", e)
        return {}


def fetch_body(ad_id):
    """Только описание из карточки ('' если его нет)."""
    body = fetch_card(ad_id).get("body")
    return body if isinstance(body, str) else ""


def param(ad, key):
    for p in ad.get("ad_parameters") or []:
        if isinstance(p, dict) and p.get("p") == key:
            v = p.get("vl")
            return ", ".join(v) if isinstance(v, list) else v
    return None


def _kopecks(v):
    """Цена из API Куфара: строка или число в КОПЕЙКАХ («40000» = 400,00 BYN; проверено на живых ответах: price_usd «13580»
    = $135,80 у той же вещи, курс ≈ 2,95). 0 — цена не указана или некорректна (отрицательная, нечисловая, бесконечность)."""
    if v is None or isinstance(v, bool):
        return 0
    try:
        x = float(str(v).strip().replace(",", ".")) if not isinstance(v, (int, float)) else float(v)
    except ValueError:
        return 0
    if not math.isfinite(x) or x <= 0:
        return 0
    return round(x) / 100


def price_byn(ad):
    """Цена в BYN; 0 = не указана. Берётся только из поля price_byn — никакие догадки (нейросети, описания) её не меняют."""
    return _kopecks(ad.get("price_byn"))


def price_usd(ad):
    return _kopecks(ad.get("price_usd"))


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


# ---------- Свежесть публикации ----------
# В API Куфара (поиск и карточка) из дат есть только list_time, ISO 8601 в UTC: «2026-10-28T14:13:15Z». Это время ПОСЛЕДНЕГО
# размещения: при поднятии объявления оно меняется (проверено: объявление № 31038107 из старого диапазона номеров стояло в
# выдаче с list_time того же утра). Поэтому свежесть = list_time не старше FRESH_MAX_AGE_S И подтверждение, что это не поднятие.

_MIN_TS, _MAX_TS = 1_400_000_000, 10_000_000_000  # 2014…2286 год: за пределами — мусор, а не дата


def parse_list_time(v):
    """list_time -> unix-время (float) или None. Понимает ISO 8601 с зоной («…Z», «…+03:00»), unix-время в секундах и в
    миллисекундах (числом или строкой). Без зоны, пустое, нечисловое, вне 2014…2286 — None: такой дате доверять нельзя."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        x = float(v)
    elif isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        if re.fullmatch(r"\d{9,14}(?:\.\d+)?", s):
            x = float(s)
        else:
            try:
                dt = datetime.fromisoformat(s[:-1] + "+00:00" if s[-1:] in ("Z", "z") else s)
            except ValueError:
                return None
            if dt.tzinfo is None:
                return None  # часовой пояс не указан — время не подтверждено
            x = dt.timestamp()
    else:
        return None
    if not math.isfinite(x):
        return None
    if x >= 1e11:  # миллисекунды
        x /= 1000.0
    return x if _MIN_TS <= x < _MAX_TS else None


def fresh_status(ad, now=None, strict=False):
    """(свежее ли, причина, возраст в секундах, list_time). Причины: '' (свежее), no_date, bad_date, future, ahead, old.
    Граница включительно: возраст ровно FRESH_MAX_AGE_S — ещё свежее, на долю секунды больше — уже нет.
    Дата впереди часов бота больше чем на FRESH_FUTURE_TOL_S — future (недостоверна). На 0…5 с впереди — при отборе кандидатов
    это погрешность часов (кандидат), а при strict=True (проверка перед отправкой) — ahead: отправлять ещё нельзя."""
    raw = ad.get("list_time") if isinstance(ad, dict) else None
    lt = parse_list_time(raw)
    if lt is None:
        return False, ("no_date" if raw in (None, "") else "bad_date"), None, None
    age = (time.time() if now is None else now) - lt
    if age < -FRESH_FUTURE_TOL_S:
        return False, "future", age, lt
    if age < 0 and strict:
        return False, "ahead", age, lt
    if age > FRESH_MAX_AGE_S:
        return False, "old", age, lt
    return True, "", age, lt


def fresh_before_send(ad):
    """Проверка прямо перед отправкой: строго 0 ≤ возраст ≤ FRESH_MAX_AGE_S. Если дата на 0…5 с впереди (часы бота чуть
    отстают), ждём эти секунды и проверяем снова — «будущее» время свежим не считается."""
    ok, reason, age, lt = fresh_status(ad, strict=True)
    if reason == "ahead":
        time.sleep(-age + 0.01)
        ok, reason, age, lt = fresh_status(ad, strict=True)
    return ok, reason, age, lt


MARK_BUCKET_S = 600  # метки номеров: на каждые 10 минут list_time — самый большой номер объявления, опубликованного в эти 10 минут


def marks_add(marks, ads):
    """Обновляет метки {начало 10-минутки: [наибольший номер, его list_time]} по наблюдённым объявлениям."""
    for ad in ads:
        if not isinstance(ad, dict):
            continue
        try:
            ad_id = int(ad.get("ad_id"))
        except (TypeError, ValueError):
            continue
        lt = parse_list_time(ad.get("list_time"))
        if lt is None or ad_id <= 0:
            continue
        b = str(int(lt // MARK_BUCKET_S) * MARK_BUCKET_S)
        cur = marks.get(b)
        if not cur or ad_id > cur[0]:
            marks[b] = [ad_id, int(lt)]


def marks_cover(marks, now):
    """Есть ли опорные метки, нужные для подтверждения публикаций прямо сейчас: опубликованные в окне
    [now − 5 мин − BUMP_TOLERANCE_MIN − REF_WINDOW_H; now − BUMP_TOLERANCE_MIN]."""
    hi = now - BUMP_TOLERANCE_MIN * 60
    lo = hi - FRESH_MAX_AGE_S - REF_WINDOW_H * 3600
    return any(lo <= rt <= hi for _rid, rt in marks.values())


def seed_marks(now, query=None):
    """Первый запуск или бот долго не работал: опорных меток нет, и все настоящие новинки были бы «неподтверждёнными».
    Дочитываем выдачу широкого запроса дальше (до SEED_PAGES страниц), пока не дойдём до объявлений старше нужного окна.
    Это только метки номеров: ничего из дочитанного не отправляется (старое не проходит проверку возраста)."""
    query = query or (QUERIES[0] if QUERIES else "iphone")
    target = now - BUMP_TOLERANCE_MIN * 60 - 10 * 60
    pages, seen_ads = 0, []
    _NEXT.pop(query, None)
    try:
        page = fetch(query, size=50)
        pages = 1
        while page:
            seen_ads.extend(page)
            marks_add(STATE["marks"], page)
            last = parse_list_time(page[-1].get("list_time")) if isinstance(page[-1], dict) else None
            if (last is not None and last < target) or pages >= SEED_PAGES or not _NEXT.get(query):
                break
            if RUN["deadline"] and time.time() > RUN["deadline"]:
                break
            time.sleep(KUFAR_PAUSE)
            page = fetch(query, size=50, cursor=_NEXT[query])
            pages += 1
    except Exception as e:
        log("Опорные метки: дочитать выдачу не удалось:", e)
    log(f"Опорные метки: дочитал {pages} стр. выдачи «{query}» ({len(seen_ads)} объявлений); "
        + ("покрытие есть" if marks_cover(STATE["marks"], now) else "покрытия по-прежнему нет — новинки будут «неподтверждёнными»"))
    return seen_ads


def originality(ad_id, lt, marks):
    """Новая ли это публикация, а не поднятие старого объявления: (да/нет, причина).
    Номера Куфар раздаёт по порядку (проверено на живой выдаче). Если объявление с БОЛЬШИМ номером было опубликовано раньше
    границы «list_time − BUMP_TOLERANCE_MIN», значит, наше объявление создано ещё раньше — это поднятие (bumped): строгое
    доказательство. Если опорных наблюдений за час до границы нет вовсе, новизну подтвердить нечем (unconfirmed) — не отправляем.
    ОГРАНИЧЕНИЕ: подтверждение новизны — не доказательство. Оно означает «номер больше всех, опубликованных за час до границы»,
    то есть объявление создано не раньше примерно чем за полтора часа до публикации. Поднятие объявления, созданного недавно и
    ни разу не попавшего боту на глаза, так не отличить: API Куфара даты первой публикации не отдаёт.
    Номер НЕ делает объявление свежим: свежесть даёт только list_time; номер только отсеивает поднятые."""
    cutoff = lt - BUMP_TOLERANCE_MIN * 60
    older = [(rid, rt) for rid, rt in marks.values() if rt <= cutoff]
    if any(rid > ad_id for rid, _rt in older):
        return False, "bumped"  # строгое доказательство: объявление старше опубликованного до границы
    if not any(rt >= cutoff - REF_WINDOW_H * 3600 for _rid, rt in older):
        return False, "unconfirmed"  # опорных наблюдений рядом с границей нет — новизну не подтвердить
    return True, ""


SKIP_RU = {"no_date": "нет даты публикации", "bad_date": "дата публикации повреждена", "future": "дата публикации в будущем",
           "old": "старше допустимого возраста", "bumped": "старое объявление, поднятое заново",
           "unconfirmed": "новизну не подтвердить (мало опорных данных)", "republished": "уже было в базе с более ранней датой",
           "notified": "уже отправлено или было в выдаче при первом запуске", "expired": "устарело к моменту отправки", "ahead": "дата ещё в будущем"}


# ---------- Нейросеть (необязательно) ----------
# Все обращения к нейросети (разбор объявления, недельный отчёт) идут через _llm_call -> _llm_post. Там живут общий ограничитель
# скорости (llm_gate) и отдельная обработка 429 и 503. Разбор одного объявления — ОДИН запрос: текст и фото уходят вместе.

class LlmOff(RuntimeError):
    """Нейросеть отключена до конца запуска (повторный 429, суточная квота, ошибки): запрос не отправлялся."""


# fails — ошибок подряд; off — больше не обращаться до конца запуска; n429 — сколько ответов 429 пришло за запуск;
# last — чем кончился последний запрос (код HTTP / "ok" / "parse" / "net" / "off"); why — почему нейросеть отключена
_LLM = {"fails": 0, "off": False, "n429": 0, "last": None, "why": ""}
LLM_STATS = {"requests": 0, "ok": 0, "r429": 0, "r5xx": 0, "retries": 0, "cached": 0, "waited": 0.0}  # для строки-итога в логе
_GATE = {"stamps": [], "last": None}  # когда уходили запросы к нейросети; между проходами (в режиме цикла) НЕ сбрасывается
_TEMP_CODES = (500, 502, 503, 504, 529)  # временные ошибки сервиса (529 — «перегружен» у Claude)
_DEFAULT_429_WAIT = 30.0  # сколько ждать после 429, если сервис не сказал сколько


def _mono():
    return time.monotonic()


def _nap(sec):
    if sec > 0:
        time.sleep(sec)


def llm_reset():
    """Новый запуск (проход): нейросеть снова включена, счётчики обнулены. Ограничитель скорости (_GATE) и кеш разборов НЕ сбрасываются:
    в режиме постоянного цикла лимит «запросов в минуту» действует и между проходами."""
    _LLM.clear()
    _LLM.update(fails=0, off=False, n429=0, last=None, why="")
    LLM_STATS.update(requests=0, ok=0, r429=0, r5xx=0, retries=0, cached=0, waited=0.0)


def llm_disable(why, details=""):
    """Больше ни одного запроса к нейросети до конца запуска: остальные объявления разбираются по правилам.
    why — короткая причина (попадает и в итоговую строку лога), details — подробности для сообщения об отключении."""
    if not _LLM["off"]:
        _LLM["off"], _LLM["why"] = True, why
        log(f"Нейросеть отключена до конца запуска: {why}. {details + '. ' if details else ''}"
            "Остальные объявления разбираю по правилам, без нейросети.")


def llm_log_summary(always=True):
    """Одна строка в лог в конце запуска: сколько было запросов к нейросети, лимитов, повторов и обращений к кешу. По ней видно, работает ли ограничитель.
    always=False (режим постоянного цикла) — молчим, если за проход с нейросетью ничего не происходило."""
    if not (GEMINI_KEY or ANTHROPIC_KEY):
        return
    s = LLM_STATS
    if not always and not (s["requests"] or s["cached"] or _LLM["off"]):
        return
    state = f"отключена до конца запуска ({_LLM['why']})" if _LLM["off"] else "работала весь запуск"
    log(f"Нейросеть за запуск: запросов {s['requests']} (успешных {s['ok']}), ответов 429: {s['r429']}, "
        f"ошибок 503 и подобных: {s['r5xx']}, повторов: {s['retries']}, из кеша: {s['cached']}, "
        f"ждал из-за лимита: {s['waited']:.0f} с; {state}. Лимит: {GEMINI_RPM} запросов/мин, пауза не меньше {GEMINI_MIN_GAP_S:g} с.")


def llm_gate():
    """Общий ограничитель скорости. Ждёт, пока можно слать запрос, и занимает «слот». Условия: не меньше GEMINI_MIN_GAP_S секунд
    после конца предыдущего запроса и не больше GEMINI_RPM запросов за любые 60 секунд. Возвращает, сколько секунд ждали."""
    waited = 0.0
    while True:
        now = _mono()
        stamps = [t for t in _GATE["stamps"] if now - t < 60.0]
        _GATE["stamps"] = stamps
        need = 0.0
        if _GATE["last"] is not None and GEMINI_MIN_GAP_S > 0:
            need = _GATE["last"] + GEMINI_MIN_GAP_S - now
        if len(stamps) >= GEMINI_RPM:
            need = max(need, stamps[-GEMINI_RPM] + 60.0 - now)  # ждём, пока из минутного окна уйдёт самый старый запрос
        if need <= 1e-6 or waited >= 120:  # 120 с — страховка от зависания (часы подменены или сломаны): дольше двух минут не ждём
            break
        need += 0.05  # небольшой запас: проснуться раньше срока нельзя
        if need >= 2:
            log(f"Нейросеть: жду {need:.0f} с (лимит: не больше {GEMINI_RPM} запросов в минуту, "
                f"пауза между запросами не меньше {GEMINI_MIN_GAP_S:g} с)")
        _nap(need)
        waited += need
    _GATE["stamps"].append(now)
    _GATE["last"] = now
    LLM_STATS["waited"] += waited
    return waited


def _header(resp, name):
    try:
        for k, v in (getattr(resp, "headers", None) or {}).items():
            if str(k).lower() == name.lower():
                return v
    except Exception:
        pass
    return None


def _error_info(r):
    """Что известно об ответе-ошибке: (суточная ли квота, сколько секунд просит подождать сервис или None, короткий текст ошибки,
    названия исчерпанных квот). Секунды берутся из заголовка Retry-After (число или дата) и из тела ответа Gemini
    (RetryInfo.retryDelay, «Please retry in 12s»); если указаны оба — большее. Суточная квота — по quotaId с «PerDay».
    Формат ответов Google могут изменить: любые неожиданности разбираются молча (тогда считаем квоту минутной, а ожидание — по умолчанию)."""
    hints, daily, msg, quotas = [], False, "", []
    ra = _header(r, "Retry-After")
    if ra is not None:
        s = str(ra).strip()
        try:
            v = float(s)
        except ValueError:
            try:
                dt = parsedate_to_datetime(s)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                v = max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())  # дата в прошлом (часы расходятся) = «можно сразу»
            except (TypeError, ValueError, IndexError, OverflowError):
                v = None
        if v is not None and math.isfinite(v) and v >= 0:
            hints.append(v)
    try:
        err = (r.json() or {}).get("error") or {}
        full = str(err.get("message") or "")
        msg = re.split(r"(?<=[.!?])\s", " ".join(full.split()), maxsplit=1)[0][:140]  # первая фраза: дальше идут ссылки и справка
        for d in err.get("details") or []:
            if not isinstance(d, dict):
                continue
            for viol in d.get("violations") or []:
                qid = str(viol.get("quotaId") or "") if isinstance(viol, dict) else ""
                if qid and qid not in quotas:
                    quotas.append(qid)
                if "perday" in re.sub(r"[\W_]+", "", qid).lower():
                    daily = True
            m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str(d.get("retryDelay") or ""))
            if m:
                hints.append(float(m.group(1)))
        if not any(isinstance(d, dict) and d.get("retryDelay") for d in err.get("details") or []):
            m = re.search(r"retry in (\d+(?:\.\d+)?)s", full, re.I)
            if m:
                hints.append(float(m.group(1)))
        if re.search(r"\bper day\b|PerDay", full, re.I):
            daily = True
    except Exception:
        pass
    return daily, (max(hints) if hints else None), msg, ", ".join(quotas[:3])


def _http_error(r, msg="", quota=""):
    code = getattr(r, "status_code", "?")
    text = f"{code} {msg}".strip() if msg else f"HTTP {code}"
    return requests.HTTPError(text + (f" [квота: {quota}]" if quota else ""), response=r)


SEND_RESERVE_S = 10.0  # столько секунд оставляем на сборку и отправку сообщения после нейросети


def _ad_left():
    """Сколько секунд ещё можно тратить на разбор текущего объявления (None — ограничения нет)."""
    until = RUN.get("ad_until")
    return None if until is None else until - SEND_RESERVE_S - time.time()


def _budget_ok(wait):
    """Успеем ли мы дождаться: запуск не должен вылезти за RUN_BUDGET_S, а объявление — устареть из-за ожидания нейросети."""
    left = _ad_left()
    if left is not None and wait > left:
        return False
    return not RUN["deadline"] or time.time() + wait <= RUN["deadline"]


def _llm_post(url, **kw):
    """POST к нейросети через общий ограничитель скорости; 429 и 5xx обрабатываются по-разному.
    429: суточная квота — сразу отключаем нейросеть до конца запуска; второй 429 за запуск — тоже отключаем; первый — ждём
    (Retry-After / RetryInfo, иначе 30 с) и повторяем ОДИН раз; просят ждать дольше GEMINI_MAX_WAIT_S или дольше, чем осталось
    на запуск, — отключаем без повтора.
    503/500/502/504: до GEMINI_RETRIES повторов с растущей паузой (5, 10 с или Retry-After); просят ждать слишком долго — без повтора.
    Остальные ошибки (400, 401, 403…) и сетевые сбои не повторяются. Успех — ответ; неудача — исключение (HTTPError с .response,
    сетевая ошибка или LlmOff, если нейросеть уже отключена)."""
    retries = 0
    while True:
        if _LLM["off"]:
            raise LlmOff(_LLM["why"] or "нейросеть отключена до конца запуска")
        llm_gate()
        LLM_STATS["requests"] += 1
        try:
            r = requests.post(url, **kw)
        finally:
            _GATE["last"] = _mono()  # пауза между запросами считается от конца предыдущего
        code = getattr(r, "status_code", 200)
        if not isinstance(code, int) or code < 400:
            LLM_STATS["ok"] += 1
            return r
        daily, hint, msg, quota = _error_info(r)
        if code == 429:
            LLM_STATS["r429"] += 1
            _LLM["n429"] += 1
            q = f"квота {quota}" if quota else ""
            if daily:
                llm_disable("исчерпана суточная квота Gemini (429)",
                            (f"Квота {quota}. " if quota else "") + "Она сбрасывается в полночь по тихоокеанскому времени (около 10–11 утра по Минску); "
                            "снижение скорости запросов её не восстановит")
            elif _LLM["n429"] >= 2:
                llm_disable("повторный 429 за запуск", "Лимит запросов Gemini" + (f", {q}" if q else ""))
            else:
                wait = hint + 1 if hint is not None else _DEFAULT_429_WAIT * HTTP_BACKOFF
                if (hint if hint is not None else wait) > GEMINI_MAX_WAIT_S or not _budget_ok(wait):
                    llm_disable(f"Gemini просит подождать {wait:.0f} с (429)", "Дольше, чем можно ждать в этом запуске" + (f"; {q}" if q else ""))
                else:
                    log(f"Gemini: 429 (лимит запросов{', ' + q if q else ''}). Жду {wait:.0f} с и повторяю один раз.")
                    _nap(wait)
                    LLM_STATS["retries"] += 1
                    continue
        elif code in _TEMP_CODES:
            LLM_STATS["r5xx"] += 1
            wait = hint if hint is not None else min(5.0 * 2 ** retries, 30.0) * HTTP_BACKOFF
            if retries < GEMINI_RETRIES and wait <= GEMINI_MAX_WAIT_S and _budget_ok(wait):
                retries += 1
                LLM_STATS["retries"] += 1
                log(f"Gemini: {code} (сервис временно недоступен). Повтор {retries} из {GEMINI_RETRIES} через {wait:.0f} с.")
                _nap(wait)
                continue
        raise _http_error(r, msg, quota)


def _llm_call(prompt, max_tokens=400, json_mode=False, images=None):
    """Текст ответа нейросети: Gemini, если есть GEMINI_API_KEY, иначе Claude. images — [(mime, байты)]: в запрос уходят сами
    картинки (base64), а не ссылки на них. При ошибке бросает исключение."""
    images = images or []
    timeout = 60 if images else 30
    left = _ad_left()
    if left is not None:  # запрос не должен пережить «окно свежести» объявления
        if left < 5:
            raise LlmOff("не хватает времени до конца окна свежести")
        timeout = min(timeout, left)
    if GEMINI_KEY:
        config = {"maxOutputTokens": max_tokens}
        if json_mode:
            config["responseMimeType"] = "application/json"
        parts = [{"text": prompt}] + [{"inline_data": {"mime_type": m, "data": base64.b64encode(b).decode("ascii")}} for m, b in images]
        r = _llm_post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": GEMINI_KEY, "content-type": "application/json"},
            json={"contents": [{"parts": parts}], "generationConfig": config},
            timeout=timeout,
        )
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    content = [{"type": "image", "source": {"type": "base64", "media_type": m, "data": base64.b64encode(b).decode("ascii")}}
               for m, b in images] + [{"type": "text", "text": prompt}]
    r = _llm_post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={"model": LLM_MODEL, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content if images else prompt}]},
        timeout=timeout,
    )
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
    if DRY_RUN:  # тестовый запуск: только показываем сообщение в логе
        print("\n===== ТЕСТОВЫЙ ЗАПУСК: в Telegram НЕ отправлено =====\n" + text + "\n", flush=True)
        return
    payload = {"chat_id": TG_CHAT_ID, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    for attempt in (1, 2):
        r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", json=payload, timeout=20)
        if r.status_code == 429 and attempt == 1:  # лимит Telegram: сообщение НЕ доставлено, ждём сколько просят и повторяем один раз
            try:
                wait = int(r.json()["parameters"]["retry_after"])
            except Exception:
                wait = 3
            time.sleep(min(wait, 20) * HTTP_BACKOFF)
            continue
        break
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
    # наблюдения из базы рынка (время — когда объявление впервые попалось боту); записи из HISTORY в приоритете
    for k_, rec in _mdb_ads().items():
        lab = (rec.get("model") or {}).get("label")
        if k_ in HISTORY or not lab or lab == "Другое" or not rec.get("price_byn") or not rec.get("first_seen"):
            continue
        rows.append({"t": int(rec["first_seen"]), "m": lab, "p": float(rec["price_byn"]), "c": rec.get("condition") or "не указано",
                     "s": rec.get("title") or "", "l": rec.get("url") or "", "ok": True})
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
# Явное подтверждение хорошего состояния (слова «хорошее состояние» сюда не входят: за ними могут стоять царапины)
_GOOD = re.compile(r"идеал\w*|отличн\w+\s+состоян\w*|состояни\w*\s+(?:отличн|идеальн)\w*|как\s+нов\w+|без\s+(?:дефект\w*|царапин\w*|сколов|трещин\w*|проблем)|"
                   r"вс[её]\s+работает|полностью\s+(?:исправ\w+|рабоч\w+)")
_BOX_NO = re.compile(r"без\s+(?:коробк\w*|комплекта)|только\s+телефон|телефон\s+без\s+всего")
_BOX = re.compile(r"коробк\w*|полн\w+\s+комплект\w*|полная\s+комплектац\w*|оригинальн\w+\s+упаковк\w*")


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


_BATTERY_TERM = r"(?:акб|аккумулятор\w*|батаре\w*|battery(?:\s+health)?|здоровье\s+батареи|(?:емкость|ёмкость)\s+(?:аккумулятора|батареи|акб)|емкост\w*)"
_BATTERY_RX = (re.compile(rf"{_BATTERY_TERM}\s*[:=\-]?\s*(\d{{2,3}})\s*%"), re.compile(rf"(\d{{2,3}})\s*%\s*{_BATTERY_TERM}"))


def battery_values(text):
    """Все явно названные проценты АКБ (40…100) в порядке появления, без повторов."""
    t = " ".join((text or "").lower().replace("ё", "е").split())
    found = []
    for rx in _BATTERY_RX:
        for m in rx.finditer(t):
            v = int(m.group(1))
            if 40 <= v <= 100:
                found.append((m.start(), v))
    out = []
    for _pos, v in sorted(found):
        if v not in out:
            out.append(v)
    return out


def parse_battery(text):
    """Процент АКБ берём только из явной конструкции вроде «акб 100%» или «100% battery» — ровно то число, что написал продавец.
    Не ищем произвольное число через 18 символов: так можно принять посторонний процент за здоровье батареи.
    Если названо два разных процента («акб 100%… акб 90%»), значение не выбираем: None (противоречие отмечает rule_facts)."""
    vals = battery_values(text)
    return vals[0] if len(vals) == 1 else None


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


def _labels_in(text):
    """Разные модели, названные в тексте: заголовок режется по «/», «,», «;», «или» и каждый кусок разбирается отдельно."""
    out = []
    for seg in re.split(r"\s*(?:/|;|,|\bили\b|\bor\b)\s*", (text or "").lower()):
        if seg.strip():
            lab = model_label(" ".join(seg.split()))
            if lab != "Другое" and lab not in out:
                out.append(lab)
    return out


def _same_model(a, b):
    """iPhone SE без поколения и iPhone SE (2020) — не противоречие, а уточнение."""
    return a == b or (a.startswith("iPhone SE") and b.startswith("iPhone SE"))


def model_facts(ad):
    """(модель, уверенность, источник, противоречия). Модель не угадываем: если заголовок называет две разные модели или
    расходится с параметром «Модель» Куфара — «Другое» (оценки не будет) и запись о противоречии."""
    title = ad.get("subject") or ""
    if not isinstance(title, str):
        title = ""
    brand, model = param(ad, "phones_brand") or "", param(ad, "phones_model") or ""
    base = " ".join(f"{title} {brand} {model}".lower().split())
    label = model_label(base)
    in_title = _labels_in(title)
    p_label = model_label(" ".join(f"{brand} {model}".lower().split())) if model else "Другое"
    conflicts = []
    if len(in_title) > 1 and not all(_same_model(in_title[0], x) for x in in_title[1:]):
        conflicts.append(f"в заголовке несколько моделей: {', '.join(in_title)}")
    t_label = in_title[0] if in_title else "Другое"
    if t_label != "Другое" and p_label != "Другое" and not _same_model(t_label, p_label):
        conflicts.append(f"модель: в заголовке {t_label}, в параметрах {p_label}")
    if conflicts:
        return "Другое", "противоречие", "заголовок и параметры", conflicts
    if t_label != "Другое" and p_label != "Другое":
        # уточнение поколения SE берём из того источника, где оно названо
        lab = p_label if facts_gen(p_label) and not facts_gen(t_label) else (t_label if facts_gen(t_label) else label)
        return lab, "высокая", "заголовок и параметры совпадают", []
    if t_label != "Другое":
        return label, "высокая", "заголовок", []
    if p_label != "Другое":
        return label, "средняя", "параметр «Модель» Куфара", []
    return label, ("низкая" if label != "Другое" else "не определена"), "текст", []


def memory_facts(ad, desc):
    """(объём ГБ или 0, источник, противоречие или ''). Заголовок и параметр Куфара — основные источники, описание — запасной."""
    title = ad.get("subject") or ""
    if not isinstance(title, str):
        title = ""
    t_mem = parse_memory(title)
    p_raw = f"{param(ad, 'phablet_phones_memory') or ''} {param(ad, 'phones_memory') or ''}".strip()
    p_mem = parse_memory(p_raw) if p_raw else 0
    if t_mem and p_mem and t_mem != p_mem:
        return 0, "", f"память: в заголовке {t_mem} ГБ, в параметрах {p_mem} ГБ"
    if t_mem:
        return t_mem, "заголовок", ""
    if p_mem:
        return p_mem, "параметры Куфара", ""
    d_mem = parse_memory(desc)
    return (d_mem, "описание", "") if d_mem else (0, "", "")


def rule_facts(ad):
    """Факты об объявлении по правилам (названию, параметрам и описанию, если оно есть в ответе Куфара)."""
    title = ad.get("subject") or ""
    desc = ad_description(ad)
    full = f"{title}. {desc}".lower()
    label, model_conf, model_src, conflicts = model_facts(ad)
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
    mem, mem_src, mem_conflict = memory_facts(ad, desc)
    if mem_conflict:
        conflicts.append(mem_conflict)
    defects = find_defects(full)
    if PARTS_RE.search(full):
        defects["parts"] = "на запчасти"
    bats = battery_values(full)
    bat = bats[0] if len(bats) == 1 else None
    if len(bats) > 1:
        conflicts.append("аккумулятор: названо несколько значений — " + ", ".join(f"{v}%" for v in bats))
    if bat is not None and bat < 80 and "battery" not in defects:
        defects["battery"] = f"аккумулятор {bat}%"
    cp = (param(ad, "condition") or "").lower()
    if cond == "new" and ("б/у" in cp or defects.get("cosmetic")) and "нов" not in cp:
        conflicts.append("состояние: в тексте «новый», а в параметрах или описании — следы использования")
    if _BARGAIN_NO.search(full):
        bargain = "no"
    elif _BARGAIN_YES.search(full):
        bargain = "yes"
    else:
        bargain = None
    return {
        "label": label, "mem": mem, "cond": cond, "defects": defects, "battery_pct": bat, "bargain": bargain,
        "negotiable_price": bool(_NEGOTIABLE.search(full)), "kit": kit_from_text(full), "desc": desc,
        "good": is_good(full), "box": has_box(full),
        "photo": {"status": "none", "n": 0, "total": len(image_refs(ad)), "findings": [], "kit": [], "mismatch": "", "quality": ""},
        "region": param(ad, "region") or "", "area": param(ad, "area") or "",
        "seller": "магазин" if ad.get("company_ad") else "частник",
        "price": price_byn(ad), "is_phone": True, "summary": "", "risks": [], "llm": False, "repair_cost": None,
        "model_conflict": model_conf == "противоречие", "model_conf": model_conf, "model_src": model_src,
        "mem_src": mem_src, "conflicts": conflicts,
        "price_src": ad.get("_price_src") or PRICE_SRC_SEARCH, "price_conflict": ad.get("_price_conflict"),
        "price_unverified": bool(ad.get("_price_unverified")),
        "price_card_invalid": "_price_card_invalid" in ad, "price_card_raw": ad.get("_price_card_invalid"),
        "currency": ad.get("currency") if isinstance(ad.get("currency"), str) else "",
        # источник каждого факта: всё из текста — это слова продавца, а не проверка
        "kit_src": "текст продавца" if kit_from_text(full) else "",
    }


def max_severity(defects):
    return max((SEVERITY.get(c, 0) for c in defects), default=-1)


# ---------- Фото объявления: скачиваем и отдаём нейросети КАРТИНКИ (не ссылки) ----------

MAX_IMG_BYTES = 1_500_000
IMG_TYPES = ("image/jpeg", "image/png", "image/webp")


def image_refs(ad):
    """[(путь, yams)] из поля images объявления. Куфар отдаёт пути вида adim1/<uuid>.jpg."""
    out = []
    for im in ad.get("images") or []:
        if isinstance(im, dict) and isinstance(im.get("path"), str) and im["path"]:
            out.append((im["path"].lstrip("/"), bool(im.get("yams_storage")) or im.get("media_storage") == "yams"))
        elif isinstance(im, str) and im:
            out.append((im.lstrip("/"), False))
    return out


def image_urls(path, yams):
    """Возможные адреса одной картинки на CDN Куфара (формат проверяется при запуске: подходящий берётся автоматически)."""
    rms = [f"https://rms.kufar.by/v1/gallery/{path}", f"https://rms.kufar.by/v1/list_thumbs_2x/{path}"]
    yam = [f"https://yams.kufar.by/api/v1/kufar-ads/images/{path}?rule=gallery",
           f"https://yams.kufar.by/api/v1/kufar-ads/images/{path}?rule=list_thumbs_2x"]
    return yam + rms if yams else rms + yam


def _download_image(path, yams):
    for url in image_urls(path, yams):
        try:
            r = http_get(url, timeout=12, tries=1)
        except Exception:
            continue
        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if r.status_code == 200 and ctype in IMG_TYPES and 0 < len(r.content) <= MAX_IMG_BYTES:
            return ctype, r.content
    return None


def fetch_photos(ad):
    """(фото, причина). фото — [(mime, байты)] до PHOTOS_MAX штук; причина: '' / 'off' / 'no_photos' / 'no_download'.
    Если у объявления ни одна картинка не загрузилась 3 раза подряд, остаток запуска фото не качаем."""
    if PHOTOS_MAX <= 0:
        return [], "off"
    refs = image_refs(ad)
    if not refs:
        return [], "no_photos"
    if RUN.get("img_fails", 0) >= 3:
        return [], "no_download"
    got = []
    for path, yams in refs[:PHOTOS_MAX]:
        if RUN["deadline"] and time.time() > RUN["deadline"]:
            break
        left = _ad_left()
        if left is not None and left < 30:  # на скачивание и разбор фото времени уже нет
            break
        img = _download_image(path, yams)
        if img:
            got.append(img)
        elif not got:
            break  # первая картинка не загрузилась — остальные пробовать нет смысла
    RUN["img_fails"] = 0 if got else RUN.get("img_fails", 0) + 1
    return got, ("" if got else "no_download")


# ---------- Нейросеть: разбор объявления одним запросом (JSON) ----------

_DEFECT_TYPES = ["lock", "water", "board", "charging", "screen", "biometric", "camera", "comms", "battery",
                 "screen_replaced", "repaired", "cosmetic", "parts"]
AI_CACHE = {}  # id объявления -> {"sig", "data", "photo"}: удачные разборы нейросети. Только в памяти процесса: seen.json не затрагивается
AI_CACHE_MAX = 200  # сколько разборов помнить (самые старые вытесняются)


def llm_enabled():
    return bool(GEMINI_KEY or ANTHROPIC_KEY) and not _LLM["off"]


def llm_json(prompt, max_tokens=700, images=None):
    """Вызов нейросети с JSON-ответом. После 2 подряд ошибок (или 429, который не удалось переждать) отключается до конца запуска.
    Чем кончился запрос — в _LLM["last"]: "ok", код HTTP, "parse" (ответ не разобрался), "net" (нет связи) или "off" (уже отключена)."""
    try:
        text = _llm_call(prompt, max_tokens, json_mode=True, **({"images": images} if images else {}))
        data = json.loads(text[text.index("{"): text.rindex("}") + 1])
        _LLM["fails"] = 0
        _LLM["last"] = "ok"
        return data if isinstance(data, dict) else None
    except LlmOff:  # запрос даже не отправлялся
        _LLM["last"] = "off"
        return None
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        _LLM["last"] = status or ("parse" if isinstance(e, (ValueError, KeyError, IndexError, TypeError)) else "net")
        _LLM["fails"] += 1
        if status == 429:
            llm_disable("лимит запросов Gemini (429)")
        elif _LLM["fails"] >= 2:
            llm_disable("две ошибки нейросети подряд")
        log("Ошибка нейросети:", e)
        return None


def _ai_sig(info, refs):
    """Отпечаток того, что уходит в нейросеть: текст объявления и список его фото. Объявление изменилось — отпечаток другой."""
    h = hashlib.sha256(info.encode("utf-8"))
    for path, yams in refs:
        h.update(f"|{path}|{int(yams)}".encode("utf-8"))
    return h.hexdigest()


def _ai_store(key, sig, data, photo):
    if key not in AI_CACHE and len(AI_CACHE) >= AI_CACHE_MAX:
        AI_CACHE.pop(next(iter(AI_CACHE)))  # самый старый
    AI_CACHE[key] = {"sig": sig, "data": copy.deepcopy(data), "photo": dict(photo)}


PHOTO_SCHEMA = (', "photos": {"findings": [{"part": "экран|задняя крышка|рамка/корпус|камера|разъём|следы вскрытия|другое", '
                '"kind": "screen|cosmetic|camera|opened|other", "what": "что именно видно, коротко", '
                '"confidence": "высокая|средняя|низкая", "check": "что проверить при осмотре"}], '
                '"kit_visible": [], "mismatch": "", "quality": "хорошее|среднее|плохое"}')
PHOTO_RULES = (
    "\nК объявлению приложены фотографии (по порядку). Заполни поле photos. ПРАВИЛА для фото: описывай ТОЛЬКО то, что действительно видно. "
    "По фото НЕЛЬЗЯ определить исправность функций (Face ID/Touch ID, iCloud и блокировки, ёмкость аккумулятора, работу камер, динамиков, "
    "микрофона, сети, зарядки) — не заявляй об этом. Можно: трещины, сколы, царапины, вмятины, деформацию рамки, следы вскрытия, "
    "пятна и выгорание на экране (если видно), состояние задней крышки и камеры снаружи, видимые аксессуары. "
    "findings — по одному элементу на каждый видимый дефект; если видимых дефектов нет — пустой массив. "
    "Если фото тёмные, размытые или их мало — quality=плохое и не гадай. kit_visible — только то, что видно на фото "
    "(коробка, зарядное устройство/кабель, наушники, чехол, защитное стекло, документы/чек); не утверждай, что аксессуары оригинальные. "
    "mismatch — только если фото противоречат описанию (например, в тексте «идеал», а на экране трещина), иначе пустая строка."
)


def llm_analyze(ad, facts):
    """Нейросеть используется только для описания видимых деталей на реально загруженных фото.
    Характеристики, цена, аккумулятор, состояние, комплект и риски из текста определяются правилами, не ответом LLM."""
    ph = facts["photo"]
    if not (GEMINI_KEY or ANTHROPIC_KEY):
        ph["status"] = "no_llm"
        return None
    if PHOTOS_MAX <= 0:
        ph["status"] = "off"
        return None
    refs = image_refs(ad)
    if not refs:
        ph["status"] = "no_photos"
        return None
    info = (
        f"Название объявления: {ad.get('subject') or 'не указано'}\n"
        f"Цена из данных Куфара: {facts['price']:.0f} BYN" + (" (цена не указана/договорная)" if not facts["price"] else "") + "\n"
        f"Описание продавца: {facts['desc'] or 'описание не получено'}\n"
        "Эти текстовые сведения даны только для проверки возможного противоречия с фотографиями. "
        "Не извлекай и не угадывай из них цену, модель, память, процент АКБ или работоспособность."
    )
    key, sig = str(ad.get("ad_id")), _ai_sig(info, refs[:PHOTOS_MAX])
    hit = AI_CACHE.get(key)
    if hit and hit["sig"] == sig:
        LLM_STATS["cached"] += 1
        log("Нейросеть: визуальный разбор этого объявления уже есть в кеше:", key)
        ph.update(copy.deepcopy(hit["photo"]))
        return copy.deepcopy(hit["data"])
    if _LLM["off"]:
        ph["status"] = "llm_off"
        return None
    if RUN.get("no_photo"):
        ph["status"] = "no_time"
        return None

    images, why = fetch_photos(ad)
    if not images:
        ph["status"] = why or "no_download"
        return None

    prompt = (
        "Ты анализируешь ТОЛЬКО фотографии объявления б/у телефона. Не оценивай стоимость и не определяй модель или характеристики.\n\n"
        + info + "\n\n"
        'Ответь ТОЛЬКО JSON вида {"photos": {"findings": [{"part":"экран|задняя крышка|рамка/корпус|камера|разъём|следы вскрытия|другое", '
        '"kind":"screen|cosmetic|camera|opened|other", "what":"короткое описание только видимого", '
        '"confidence":"высокая|средняя|низкая", "check":"что проверить при осмотре"}], '
        '"kit_visible": [], "mismatch": "", "quality": "хорошее|среднее|плохое"}}.\n'
        "Если дефект не очевиден, не утверждай, что он есть: укажи низкую уверенность или не включай его. "
        "Не выводи аккумулятор, цену, память, Face ID, блокировки, камеры/звук как работающие или неработающие по фото. "
        "В комплект добавляй только предметы, которые явно видны на фото. Если фото недостаточно информативны, укажи плохое качество.\n"
        + PHOTO_RULES
    )
    data = llm_json(prompt, 700, images=images)
    if isinstance(data, dict) and isinstance(data.get("photos"), dict):
        photo = {"status": "analyzed", "n": len(images)}
        ph.update(photo)
        _ai_store(key, sig, data, photo)
        return data
    transient = _LLM.get("last") in _TEMP_CODES or _LLM.get("last") == "net"
    ph["status"] = "llm_off" if _LLM["off"] or transient else "error"
    return None


def merge_llm(facts, data):
    """Из ответа нейросети принимаем только визуальные наблюдения. Текстовые характеристики не доверяем LLM."""
    if not isinstance(data, dict):
        return facts
    if facts["photo"].get("status") == "analyzed" and isinstance(data.get("photos"), dict):
        facts["llm"] = True
        merge_photos(facts, data["photos"])
    return facts


PHOTO_KINDS = ("screen", "cosmetic", "camera", "opened", "other")
PHOTO_KIT = ("коробка", "зарядное устройство/кабель", "наушники", "чехол", "защитное стекло", "документы/чек")
CONF_RU = ("высокая", "средняя", "низкая")


def merge_photos(facts, ph):
    """Что нейросеть увидела на фото. В дефекты попадает только то, в чём она уверена («высокая») и если фото нормального качества;
    остальное показывается как «возможно, проверить». Исправность функций по фото не определяется."""
    out = facts["photo"]
    finds = []
    for f in (ph.get("findings") or [])[:6]:
        if not isinstance(f, dict) or not str(f.get("what") or "").strip():
            continue
        conf = str(f.get("confidence") or "").lower()
        finds.append({"part": str(f.get("part") or "")[:30], "kind": f.get("kind") if f.get("kind") in PHOTO_KINDS else "other",
                      "what": str(f["what"]).strip()[:90], "conf": conf if conf in CONF_RU else "низкая",
                      "check": str(f.get("check") or "")[:90]})
    out["findings"] = finds
    kit = ph.get("kit_visible")
    out["kit"] = [x for x in kit if x in PHOTO_KIT] if isinstance(kit, list) else []
    out["mismatch"] = str(ph.get("mismatch") or "")[:140]
    out["quality"] = str(ph.get("quality") or "")[:20]
    # Фото-наблюдения показываем отдельно, но не превращаем автоматически в дефекты для расчёта цены.
    # Так ошибочная визуальная догадка модели не меняет рекомендацию без подтверждения продавцом.


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
# Виды дефектов в заголовке аналога (старшие биты тех же флагов): нужны, чтобы отличать «такой же дефект» от «какой-то дефект».
# У аналогов из старого кеша этих битов нет — такие аналоги «таким же дефектом» не считаются (подтвердить нечем).
F_KINDS = {"lock": 1 << 6, "water": 1 << 7, "board": 1 << 8, "charging": 1 << 9, "screen": 1 << 10,
           "biometric": 1 << 11, "camera": 1 << 12, "comms": 1 << 13, "battery": 1 << 14}
KIND_NAMES = {"lock": "блокировка", "water": "вода", "board": "плата", "charging": "зарядка", "screen": "экран",
              "biometric": "Face/Touch ID", "camera": "камера", "comms": "связь/звук", "battery": "слабый акб"}


def kinds_mask(defects):
    """Битовая маска видов дефектов из словаря {код: пометка}."""
    return sum(bit for code, bit in F_KINDS.items() if code in defects)


# Ещё флаги аналога: мелкие дефекты без «вида» (царапины, замена экрана, был ремонт), явное «идеал/всё работает», коробка.
F_COSM, F_GOOD, F_BOX = 1 << 15, 1 << 16, 1 << 17
KIND_FAULT = sum(F_KINDS[k] for k in ("lock", "water", "board", "charging", "biometric", "comms"))
KIND_VISIBLE = F_KINDS["screen"] | F_KINDS["camera"]
# Категории состояния от лучшей к худшей. «ok» — исправность подтверждена словами («идеал», «всё работает»);
# «unk» — дефекты не названы, но и исправность не подтверждена: по умолчанию большинство объявлений именно такие.
CATS = ("ok", "unk", "minor", "visible", "faulty")
CAT_NAMES = {"ok": "исправные", "unk": "состояние не подтверждено", "minor": "небольшие дефекты",
             "visible": "заметные дефекты", "faulty": "неисправные"}
CAT_LEVEL = {"ok": 0, "unk": 0, "minor": 1, "visible": 2, "faulty": 3}  # «глубина» повреждения для расчёта между категориями


def is_good(text):
    """Явное подтверждение хорошего состояния в тексте (не «не идеал»)."""
    t = " ".join((text or "").lower().replace("ё", "е").split())
    return any(not _NEG_BEFORE.search(t[max(0, m.start() - 14):m.start()]) for m in _GOOD.finditer(t))


def has_box(text):
    """В тексте названа коробка / полный комплект (и не написано «без коробки»)."""
    t = " ".join((text or "").lower().split())
    return bool(_BOX.search(t)) and not _BOX_NO.search(t)


def defect_flags(defects, good=False):
    """Флаги состояния по словарю дефектов {код: пометка} — одни и те же для аналога и для самого объявления."""
    flags = kinds_mask(defects)
    sev = max_severity(defects)
    if sev >= 2 or "battery" in defects:
        flags |= F_DEF
    if sev >= 3:
        flags |= F_DEF | F_CRIT
    if "parts" in defects:
        flags |= F_PARTS
    if any(c in defects for c in ("cosmetic", "screen_replaced", "repaired")):
        flags |= F_COSM
    if good and not flags:
        flags |= F_GOOD
    return flags


def comp_cat(flags):
    """Категория состояния по флагам. None — состояние не определить (дефект есть, но вид неизвестен: запись из старого кеша)."""
    kinds = flags & sum(F_KINDS.values())
    if flags & (F_PARTS | F_CRIT) or kinds & KIND_FAULT:
        return "faulty"
    if kinds & KIND_VISIBLE:
        return "visible"
    if flags & F_DEF and not kinds:
        return None
    if kinds or flags & F_COSM:  # остался только слабый аккумулятор или мелочи
        return "minor"
    return "ok" if flags & F_GOOD else "unk"


def ad_cat(facts):
    return comp_cat(defect_flags(facts["defects"], facts.get("good")))


_MARKET_REFRESHES = {"n": 0}


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


def title_key(title):
    """Короткий отпечаток заголовка (нижний регистр, без пробелов): одинаковые объявления-дубли дают одинаковый отпечаток."""
    t = re.sub(r"[^0-9a-zа-я]+", "", normalize_text(title if isinstance(title, str) else ""))
    return hashlib.sha1(t.encode("utf-8")).hexdigest()[:8] if t else ""


def comp_item(ad, key):
    """Сжатая запись об аналоге [id, цена BYN, память ГБ, флаги, код региона, поколение SE, отпечаток заголовка] или None.
    Не аналоги: «куплю/скупка/муляж», аксессуары, другая модель, объявления без цены."""
    if ad.get("type") != "sell":
        return None
    title = ad.get("subject") or ""
    if not isinstance(title, str) or any(w in title.lower() for w in BAD_WORDS):
        return None
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
    bat = parse_battery(full)
    if bat is not None and bat < 80:
        defects.setdefault("battery", f"аккумулятор {bat}%")  # так же, как для самого объявления (rule_facts)
    flags = defect_flags(defects, is_good(full))
    if has_box(full):
        flags |= F_BOX
    cond_param = (param(ad, "condition") or "").lower()
    if "нов" in cond_param and "б/у" not in cond_param or _SEALED.search(full):
        flags |= F_NEW
    elif _REFURB.search(full):
        flags |= F_REFURB
    if ad.get("company_ad"):
        flags |= F_SHOP
    mem = parse_memory(f"{title} {param(ad, 'phablet_phones_memory') or ''} {param(ad, 'phones_memory') or ''}") or parse_memory(desc)
    return [int(ad["ad_id"]), int(round(price)), mem, flags, region_code(param(ad, "region")), gen, title_key(title)]


def dedupe_items(items):
    """Убирает повторы: тот же номер или явный дубль (тот же заголовок, цена, память и регион под разными номерами)."""
    out, ids, sig = [], set(), set()
    for it in items:
        if it[0] in ids:
            continue
        s = (it[6], it[1], it[2], it[4]) if len(it) > 6 and it[6] else None
        if s and s in sig:
            continue
        ids.add(it[0])
        if s:
            sig.add(s)
        out.append(it)
    return out


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
    items = []
    for ad in ads or []:
        try:
            it = comp_item(ad, key)
        except Exception:
            continue
        if it:
            items.append(it)
            mdb_observe(ad, comp=it, key=key)  # каждое увиденное объявление-аналог пополняет базу рынка
    marks_add(STATE["marks"], ads or [])
    return dedupe_items(items)


def _merge_db(items, key, now):
    """Аналоги из свежей выдачи + АКТИВНЫЕ наблюдения из базы рынка (их цена — последняя увиденная), без повторов номеров.
    Возвращает (список, сколько добавлено из базы)."""
    have = {x[0] for x in items}
    extra = [it for it in mdb_comps(key, now) if it[0] not in have]
    merged = dedupe_items(list(items) + extra)
    return merged, len(merged) - len(dedupe_items(list(items)))


def market_items(label, now=None):
    """(аналоги, возраст кеша в секундах, устарел ли, причина). Свежий кеш не трогаем; при сбое берём старый и помечаем.
    К выдаче добавляются наблюдения из базы рынка (market_history.json): число добавленных — в RUN["db_comps"].
    Куфар недоступен и кеша нет, но в базе хватает наблюдений — оценка идёт по базе (помечается как устаревшая)."""
    now = now or time.time()
    key = market_key(label)
    entry = STATE["market"].get(key)
    age = (now - entry["t"]) if entry else None
    RUN["db_comps"] = 0
    if entry and age < MARKET_TTL_H * 3600:
        items, RUN["db_comps"] = _merge_db(entry["items"], key, now)
        return items, age, False, None
    reason = "capped"  # обновление не разрешено: лимит запросов за запуск, вышло время запуска или окно свежести
    if (_MARKET_REFRESHES["n"] < MARKET_MAX_REFRESH and not (RUN["deadline"] and time.time() > RUN["deadline"])
            and not RUN.get("no_refresh")):
        _MARKET_REFRESHES["n"] += 1
        reason = "failed"
        try:
            items = refresh_market(label)
            STATE["market"][key] = {"t": int(now), "items": items[:150]}
            time.sleep(KUFAR_PAUSE)
            items, RUN["db_comps"] = _merge_db(items, key, now)
            return items, 0, False, None
        except Exception as e:
            log(f"Не удалось обновить аналоги ({label}):", e)
    if entry and age <= MARKET_ACTIVE_DAYS * 86400:  # кеш старше окна активности — уже не текущие предложения
        items, RUN["db_comps"] = _merge_db(entry["items"], key, now)
        return items, age, True, None
    db = mdb_comps(key, now)
    if len(db) >= REF_MIN:
        RUN["db_comps"] = len(db)
        return dedupe_items(db), None, True, None
    return None, None, False, reason


# ---------- Оценка цены и перепродажи по реальным аналогам (цены АКТИВНЫХ объявлений, не сделок) ----------

MIN_DEFECT_COMPS = 3  # аналогов с такими же проблемами обычно мало


def rnd5(x):
    """До ближайших 5 BYN — для медианы (цена выставления). Быстрая продажа и максимум покупки округляются ВНИЗ (floor5),
    резерв и целевая прибыль — ВВЕРХ (ceil5): так округление никогда не делает сделку выгоднее, чем она есть."""
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


CLEAN_KIND = "без дефектов в названии"
SAME_KIND = "с таким же дефектом"


def _cands(items, facts, ad_id):
    """Аналоги той же модели (у iPhone SE — того же поколения), без самого объявления."""
    cand = [it for it in items if it[0] != ad_id and it[1] > 0]
    gen = facts_gen(facts["label"])
    return [it for it in cand if it[5] == gen] if gen else cand


def _tier_pick(base, mem, reg, need, kind):
    """Уровни подбора: сначала самые точные (память + регион), потом шире, с пометками. Частники в приоритете."""
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
        priv_only = len(priv) >= tier_need
        if priv_only:
            pool = priv  # частники в приоритете: магазины ставят цену «с наценкой»
        if len(pool) >= tier_need:
            return {"items": pool, "kind": kind, "tier": name, "desc": f"{kind}: {desc}", "place": desc, "notes": list(notes),
                    "need": need, "base_n": len(base), "priv": priv_only}
    last = tiers[-1]  # ни один уровень не набрал минимум: отдаём самый широкий набор, решает вызывающий код
    return {"items": last[1], "kind": kind, "tier": "none", "desc": f"{kind}: {last[2]}", "place": last[2], "notes": list(last[3]),
            "need": need, "base_n": len(base), "priv": False}


def select_pool(items, facts, ad_id, region=None, force_clean=False):
    """Подбор сопоставимых аналогов (см. _tier_pick). Тип выборки зависит от дефектов объявления:
    «на запчасти» / «такой же дефект» / «без пометок о дефектах в заголовке».
    У аналогов видны только заголовки (описания бот не читает), поэтому «такой же дефект» = тот же вид дефекта назван в заголовке."""
    cand = _cands(items, facts, ad_id)
    defects = facts["defects"]
    sev = max_severity(defects)
    bad = sev >= 2 or "battery" in defects
    reg = region_code(facts["region"]) if region is None else region
    cond = facts["cond"] if facts["cond"] != "unknown" else "used"
    if not force_clean and "parts" in defects:
        base, kind = [it for it in cand if it[3] & F_PARTS], "на запчасти"
    elif not force_clean and bad:
        mine = kinds_mask(defects)
        base = [it for it in cand if it[3] & F_DEF and not it[3] & F_PARTS and (it[3] & mine) == mine]
        kind = SAME_KIND
    else:
        base = [it for it in cand if not it[3] & (F_DEF | F_PARTS | F_COSM) and _cond_ok(it[3], cond)]
        kind = CLEAN_KIND
    need = MIN_DEFECT_COMPS if kind != CLEAN_KIND else MIN_COMPS
    return _tier_pick(base, facts["mem"], reg, need, kind)


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


REF_MIN = 3            # меньше стольких аналогов ориентир цены не считаем вообще; меньше MIN_COMPS — считаем, но «очень приблизительно»
BARGAIN_REACH = 0.15       # торгом реально снять до 15% цены
BARGAIN_REACH_HINT = 0.25  # …до 25%, если продавец сам пишет про торг


def ceil5(x):
    return int(-(-x // 5) * 5)


def floor5(x):
    return max(0, int(x // 5) * 5)


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None


def _rng(v):
    """Число или [мин, макс] -> (мин, макс); иначе None."""
    n = _num(v)
    if n is not None:
        return n, n
    if isinstance(v, (list, tuple)) and len(v) == 2:
        lo, hi = _num(v[0]), _num(v[1])
        if lo is not None and hi is not None:
            return min(lo, hi), max(lo, hi)
    return None


def repair_range(code):
    """Цена ремонта из REPAIR_COSTS: (мин, макс, пояснение) или None. Формы записи: 80 | [70, 110] |
    {"parts": [40, 60], "labor": 30} (запчасти и работа отдельно, каждое — число или [мин, макс])."""
    v = REPAIR_COSTS.get(code)
    r = _rng(v)
    if r:
        return r[0], r[1], "REPAIR_COSTS"
    if isinstance(v, dict):
        parts, labor = _rng(v.get("parts")), _rng(v.get("labor"))
        if parts or labor:
            p, w = parts or (0.0, 0.0), labor or (0.0, 0.0)
            return p[0] + w[0], p[1] + w[1], "REPAIR_COSTS: запчасти + работа"
    return None


def repair_plan(facts):
    """Что нужно чинить и сколько это стоит. Цену ремонта бот не выдумывает: она берётся только из REPAIR_COSTS или из слов
    продавца (если дефект один). Неизвестное остаётся неизвестным.
    {"needs": [названия], "items": [{code, name, lo, hi, src}], "unknown": [названия], "lo": сумма, "hi": сумма}"""
    needs = [(c, n) for c, n in facts["defects"].items() if SEVERITY.get(c, 0) >= 1 and c not in ("repaired", "screen_replaced")]
    items, unknown = [], []
    for c, name in needs:
        r = repair_range(c)
        if r:
            items.append({"code": c, "name": name, "lo": r[0], "hi": r[1], "src": r[2]})
        elif facts.get("repair_cost") and len(needs) == 1:
            v = float(facts["repair_cost"])
            items.append({"code": c, "name": name, "lo": v, "hi": v, "src": "по словам продавца"})
        else:
            unknown.append(name)
    return {"needs": [n for _c, n in needs], "items": items, "unknown": unknown,
            "lo": sum(i["lo"] for i in items), "hi": sum(i["hi"] for i in items)}


def known_repair_cost(facts):
    """Верхняя граница ИЗВЕСТНЫХ расходов на ремонт; None, если у какого-то дефекта цена ремонта неизвестна."""
    rp = repair_plan(facts)
    return None if rp["unknown"] else rp["hi"]


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


def pick_basis(items, facts, ad_id, reg):
    """На чём строится оценка.
    'defect'  — аналоги с таким же дефектом (по заголовкам): их цена уже учитывает дефект, ремонт из неё не вычитается;
    'general' — общий рынок: аналоги без пометок о дефектах в заголовке. Если у объявления есть дефект, состояние таких
                аналогов НЕ подтверждено — оценка по ним приблизительная.
    Возвращает (основа, пул аналогов, статистика цен или None, сведения об аналогах с таким же дефектом)."""
    pool = select_pool(items, facts, ad_id, region=reg)
    like = pool["kind"] != CLEAN_KIND
    info = {"like_n": pool["base_n"] if like else None, "like_need": pool["need"] if like else None,
            "like_kind": pool["kind"] if like else None}
    if like:
        st = price_stats([it[1] for it in pool["items"]]) if len(pool["items"]) >= pool["need"] else None
        if st and st["n"] >= pool["need"]:
            return "defect", pool, st, info
        pool = select_pool(items, facts, ad_id, region=reg, force_clean=True)
    st = price_stats([it[1] for it in pool["items"]]) if len(pool["items"]) >= REF_MIN else None
    return "general", pool, st, info


SNAP_NEED = 3  # минимум объявлений в категории, чтобы показывать медиану


def _row(pool_items):
    """Строка сводки: число объявлений и статистика цен (без выбросов)."""
    st = price_stats([it[1] for it in pool_items])
    return {"n": st["n"] if st else 0, "st": st, "items": pool_items}


def _scope(items, mem):
    """Один охват для сравнения категорий: та же память (если известна), вся Беларусь; частники, если их хватает.
    Если аналогов той же памяти меньше SNAP_NEED, а всех вместе хватает — берём любую память (mixed)."""
    same = [it for it in items if it[2] == mem] if mem else list(items)
    mixed = False
    if mem and len(same) < SNAP_NEED and len(items) >= SNAP_NEED:
        same, mixed = list(items), True
    priv = [it for it in same if not it[3] & F_SHOP]
    shops = False
    if len(priv) >= SNAP_NEED:
        same = priv
    else:
        shops = any(it[3] & F_SHOP for it in same)
    row = _row(same)
    row.update(all=len(items), mixed=mixed, shops=shops)
    return row


def market_snapshot(items, facts, ad_id):
    """Цены АКТИВНЫХ объявлений той же модели по категориям состояния (CATS). Учитываются только дефекты, названные в тексте
    аналога: «дефектов нет в заголовке» не значит «исправен», поэтому такие аналоги — категория «состояние не подтверждено»."""
    cond = facts["cond"] if facts["cond"] != "unknown" else "used"
    cand = [it for it in _cands(items, facts, ad_id) if _cond_ok(it[3], cond)]
    by, undefined = {c: [] for c in CATS}, 0
    for it in cand:
        c = comp_cat(it[3])
        if c is None:
            undefined += 1  # дефект есть, а какой — неизвестно (запись из старого кеша): в категории не берём
        else:
            by[c].append(it)
    return {"rows": {c: _scope(by[c], facts["mem"]) for c in CATS}, "total": len(cand), "undefined": undefined,
            "mem": facts["mem"], "cand": cand}


def kind_row(snap, kind):
    """Аналоги, у которых в тексте назван дефект этого вида (и нет «на запчасти»): строка со статистикой."""
    bit = F_KINDS[kind]
    return _scope([it for it in snap["cand"] if it[3] & bit and not it[3] & F_PARTS], snap["mem"])


def _interp(anchors, level):
    """Цена «между категориями»: линейно по глубине повреждения между ближайшими категориями с данными.
    anchors — {уровень: (быстрая, цена выставления, число объявлений)}. None, если нет данных с обеих сторон."""
    lo = [l for l in anchors if l < level]
    hi = [l for l in anchors if l > level]
    if not lo or not hi:
        return None
    a, b = max(lo), min(hi)
    t = (level - a) / (b - a)
    quick = anchors[a][0] + (anchors[b][0] - anchors[a][0]) * t
    lst = anchors[a][1] + (anchors[b][1] - anchors[a][1]) * t
    return floor5(quick), rnd5(lst), (a, b)  # быструю продажу округляем вниз: оценка должна быть консервативной


def asis_estimate(facts, snap, clean, like):
    """Сколько можно выручить за ЭТОТ телефон «как есть» (с его дефектами). Источники по убыванию надёжности:
    same — аналоги с таким же дефектом (найдено на рынке); cat — аналоги той же категории состояния (дефекты могут отличаться);
    interp — расчёт между соседними категориями (допущение, не рыночная цена); clean — аналоги без названных дефектов.
    None — оценить не из чего. Возвращает {src, found, quick, list, n, st, cat, between}."""
    cat = ad_cat(facts) or "unk"
    row_ok = snap["rows"]["ok"]
    if cat == "ok" and row_ok["st"] and row_ok["n"] >= SNAP_NEED:  # исправность названа словами — сравниваем с такими же
        st = row_ok["st"]
        return {"src": "ok", "found": True, "quick": floor5(st["q1"]), "list": rnd5(st["med"]), "n": st["n"], "st": st, "cat": cat}
    if cat in ("ok", "unk"):
        st = clean["st"] if clean else None
        if st:
            return {"src": "clean", "found": True, "quick": floor5(st["q1"]), "list": rnd5(st["med"]), "n": st["n"], "st": st, "cat": cat}
        return None
    if like and like.get("st"):
        st = like["st"]
        return {"src": "same", "found": True, "quick": floor5(st["q1"]), "list": rnd5(st["med"]), "n": st["n"], "st": st, "cat": cat}
    row = snap["rows"][cat]
    if row["st"] and row["n"] >= SNAP_NEED:
        st = row["st"]
        return {"src": "cat", "found": True, "quick": floor5(st["q1"]), "list": rnd5(st["med"]), "n": st["n"], "st": st, "cat": cat}
    anchors = {}
    if clean and clean["st"]:
        anchors[0] = (clean["st"]["q1"], clean["st"]["med"], clean["st"]["n"])
    for c in ("minor", "visible", "faulty"):
        r = snap["rows"][c]
        if c != cat and r["st"] and r["n"] >= SNAP_NEED:
            anchors[CAT_LEVEL[c]] = (r["st"]["q1"], r["st"]["med"], r["n"])
    mid = _interp(anchors, CAT_LEVEL[cat])
    if mid:
        return {"src": "interp", "found": False, "quick": mid[0], "list": mid[1], "n": 0, "st": None, "cat": cat, "between": mid[2]}
    return None


DESIRED_MARGIN = 1.5  # «желаемая» цена покупки: прибыль в 1,5 раза выше целевой (запас на неприятные сюрпризы)


def target_profit(quick):
    """Целевая чистая прибыль на сделку: TARGET_PROFIT_BYN, а если не задана — большее из MIN_PROFIT_BYN и MIN_PROFIT_PCT % от быстрой продажи."""
    if TARGET_PROFIT_BYN > 0:
        return float(TARGET_PROFIT_BYN)
    return ceil5(max(MIN_PROFIT_BYN, MIN_PROFIT_PCT / 100 * quick))


def deal_calc(quick, lst, price, rep=None, rep_unknown=(), reserve_on=True):
    """Расчёт сделки — одна формула для обоих вариантов (без ремонта и с ремонтом); ремонт вычитается ОДИН раз.
      расходы = прочие расходы + ремонт (верхняя граница + запас на удорожание) + резерв на непроверенные функции
      макс. цена покупки = ожидаемая (быстрая) цена продажи − расходы − целевая прибыль
      желаемая цена      = то же, но прибыль в DESIRED_MARGIN раза выше целевой
      цена отказа        = безубыточность при продаже по цене выставления (оптимистично: нижняя граница ремонта)
    quick — консервативная продажа (нижняя четверть цен аналогов), lst — цена выставления (медиана).
    rep — (мин, макс) ИЗВЕСТНОГО ремонта или None; rep_unknown — дефекты, цена ремонта которых не известна: тогда расчёт
    «до учёта ремонта» (final=False), а лимит предварительный."""
    lo, hi = rep if rep else (0.0, 0.0)
    target = target_profit(quick)
    reserve = ceil5(RISK_RESERVE_PCT / 100 * quick) if reserve_on and RISK_RESERVE_PCT > 0 else 0
    over = hi * REPAIR_OVERRUN_PCT / 100
    costs = EXTRA_COSTS_BYN + hi + over + reserve  # консервативные расходы
    costs_opt = EXTRA_COSTS_BYN + lo + reserve     # оптимистичные расходы
    c = {"quick": quick, "list": lst, "target": target, "extra": EXTRA_COSTS_BYN, "rep_lo": lo, "rep_hi": hi, "overrun": over,
         "reserve": reserve, "costs": costs, "costs_opt": costs_opt, "rep_unknown": list(rep_unknown), "final": not rep_unknown,
         "raw": quick - costs - target, "desired": floor5(quick - costs - DESIRED_MARGIN * target),
         "limit": floor5(quick - costs - target), "walk": floor5(lst - costs_opt)}
    if price:
        c["profit"], c["profit_opt"] = quick - price - costs, lst - price - costs_opt
        c["roi"] = c["profit"] / (price + costs) if price + costs > 0 else None
        c["roi_opt"] = c["profit_opt"] / (price + costs_opt) if price + costs_opt > 0 else None
        c["gap"] = c["limit"] - price  # запас до максимальной цены (минус — цена выше)
    return c


def unconfirmed_checks(facts, title=""):
    """Что в объявлении не подтверждено и проверяется только при осмотре. Если список не пуст — в расчёте есть резерв на скрытые неисправности."""
    out = []
    phone = facts["label"].startswith("iPhone")
    if lock_status(facts, title) is None:
        out.append("блокировка (iCloud/активация)" if facts["label"].startswith(("iPhone", "iPod")) else "блокировка (Google-аккаунт, оператор)")
    if phone and bio_status(facts, title) is None:
        out.append("Face ID/Touch ID")
    if facts["battery_pct"] is None:
        out.append("износ аккумулятора")
    if not facts.get("good"):
        out.append("камеры, динамики, микрофон, разъём зарядки, кнопки, сеть")
    return out


def build_plan(ad, facts, snap, clean, like):
    """Два варианта сделки и три уровня цены покупки (желаемая / максимальная / отказ). Всё считается из найденных аналогов;
    цены ремонта — только из REPAIR_COSTS или слов продавца.
      A — купить и перепродать как есть (по цене телефонов в том же состоянии);
      B — купить, отремонтировать и продать как исправный (по цене исправных аналогов).
    Варианта «В» (отказаться) в расчёте нет: он наступает, когда цена выше максимума."""
    price = facts["price"]
    unconf = unconfirmed_checks(facts, ad.get("subject") or "")
    asis = asis_estimate(facts, snap, clean, like)
    rp = repair_plan(facts)
    crit = [n for c, n in facts["defects"].items() if SEVERITY.get(c, 0) >= 3]
    plan = {"unconfirmed": unconf, "asis": asis, "repair": rp, "crit": crit, "A": None, "B": None, "best": None, "breakeven": None,
            "sens": [], "upper": None}
    reserve_on = bool(unconf)
    if asis:
        plan["A"] = deal_calc(asis["quick"], asis["list"], price, None, (), reserve_on)
    if rp["needs"] and not crit and clean and clean["st"]:
        cq, cl = floor5(clean["st"]["q1"]), rnd5(clean["st"]["med"])
        known = (rp["lo"], rp["hi"]) if rp["items"] else None
        plan["B"] = deal_calc(cq, cl, price, known, rp["unknown"], True)
        plan["B"]["clean_n"] = clean["st"]["n"]
        if plan["A"]:
            free = deal_calc(cq, cl, price, (0.0, 0.0), (), True)  # макс. цена, если бы ремонт был бесплатным
            be = floor5((free["limit"] - plan["A"]["limit"]) / (1 + REPAIR_OVERRUN_PCT / 100))
            plan["breakeven"] = be  # при ремонте дороже этой суммы выгоднее продать как есть
            if rp["unknown"] and be > 0:
                for r in sorted({floor5(be / 2), be, floor5(be * 1.5)}):
                    plan["sens"].append((r, deal_calc(cq, cl, price, (float(r), float(r)), (), True)["limit"]))
    if not plan["A"] and not plan["B"] and not crit and clean and clean["st"]:
        # состояние телефона оценить не из чего, но продать дороже исправного он не сможет: считаем только верхнюю границу
        plan["upper"] = deal_calc(floor5(clean["st"]["q1"]), rnd5(clean["st"]["med"]), price, None, (), reserve_on)
    best = None
    if plan["A"]:
        best = "A"
    if plan["B"] and plan["B"]["final"]:
        a, b = plan["A"], plan["B"]
        # ремонт — это ещё время, риск и работа: вариант 2 выбирается, только если он даёт заметно больше (не меньше половины цели)
        gain = None if not a else (b["profit"] - a["profit"] if price else b["limit"] - a["limit"])
        if not a or gain >= max(a["target"] / 2, 10):
            best = "B"
    elif plan["B"] and not plan["A"]:
        best = "B"
    plan["best"] = best
    return plan


NO_DATA = "Пока недостаточно данных для решения"


SCEN_NAMES = {"A": "вариант 1 (перепродажа без ремонта)", "B": "вариант 2 (ремонт и перепродажа)"}


def _decide_core(facts, ap):
    """Итоговый вывод: (код, текст). Код: buy / bargain / skip / unknown; текст всегда начинается с одной из четырёх фраз:
    «Покупать по текущей цене», «Покупать только после торга…», «Не покупать для перепродажи», «Пока недостаточно данных для решения».
    Решает не просто «прибыль > 0»: нужна целевая прибыль при консервативной продаже, а при низкой уверенности оценки —
    ещё и запас (цена не выше «желаемой»)."""
    price, st = facts["price"], ap["status"]
    crit = [n for c, n in facts["defects"].items() if SEVERITY.get(c, 0) >= 3]
    if crit:
        return "skip", "Не покупать для перепродажи — " + ", ".join(crit) + ": цена и исход ремонта непредсказуемы."
    if st == "no_model":
        return "unknown", f"{NO_DATA} — модель не определена, сравнить не с чем."
    if st == "error":
        return "unknown", f"{NO_DATA} — внутренняя ошибка расчёта."
    if st == "no_market":
        return "unknown", f"{NO_DATA} — аналоги пока не загружены."
    if st == "se_gen":
        return "unknown", f"{NO_DATA} — у iPhone SE не указано поколение, а цены поколений сильно разные."
    plan = ap.get("plan") or {}
    best = plan.get("best")
    if st != "ok" or not (best or plan.get("upper")):
        if st != "ok":
            found, kept = ap.get("found", 0), ap.get("kept")
            if kept is not None and found >= REF_MIN:
                return "unknown", (f"{NO_DATA} — найдено {ads_nom(found)}, но цены сильно расходятся: после отсева аномальных "
                                   f"осталось {kept}, нужно хотя бы {REF_MIN}.")
            return "unknown", f"{NO_DATA} — найдено только {ads_nom(found)} этой модели, для ориентира нужно хотя бы {REF_MIN}."
        return "unknown", f"{NO_DATA} — {no_estimate_reason(facts, ap)}"
    if not best:  # состояние оценить не из чего: известна только верхняя граница (цена исправных)
        up = plan["upper"]
        if price and price > up["limit"]:
            return "skip", (f"Не покупать для перепродажи — даже если продать как исправный (≈ {money(up['quick'])} BYN), максимум покупки "
                            f"{money(up['limit'])} BYN, а просят {money(price)} BYN.")
        return "unknown", f"{NO_DATA} — {no_estimate_reason(facts, ap)} Выше {money(up['limit'])} BYN платить в любом случае нельзя."
    c, scen = plan[best], SCEN_NAMES[best]
    if not price:
        return "unknown", f"{NO_DATA} — в объявлении нет цены: спроси её у продавца (уровни цены покупки посчитаны ниже)."
    if ap.get("thin"):
        n = (ap.get("stats") or {}).get("n", 0)
        return "unknown", f"{NO_DATA} — аналогов мало ({n}, нужно ≥ {MIN_COMPS}): ориентиры предварительные, {scen}."
    limit, desired, walk = c["limit"], c["desired"], c["walk"]
    over = price - limit
    reach = BARGAIN_REACH_HINT if facts["bargain"] == "yes" else BARGAIN_REACH
    if limit <= 0:
        return "skip", (f"Не покупать для перепродажи — при ожидаемой продаже {money(c['quick'])} BYN расходы и целевая прибыль "
                        "не окупаются ни при какой цене.")
    if not c["final"]:  # ремонт нужен, а его цена не известна: считаем, сколько на него можно потратить
        names = ", ".join(c["rep_unknown"])
        if over > 0:
            if facts["bargain"] == "no":
                return "skip", f"Не покупать для перепродажи — {money(price)} BYN выше максимума {money(limit)} BYN (ещё до ремонта), а продавец пишет «без торга»."
            if over <= reach * price:
                return "bargain", (f"Покупать только после торга до {money(limit)} BYN минус ремонт ({names}) — {scen}: цена ремонта не известна, "
                                   f"максимум предварительный; сейчас {money(price)} BYN, уже без ремонта выше на {money(over)} BYN.")
            return "skip", (f"Не покупать для перепродажи — даже при бесплатном ремонте максимум покупки {money(limit)} BYN, "
                            f"а просят {money(price)} BYN (на {over / price * 100:.0f}% выше), торгом столько обычно не снять.")
        room = floor5((limit - price) / (1 + REPAIR_OVERRUN_PCT / 100))
        return "unknown", (f"{NO_DATA} — не известна цена ремонта ({names}). При цене {money(price)} BYN ремонт должен уложиться "
                           f"в ≈ {money(room)} BYN (с запасом на удорожание), иначе цена не подходит; задай цену в REPAIR_COSTS.")
    weak = ap.get("conf") == "низкая" or bool(ap.get("asis") and ap["asis"]["src"] == "interp")
    prof = f"прибыль ≈ {signed(c['profit'])} BYN при быстрой продаже" if price else ""
    if over <= 0:
        clean_st = (ap.get("clean") or {}).get("st")
        if max_severity(facts["defects"]) < 2 and clean_st and price < 0.5 * clean_st["med"]:  # слишком хорошо, чтобы быть правдой
            return "unknown", (f"{NO_DATA} — цена {money(price)} BYN вдвое ниже рынка (медиана {money(clean_st['med'])} BYN): сначала "
                               f"убедись, что нет блокировки iCloud и обмана; по расчёту максимум покупки {money(limit)} BYN.")
        if price <= desired or not weak:
            return "buy", (f"Покупать по текущей цене — {scen}: {money(price)} BYN не выше максимума {money(limit)} BYN "
                           f"(запас {money(-over)} BYN), {prof}.")
        return "bargain", (f"Покупать только после торга до {money(desired)} BYN — {scen}: цена {money(price)} BYN укладывается в максимум "
                           f"{money(limit)} BYN, но оценка ненадёжна, поэтому нужен запас прочности.")
    if facts["bargain"] == "no":
        return "skip", f"Не покупать для перепродажи — {money(price)} BYN выше максимума {money(limit)} BYN, а продавец пишет «без торга»."
    if price > walk:
        return "skip", (f"Не покупать для перепродажи — {money(price)} BYN выше цены отказа {money(walk)} BYN: даже при продаже "
                        "по цене выставления сделка не окупается.")
    if over <= reach * price:
        return "bargain", (f"Покупать только после торга до {money(limit)} BYN — {scen}: сейчас {money(price)} BYN, "
                           f"на {money(over)} BYN выше максимума." + (f" Оценка ненадёжна — лучше сбить до {money(desired)} BYN." if weak else ""))
    return "skip", (f"Не покупать для перепродажи — {money(price)} BYN выше максимума {money(limit)} BYN на {money(over)} BYN "
                    f"({over / price * 100:.0f}% цены), торгом столько обычно не снять.")


def decide(facts, ap):
    """Итоговый вывод (код, текст) + пояснение про второй вариант: если решение «торг/отказ», показываем максимум по обоим вариантам,
    а если ремонт не задан, но при низкой цене ремонта вариант 2 мог бы сработать — говорим, при какой цене ремонта."""
    code, text = _decide_core(facts, ap)
    try:
        plan, price = ap.get("plan") or {}, facts["price"]
        a, b = plan.get("A"), plan.get("B")
        if price and a and b and code in ("skip", "bargain"):
            if b["final"]:
                text += f" Максимум покупки: вариант 1 — {money(a['limit'])} BYN, вариант 2 — {money(b['limit'])} BYN."
            elif price <= b["limit"]:
                room = floor5((b["limit"] - price) / (1 + REPAIR_OVERRUN_PCT / 100))
                text += (f" Вариант 2 сработает, только если ремонт ({', '.join(b['rep_unknown'])}) обойдётся не дороже ≈ {money(room)} BYN — "
                         "цена ремонта не задана.")
    except Exception as e:  # пояснение вторично: основной вывод не теряем
        log("Ошибка пояснения к выводу:", e)
    return code, text


def no_estimate_reason(facts, ap):
    """Конкретно, чего не хватает, чтобы оценить телефон в его состоянии."""
    cat = ad_cat(facts) or "unk"
    snap = ap.get("snap") or {"rows": {}}
    names = ", ".join(defect_kind_names(facts)) if cat != "unk" else "состояние"
    row = snap["rows"].get(cat)
    n = row["n"] if row else 0
    return (f"нет аналогов в категории «{CAT_NAMES[cat]}» ({names}): найдено {n}, нужно ≥ {SNAP_NEED}, а соседних категорий "
            "для расчёта между ними тоже не хватает.")


def _source_conf(res, facts, plan, clean, pool, st, snap, sev):
    """Основа оценки основного варианта -> (статистика, пул, минимум аналогов, уверенность, причины низкой уверенности)."""
    asis, best = plan["asis"], plan["best"]
    tier, need = "none", MIN_COMPS
    if best == "B" or (asis and asis["src"] == "clean"):
        sst, spool, tier = clean["st"], clean["pool"]["items"], clean["pool"]["tier"]
    elif asis and asis["src"] == "same":
        sst, spool, tier, need = st, pool["items"], pool["tier"], pool["need"]
    elif asis and asis["src"] in ("cat", "ok"):
        row = snap["rows"][asis["cat"]]
        sst, spool, tier, need = row["st"], row["items"], "T4" if row["mixed"] else "T2", SNAP_NEED
    else:
        sst, spool = None, []
    why = []
    thin = bool(sst and sst["n"] < need)
    if not sst:
        conf = "низкая"
        why.append("расчёт между категориями — это допущение, а не цена из объявлений" if asis else "аналогов нет")
    else:
        conf = confidence_of(sst["n"], tier, sst, res.get("stale"), bool(facts["mem"]), sev)
        if thin:
            why.append(f"мало аналогов: {sst['n']}")
        if asis and asis["src"] == "cat":
            why.append("аналоги той же категории, но дефекты могут отличаться")
            conf = "средняя" if conf == "высокая" else conf
        unconfirmed = (best == "B" or (asis and asis["src"] == "clean")) and res.get("basis") == "general" and res.get("like_n") is not None
        if unconfirmed:  # у телефона есть дефект, а оценка идёт по общему рынку: состояние аналогов не подтверждено
            why.append("состояние и дефекты аналогов не подтверждены")
        if thin or unconfirmed:
            conf = "низкая"
        # Не называем оценку высокой, когда целевая категория состояния почти пуста,
        # а цена рассчитана по общим объявлениям без подтверждения исправности.
        asis = plan.get("asis")
        target_cat = ad_cat(facts) or "unk"
        target_row = (snap or {}).get("rows", {}).get(target_cat) or {}
        if asis and asis.get("src") == "clean" and target_row.get("n", 0) < SNAP_NEED:
            why.append(f"в категории «{CAT_NAMES.get(target_cat, target_cat)}» мало аналогов; использован общий рынок")
            if conf == "высокая":
                conf = "средняя"
    if ad_cat(facts) == "unk":
        why.append("исправность не подтверждена словами продавца")
        if conf == "высокая":
            conf = "средняя"
    if not facts["mem"]:
        why.append("память не указана")
    if facts.get("conflicts"):  # противоречия в характеристиках: уверенного вывода не даём
        why.append("противоречие: " + facts["conflicts"][0])
        conf = "низкая"
    if facts.get("price_unverified"):  # цена только из поиска, со страницей не сверена — уверенного вывода не даём
        why.append("цена не сверена со страницей объявления")
        conf = "низкая"
    if res.get("stale"):
        why.append("аналоги не обновлялись давно")
    if best == "B" and plan["B"] and not plan["B"]["final"]:
        why.append("цена ремонта не известна")
        conf = "низкая"
    return sst, spool, need, thin, conf, why


def _appraise(ad, facts, now=None):
    """Оценка по реальным аналогам. Не бросает исключений наружу: при сбое статус error."""
    res = {"status": "ok", "label": facts["label"], "price": facts["price"], "notes": [], "warnings": [], "verdict": None,
           "comps": [], "calc": None, "basis": None, "found": 0, "like_n": None, "like_need": None, "like_kind": None,
           "conf": None, "conf_why": [], "thin": False, "like_for_like": False, "plan": None, "snap": None, "clean": None, "asis": None}
    try:
        if not market_query(facts["label"]):
            res["status"] = "no_model"
            return res
        items, age, stale, why = market_items(facts["label"], now)
        if items is None:
            res["status"], res["no_market_reason"] = "no_market", why
            return res
        res["age_h"], res["stale"] = (age / 3600 if age is not None else None), stale
        res["db_comps"] = RUN.get("db_comps", 0)
        res["history"] = mdb_history(market_key(facts["label"]), facts["mem"], now)  # отдельно: в расчёт не входит
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
        reg = region_code(HOME_REGION) if HOME_REGION else None  # None: регион самого объявления
        basis, pool, st, info = pick_basis(items, facts, ad_id, reg)
        res.update(info, basis=basis, found=len(pool["items"]), tier=pool["tier"], desc=pool["desc"], place=pool["place"],
                   kind=pool["kind"], notes=list(pool["notes"]), need=pool["need"], priv=pool["priv"])
        res["comps"] = sorted(pool["items"], key=lambda it: it[1])[:3]
        # эталон «исправный телефон»: аналоги без названных дефектов; нужен и для варианта «с ремонтом», и для расчёта между категориями
        cpool = pool if basis == "general" else select_pool(items, facts, ad_id, region=reg, force_clean=True)
        cst = st if basis == "general" else (price_stats([it[1] for it in cpool["items"]]) if len(cpool["items"]) >= REF_MIN else None)
        clean = {"pool": cpool, "st": cst if cst and cst["n"] >= REF_MIN else None}
        snap = market_snapshot(items, facts, ad_id)
        like = {"pool": pool, "st": st} if basis == "defect" else None
        plan = build_plan(ad, facts, snap, clean, like)
        res.update(plan=plan, snap=snap, clean=clean, asis=plan["asis"])
        if not plan["A"] and not plan["B"] and not clean["st"]:
            res["status"] = "few"  # ориентир считать не из чего: ни по такому состоянию, ни по исправным
            if st:
                res["kept"] = st["n"]
            return res
        sst, spool, need, thin, conf, why_low = _source_conf(res, facts, plan, clean, pool, st, snap, sev)
        res["stats"] = sst or clean["st"]
        res["thin"], res["conf"], res["conf_why"] = thin, conf, why_low
        if thin:
            res["notes"].append("аналогов мало — оценка приблизительная")
        if basis == "general" and info["like_n"] is None and facts["battery_pct"] is not None:
            res["notes"].append("состояние аккумулятора у аналогов неизвестно, на цену не влияет")
        ref = plan["asis"] if plan["asis"] and plan["asis"]["found"] else None
        res["like_for_like"] = bool(ref)  # сравниваем с такими же по состоянию, а не с телефонами без пометок о дефектах
        if not price:
            res["warnings"].append("цена не указана — вердикт невозможен")
        elif ref:
            verdict, disc = rank_verdict(price, ref["st"])
            res["pct"] = -disc * 100  # минус — дешевле медианы
            if (thin or conf == "низкая") and verdict == "ОЧЕНЬ ВЫГОДНО":
                verdict = "ВЫГОДНО"  # на малой выборке «очень выгодно» не объявляем
            if sev >= 3 and verdict in ("ОЧЕНЬ ВЫГОДНО", "ВЫГОДНО"):
                verdict = None
                res["warnings"].append("низкая цена объясняется критичным дефектом — риск высокий")
            elif sev < 2 and clean["st"] and price < 0.5 * clean["st"]["med"]:
                res["warnings"].append("цена вдвое ниже рынка: проверь блокировку/обман")
                if verdict == "ОЧЕНЬ ВЫГОДНО":
                    verdict = "ВЫГОДНО"
            res["verdict"] = verdict
        elif clean["st"]:
            res["pct"] = (price - clean["st"]["med"]) / clean["st"]["med"] * 100
        if spool and sst:
            res["comps"] = pick_comps(spool, sst, price)
        res["calc"] = plan[plan["best"]] if plan["best"] else None
    except Exception as e:
        log("Ошибка оценки цены:", e)
        res["status"] = "error"
    return res


def appraise(ad, facts, now=None):
    """Полная оценка объявления + итоговый вывод (res['decision'] = (код, текст))."""
    res = _appraise(ad, facts, now)
    try:
        res["decision"] = decide(facts, res)
    except Exception as e:
        log("Ошибка итогового вывода:", e)
        res["decision"] = ("unknown", f"{NO_DATA} — внутренняя ошибка расчёта.")
    return res


# ---------- Сообщение в Telegram ----------

VERDICT_ICON = {"ОЧЕНЬ ВЫГОДНО": "🟢", "ВЫГОДНО": "🟢", "СРЕДНИЙ ВАРИАНТ": "🟡", "ДОРОГО": "🔴", "НЕВЫГОДНО": "🔴"}
DECISION_ICON = {"buy": "🟢", "bargain": "🟡", "skip": "🔴", "unknown": "⚪"}
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


def _ads_form(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def ads_nom(n):
    """«31 объявление», «34 объявления», «35 объявлений»."""
    return f"{n} {_ads_form(n, 'объявление', 'объявления', 'объявлений')}"


def ads_gen(n):
    """Для «медиана цен …»: «31 объявления», «34 объявлений»."""
    return f"{n} {_ads_form(n, 'объявления', 'объявлений', 'объявлений')}"


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
    kinds = [KIND_NAMES[c] for c, bit in F_KINDS.items() if it[3] & bit]
    for flag, name in ((F_PARTS, "на запчасти"), (F_DEF, "с дефектами"), (F_NEW, "новый"), (F_REFURB, "восстановл."), (F_SHOP, "магазин")):
        if it[3] & flag and not (flag == F_DEF and it[3] & F_PARTS):
            bits.append("дефект в заголовке: " + ", ".join(kinds) if flag == F_DEF and kinds else name)
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
    pct = ap.get("pct") if ap.get("like_for_like") else None  # «ниже медианы» — плюс только в сравнении с такими же, а не с исправными
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


def pool_text(ap):
    """Что за аналоги: «iPhone XS, 64 ГБ, вся Беларусь; без пометок о дефектах в заголовке; только частники»."""
    kind = {CLEAN_KIND: "без пометок о дефектах в заголовке", SAME_KIND: "с таким же дефектом в заголовке",
            "на запчасти": "«на запчасти»"}.get(ap.get("kind"), ap.get("kind") or "")
    head = f"{ap['label']}, {ap['place']}" if ap.get("place") else ap["label"]
    return "; ".join(b for b in (head, kind, "только частники" if ap.get("priv") else "") if b)


def defect_kind_names(facts):
    return [KIND_NAMES[c] for c in F_KINDS if c in facts["defects"]] or ["дефект"]


def like_line(facts, ap):
    """Сколько аналогов с ПОДТВЕРЖДЁННЫМ таким же дефектом (по тексту объявлений-аналогов) — отдельно от всех найденных."""
    n, need = ap.get("like_n"), ap.get("like_need")
    if n is None:
        return None
    if ap.get("like_kind") == "на запчасти":
        txt = f"Среди аналогов «на запчасти»: {n}"
    else:
        txt = f"С таким же дефектом ({', '.join(defect_kind_names(facts))}) в заголовках аналогов: {n}"
    if ap.get("basis") == "defect":
        return txt + "; оценка по ним."
    return txt + f" — для отдельной оценки нужно ≥ {need}."


def missing_text(facts, ap):
    """Конкретно, чего не хватает для точной оценки (вместо общей фразы «недостаточно данных»)."""
    if ap.get("status") != "ok":
        return ""
    plan = ap.get("plan") or {}
    asis = plan.get("asis")
    uses_clean = bool(plan.get("B")) or bool(asis and asis["src"] == "clean")  # продажа считается по общему рынку (без названных дефектов)
    if ap.get("basis") == "general" and ap.get("like_n") is not None and uses_clean:
        others = [n for n in defect_kind_names(facts) if n != KIND_NAMES["battery"]]
        if "battery" in facts["defects"]:
            what = "состояние аккумулятора и наличие дефектов" + (f" ({', '.join(others)})" if others else "")
        else:
            what = f"наличие дефектов ({', '.join(others)})"
        base = f"Найдено {ads_nom(ap['found'])} похожих устройств, но {what} у них не подтверждены. "
        if asis and asis["src"] != "clean":  # вариант 1 оценён по другим аналогам, а на общем рынке стоит только цена после ремонта
            return base + "Поэтому цена продажи после ремонта (вариант 2) основана на общем рынке и может быть неточной."
        return base + "Поэтому оценка основана на общем рынке и может быть неточной."
    if ap.get("thin"):
        return f"Найдено только {ads_nom(ap['found'])}: для надёжной оценки нужно ≥ {MIN_COMPS}."
    return ""


def market_lines(facts, ap):
    """📊 для статусов, когда таблицу категорий построить нельзя (нет модели, нет аналогов, мало аналогов, поколение SE)."""
    st = ap["status"]
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
        k, kept = ap.get("found", 0), ap.get("kept")
        where = html.escape(pool_text(ap))
        if kept is not None and k >= REF_MIN:
            what = (f"найдено {ads_nom(k)} ({where}), но цены так сильно расходятся, что после отсева аномальных осталось {kept}; "
                    f"для ориентира нужно хотя бы {REF_MIN}")
        else:
            what = (f"найдено только {ads_nom(k)} ({where}); для ориентира нужно хотя бы {REF_MIN}, для надёжной оценки — {MIN_COMPS}"
                    if k else f"подходящих объявлений этой модели в выдаче нет ({where})")
        out = [f"📊 Ориентир цены посчитать не из чего: {what}."]
        ll = like_line(facts, ap)
        if ll:
            out.append("   " + html.escape(ll))
        if ap.get("comps"):
            out.append("   Найденные цены (очень низкая уверенность: слишком мало объявлений, это не оценка рынка): "
                       + ", ".join(money(it[1]) for it in ap["comps"]) + " BYN")
        return out
    return []


def signed(x):
    return f"{x:+,.0f}".replace(",", " ").replace("-", "−")


def rng(a, b):
    """«40–60» или «40», если границы совпадают."""
    return money(a) if round(a) == round(b) else f"{money(a)}–{money(b)}"


PHOTO_WHY = {
    "off": "отключён (PHOTOS_MAX=0)",
    "no_llm": "не подключена нейросеть (нет GEMINI_API_KEY / ANTHROPIC_API_KEY)",
    "no_photos": "в объявлении нет фото",
    "no_download": "фото не удалось загрузить с Куфара",
    "error": "нейросеть не приняла запрос с фото",
    "llm_off": "нейросеть недоступна (лимит запросов или сбой сервиса)",
    "none": "анализ не запускался",
    "no_time": "не хватило времени до конца окна свежести",
}


def kit_effect(ap):
    """Влияние коробки на цену ПО АНАЛОГАМ: (разница медиан или None, аналогов с коробкой в заголовке, без неё).
    Берётся только если в обеих группах не меньше SNAP_NEED объявлений; никаких «надбавок за предмет»."""
    pool = ((ap.get("clean") or {}).get("pool") or {}).get("items") or []
    with_box = [it[1] for it in pool if it[3] & F_BOX]
    without = [it[1] for it in pool if not it[3] & F_BOX]
    if len(with_box) >= SNAP_NEED and len(without) >= SNAP_NEED:
        return statistics.median(with_box) - statistics.median(without), len(with_box), len(without)
    return None, len(with_box), len(without)


def kind_effect(ap, kind):
    """На сколько аналоги с таким дефектом (по тексту) дешевле исправных: (разница медиан или None, число аналогов).
    Для царапин и сколов («cosmetic») берётся категория «небольшие дефекты»."""
    snap, clean = ap.get("snap"), ap.get("clean")
    if not snap or not clean or not clean["st"] or (kind not in F_KINDS and kind != "cosmetic"):
        return None, 0
    row = snap["rows"]["minor"] if kind == "cosmetic" else kind_row(snap, kind)
    if row["st"] and row["n"] >= SNAP_NEED:
        return row["st"]["med"] - clean["st"]["med"], row["n"]
    return None, row["n"]


def photo_lines(facts, ap, compact=False):
    """Что видно на фото. Только видимое: исправность функций по фото не определяется."""
    e, ph = html.escape, facts.get("photo") or {}
    st = ph.get("status", "none")
    if st != "analyzed":
        return [f"   • По фото: не анализировались — {PHOTO_WHY.get(st, PHOTO_WHY['none'])}."]
    n, total = ph.get("n", 0), ph.get("total", 0)
    finds = ph.get("findings") or []
    poor = (ph.get("quality") or "").lower() == "плохое"
    if not finds:
        return [f"   • По фото ({n} из {total}): видимых дефектов не найдено" +
                (" — но качество фото плохое, вывод ненадёжен" if poor else "; это не проверка работы телефона") + "."]
    out = [f"   • По фото ({n} из {total}) видно" + (" (качество фото плохое, выводы ненадёжны)" if poor else "") + ":"]
    for f in finds[: 2 if compact else 4]:
        eff = ""
        if f.get("kind") in F_KINDS or f.get("kind") == "cosmetic":
            d, k = kind_effect(ap, f["kind"])
            eff = (f" Аналоги с таким дефектом дешевле исправных на ≈ {money(-d)} BYN (по {k})." if d is not None and d < 0
                   else f" Влияние на цену по аналогам не оценить (нужно ≥ {SNAP_NEED}, найдено {k}).")
        chk = f" Проверить: {e(f['check'])}." if f.get("check") and not compact else ""
        out.append(f"      – {e(f['what'])} (уверенность: {e(f['conf'])}).{eff}{chk}")
    if ph.get("mismatch"):
        out.append(f"      ⚠ Расхождение с описанием: {e(ph['mismatch'])}")
    if any(f.get("kind") in ("screen", "cosmetic", "camera") and f.get("conf") in ("высокая", "средняя") for f in finds):
        out.append("      ℹ Визуальные наблюдения не меняют расчёт цены автоматически — подтверди дефект у продавца.")
    return out


def kit_lines(facts, ap, compact=False):
    e, ph = html.escape, facts.get("photo") or {}
    seen = [x for x in facts["kit"] if x != "только телефон"]
    seen_ph = [x for x in (ph.get("kit") or []) if x not in seen]
    if not seen and not seen_ph:
        return ["   • Комплект: " + ("продавец пишет «только телефон»." if "только телефон" in facts["kit"] else "в объявлении не указан.")]
    parts = []
    if seen:
        parts.append("по тексту — " + e(", ".join(seen)))
    if seen_ph:
        parts.append("на фото видно — " + e(", ".join(seen_ph)))
    out = ["   • Комплект: " + "; ".join(parts) + ". Оригинальность аксессуаров не подтверждена."]
    if not compact and facts.get("box"):
        d, nb, nw = kit_effect(ap)
        out.append(f"      Коробка ≈ {signed(d)} BYN к медиане аналогов ({nb} с коробкой в заголовке и {nw} без; в расчёт не включено)."
                   if d is not None else
                   f"      Влияние коробки на цену не оценить: аналогов с коробкой {nb}, без неё {nw} (нужно ≥ {SNAP_NEED} в каждой группе).")
    return out


def state_lines(ad, facts, ap, compact=False):
    """🔍 Состояние: категория, дефекты по тексту, аккумулятор, фото, комплект, что не проверено."""
    e = html.escape
    cat = ad_cat(facts) or "unk"
    out = ["🔍 <b>Состояние</b>"]
    defects = [n for _c, n in sorted(facts["defects"].items(), key=lambda kv: -SEVERITY.get(kv[0], 0))]
    if defects:
        out.append(f"   • Категория: {CAT_NAMES[cat]}. Дефекты (описание и фото): {e('; '.join(defects))}.")
    elif cat == "ok":
        out.append("   • Категория: исправные — продавец пишет, что всё в порядке; это слова продавца, не проверка.")
    else:
        out.append("   • Дефекты в описании не названы — но это не значит, что телефон исправен: состояние не подтверждено.")
    title = ad.get("subject") or ""
    lock, bio = lock_status(facts, title), bio_status(facts, title)
    known = ([f"блокировка — {lock}"] if lock else []) + ([f"Face/Touch ID — {bio}"] if bio else [])
    if known:
        out.append("   • Со слов продавца: " + e("; ".join(known)) + " (это слова, а не проверка).")
    if facts["price"] and facts["bargain"] == "no":
        out.append("   • Торг: продавец пишет «без торга» — рассчитывай на указанную цену.")
    elif facts["price"] and facts["bargain"] == "yes":
        out.append("   • Торг: в тексте есть про торг — цена, скорее всего, стартовая; сколько уступит, неизвестно.")
    if not facts["desc"]:
        out.append("   • Описание в выдаче Куфара не получено — оценка по названию и параметрам, открой объявление.")
    bat = facts["battery_pct"]
    if bat is not None:
        out.append(f"   • Аккумулятор: {bat}%" + (" — ниже 80%, износ заметный, нужно оценить замену." if bat < 80 else "."))
    out += photo_lines(facts, ap, compact)
    out += kit_lines(facts, ap, compact)
    unconf = (ap.get("plan") or {}).get("unconfirmed")
    if unconf is None:
        unconf = unconfirmed_checks(facts, ad.get("subject") or "")
    if unconf:
        out.append("   • Не проверено: " + e("; ".join(unconf)) + ".")
    return out


def cat_row_text(r):
    """Строка категории: «5 шт. · медиана 275 (240–300)» или честное «мало»."""
    st = r["st"]
    if not r["all"]:
        return "объявлений нет"
    if not st or r["n"] < SNAP_NEED:
        prices = ", ".join(money(p) for p in (st["prices"] if st else [])[:3])
        return f"{r['n']} шт. ({prices} BYN) — мало для медианы"
    bits = f"{r['n']} шт. · медиана {money(st['med'])} ({money(st['min'])}–{money(st['max'])})"
    if r["mixed"]:
        bits += " · память разная"
    if r["shops"]:
        bits += " · вкл. магазины"
    return bits


def market_block(facts, ap, compact=False):
    """📊 Рынок по состоянию: цены активных объявлений той же модели по категориям — от исправных до неисправных."""
    e, snap, me = html.escape, ap["snap"], ad_cat(facts) or "unk"
    head = f"📊 <b>Рынок</b> — {e(ap['label'])}" + (f", {facts['mem']} ГБ" if facts["mem"] else "") + \
           f": найдено {n_ads(snap['total'])}. Это цены объявлений, не сделок."
    out = [head]
    for c in CATS:
        out.append(f"   • {CAT_NAMES[c]}: {cat_row_text(snap['rows'][c])}" + (" ◀ этот телефон" if c == me else ""))
    ll, mt = like_line(facts, ap), missing_text(facts, ap)
    if ll:
        out.append("   " + e(ll))
    if mt:
        out.append("   ⚠ " + e(mt))
    if ap.get("price") and ap.get("pct") is not None:
        ref = "аналогов в том же состоянии" if ap.get("like_for_like") else "общего рынка (без названных дефектов; не сравнение с такими же)"
        out.append(f"   Цена продавца {pct_text(ap['pct'])} {ref}." +
                   (f" По рынку: <b>{ap['verdict']}</b> (для перепродажи решают расчёты ниже)." if ap.get("verdict") else ""))
    if not compact:
        for n in ap["notes"] + ap["warnings"]:
            out.append(f"   ⚠ {e(n)}")
        if snap.get("undefined"):
            out.append(f"   ({snap['undefined']} объявлений из старого кеша без вида дефекта в расчёт категорий не вошли)")
        if ap.get("stale") and ap.get("age_h") is not None:
            out.append(f"   ⚠ аналоги обновлялись {ap['age_h']:.0f} ч назад (свежие загрузить не удалось)")
        h = ap.get("history")
        if h:
            out.append(f"   История (уже неактивные предложения, в расчёт не входят): {h['n']} шт., медиана {money(h['med'])} BYN"
                       + (f", у {h['changed']} цена менялась" if h["changed"] else "") + ".")
    return out


def asis_src_text(ap):
    """Откуда цена «как есть»: найдено на рынке или расчёт (допущение)."""
    a = ap["plan"]["asis"]
    if a["src"] == "clean":
        return f"найдено: {ads_nom(a['n'])} без названных дефектов, состояние не подтверждено"
    if a["src"] == "ok":
        return f"найдено: {ads_nom(a['n'])}, где исправность подтверждена словами продавца («идеал», «всё работает»)"
    if a["src"] == "same":
        what = "«на запчасти»" if ap.get("like_kind") == "на запчасти" else "с таким же дефектом в тексте"
        return f"найдено: {ads_nom(a['n'])} {what}"
    if a["src"] == "cat":
        return f"найдено: {ads_nom(a['n'])} категории «{CAT_NAMES[a['cat']]}», дефекты могут отличаться"
    lo, hi = a["between"]
    names = {0: "без названных дефектов"}
    names.update({CAT_LEVEL[c]: CAT_NAMES[c] for c in ("minor", "visible", "faulty")})
    return f"расчёт (допущение): между категориями «{names[lo]}» и «{names[hi]}» — аналогов в категории «{CAT_NAMES[a['cat']]}» не хватает"


def levels_line(c):
    return f"   • Цена покупки: желательно ≤ <b>{money(c['desired'])}</b> · максимум <b>{money(c['limit'])}</b> · отказ выше {money(c['walk'])} BYN"


def calc_line(c, label, repair_txt=None, prelim=False):
    """Формула максимальной цены покупки с числами: продажа − расходы − целевая прибыль (ремонт вычитается один раз)."""
    parts = [f"{money(c['quick'])} ({label})"]
    if repair_txt:
        parts.append(f"− {repair_txt}")
    if c["extra"]:
        parts.append(f"− {money(c['extra'])} (прочие расходы)")
    if c["reserve"]:
        parts.append(f"− {money(c['reserve'])} (резерв {RISK_RESERVE_PCT:g}% на непроверенные функции)")
    parts.append(f"− {money(c['target'])} (целевая прибыль)")
    tail = f"= {money(c['raw'])}" + (" (до вычета ремонта)" if prelim else (f" → {money(c['limit'])}" if abs(c["raw"] - c["limit"]) >= 1 else ""))
    return "   • Расчёт: " + " ".join(parts) + " " + tail


def profit_line(c, price, prefix="Прибыль"):
    if not price or "profit" not in c:
        return None
    roi = f", ROI ≈ {c['roi'] * 100:+.0f}% от вложенных {money(price + c['costs'])} BYN".replace("-", "−") if c.get("roi") is not None else ""
    return (f"   • {prefix} при цене {money(price)} BYN: от {signed(c['profit'])} (быстрая продажа) до {signed(c['profit_opt'])} "
            f"(по цене выставления) BYN{roi}. Не гарантия.")


def variant1_lines(facts, ap, compact=False):
    plan, price, e = ap["plan"], facts["price"], html.escape
    out = ["💵 <b>Вариант 1 — перепродажа без ремонта</b>"]
    A = plan["A"]
    if not A:
        out.append(f"   • Оценить продажу «как есть» не из чего: {e(no_estimate_reason(facts, ap))}")
        up = plan.get("upper")
        if up:
            out.append(f"   • Верхняя граница (если бы телефон был исправным): быстро ≈ {money(up['quick'])} BYN → максимум покупки "
                       f"{money(up['limit'])} BYN; для телефона с дефектом реальный максимум ниже.")
        return out
    out.append(f"   • Продажа в текущем состоянии: выставлять ≈ {money(A['list'])} BYN (медиана), быстро ≈ {money(A['quick'])} BYN "
               f"(нижняя четверть) — {e(asis_src_text(ap))}.")
    out.append(calc_line(A, "быстрая продажа"))
    out.append(levels_line(A))
    pl = profit_line(A, price)
    if pl:
        out.append(pl)
    return out


def repair_text(rp):
    """«замена акб 40–60 BYN (REPAIR_COSTS)» — только то, что задано пользователем или названо продавцом."""
    return "; ".join(f"{i['name']} {rng(i['lo'], i['hi'])} BYN ({i['src']})" for i in rp["items"])


def variant2_lines(facts, ap, compact=False):
    plan, price, e = ap["plan"], facts["price"], html.escape
    out = ["🔧 <b>Вариант 2 — ремонт и перепродажа</b>"]
    rp, B = plan["repair"], plan["B"]
    if plan["crit"]:
        out.append("   • Не рассматриваю: " + e(", ".join(plan["crit"])) + " — скрытые повреждения и цена ремонта непредсказуемы.")
        return out
    if not rp["needs"]:
        out.append("   • Ремонт не нужен: заметных неисправностей в описании нет.")
        return out
    if not B:
        out.append("   • Не посчитан: нет исправных аналогов для цены продажи после ремонта (нужно ≥ " + str(REF_MIN) + ").")
        return out
    rep_parts = []
    if rp["items"]:
        rep_parts.append(e(repair_text(rp)))
    if rp["unknown"]:
        rep_parts.append(e(", ".join(rp["unknown"])) + " — цена ремонта не задана (REPAIR_COSTS), бот её не придумывает")
    out.append("   • Ремонт: " + "; ".join(rep_parts) + (f". Запас на удорожание {REPAIR_OVERRUN_PCT:g}% учтён" if rp["items"] else ""))
    out.append(f"   • Продажа после ремонта: выставлять ≈ {money(B['list'])} BYN, быстро ≈ {money(B['quick'])} BYN "
               f"(найдено: {ads_nom(B['clean_n'])} без названных дефектов; состояние аналогов не подтверждено)")
    if B["final"]:
        out.append(calc_line(B, "быстрая продажа", f"{money(B['rep_hi'] + B['overrun'])} (ремонт {money(B['rep_hi'])} + запас {REPAIR_OVERRUN_PCT:g}%)"))
    else:
        txt = f"ремонт ({e(', '.join(rp['unknown']))}; цена не известна)"
        if rp["items"]:
            txt = f"{money(B['rep_hi'] + B['overrun'])} (известная часть ремонта) − ещё " + txt
        out.append(calc_line(B, "быстрая продажа", txt, prelim=True))
    out.append(levels_line(B) + ("" if B["final"] else " (до вычета ремонта)"))
    pl = profit_line(B, price, "Прибыль после всех учтённых расходов") if B["final"] else None
    if pl:
        out.append(pl)
    elif price and not B["final"]:
        out.append(f"   • Прибыль до вычета ремонта при цене {money(price)} BYN: от {signed(B['profit'])} до {signed(B['profit_opt'])} BYN — "
                   "из этого нужно вычесть ремонт.")
    be = plan.get("breakeven")
    if be and not compact:
        out.append(f"   • Ремонт выгоднее варианта 1, только если запчасти + работа не дороже ≈ {money(be)} BYN.")
        if plan["sens"]:
            out.append("   • Что если (не цены ремонта, а чувствительность): " + "; ".join(
                f"ремонт {money(r)} → максимум {money(m)}" for r, m in plan["sens"]) + " BYN.")
    return out


def risk_lines(facts, ap, compact=False):
    """⚠️ Риски: непроверенные функции и скрытые дефекты, уверенность оценки, ликвидность, риски от нейросети."""
    e, plan = html.escape, ap.get("plan") or {}
    out = ["⚠️ <b>Риски</b>"]
    unconf = plan.get("unconfirmed") or []
    best = plan.get(plan.get("best")) if plan.get("best") else None
    if unconf:
        res = f" В расчёт заложен резерв {money(best['reserve'])} BYN ({RISK_RESERVE_PCT:g}%)." if best and best.get("reserve") else ""
        out.append("   • Возможны скрытые дефекты: " + e("; ".join(unconf)) + "." + res)
    else:
        out.append("   • Все ключевые функции подтверждены словами продавца — это не проверка, посмотри при осмотре.")
    if ap.get("conf"):
        why = ap.get("conf_why") or []
        out.append(f"   • Уверенность оценки: {ap['conf']}" + (f" — {e('; '.join(why))}" if why and ap["conf"] == "низкая" else "") + ".")
    snap = ap.get("snap")
    if snap and not compact and ap.get("status") == "ok":
        thin = " Рынок тонкий — быстро продать может не получиться." if snap["total"] < 8 else ""
        out.append(f"   • Ликвидность: на Куфаре сейчас {n_ads(snap['total'])} этой модели; за сколько они продаются, Куфар не показывает.{thin}")
    if plan.get("best") == "B" and plan.get("B") and not plan["B"]["final"]:
        out.append("   • Цена ремонта не известна — вариант 2 предварительный.")
    for r in facts["risks"][: 1 if compact else 3]:
        out.append(f"   • {e(r)}")
    return out


def verdict_lines(facts, ap):
    """Один однозначный вывод в конце оценки (+ «только после проверки», если важные функции не подтверждены)."""
    code, text = ap.get("decision") or decide(facts, ap)
    head, sep, tail = text.partition(" — ")
    out = f"✅ <b>Итоговая рекомендация:</b> {DECISION_ICON.get(code, '⚪')} <b>{html.escape(head)}</b>" + (f" — {html.escape(tail)}" if sep else "")
    if code in ("buy", "bargain") and ap.get("conf") == "низкая":
        out += " Уверенность оценки низкая — проверь состояние при встрече."
    lines = [out]
    crit = [x for x in ((ap.get("plan") or {}).get("unconfirmed") or []) if x.startswith(("блокировка", "Face"))]
    if code in ("buy", "bargain") and crit:
        lines.append("   🔎 Покупать только после проверки при осмотре: " + html.escape("; ".join(crit)) + ".")
    return lines


def header_lines(ad, facts):
    e = html.escape
    title = ad.get("subject") or facts["label"]
    price, usd = facts["price"], price_usd(ad)
    ptxt = (f"{money(price)} BYN" + (f" (~${money(usd)})" if usd else "")) if price else \
        ("цена договорная" if facts["negotiable_price"] else "цена не указана")
    place = ", ".join(x for x in (facts["region"], facts["area"]) if x) or "регион не указан"
    spec = [facts["label"] if facts["label"] != "Другое" else "модель не определена"]
    spec.append(f"{facts['mem']} ГБ" if facts["mem"] else "память не указана")
    spec.append(COND_RU[facts["cond"]])
    if facts["battery_pct"]:
        spec.append(f"акб {facts['battery_pct']}%")
    return [f"📱 <b>{e(title)}</b>", f"💰 Цена продавца: {e(ptxt)}",
            f"📍 {e(place)} · {'🏪 магазин' if facts['seller'] == 'магазин' else '👤 частник'}", "🔧 " + e(" · ".join(spec))]


def comp_title_text(ap):
    """Заголовок блока примеров: откуда взяты показанные аналоги — это зависит от того, по чему считался основной вариант."""
    plan = ap.get("plan") or {}
    asis = plan.get("asis")
    src = asis["src"] if asis else None
    if plan and (plan.get("best") == "B" or src == "clean"):
        return "Примеры аналогов без названных дефектов (активные объявления, не сделки):"
    if src == "ok":
        return "Примеры аналогов, где исправность подтверждена словами продавца (активные объявления, не сделки):"
    if src == "same":
        what = "«на запчасти»" if ap.get("like_kind") == "на запчасти" else "с таким же дефектом"
        return f"Примеры аналогов {what} (активные объявления, не сделки):"
    if src == "cat":
        return f"Примеры аналогов категории «{CAT_NAMES[asis['cat']]}» (активные объявления, не сделки):"
    if ap.get("basis") == "general" and ap.get("like_n") is not None:
        return "Примеры аналогов без названных дефектов (активные объявления, не сделки):"
    return "Сопоставимые активные объявления (не сделки):"


def build_full_message(ad, facts, ap):
    """Подробный разбор (MESSAGE_STYLE=full, до ~3990 символов): 📱 💰 / 🔍 Состояние / 📊 Рынок / 💵 Вариант 1 / 🔧 Вариант 2 / ⚠️ Риски / ✅ Итог.
    Только известные факты; неизвестное названо «не указано» / «не подтверждено». Если не помещается — сначала сокращаются
    второстепенные строки, затем убираются примеры аналогов, и только потом режется середина (итог и ссылка остаются всегда)."""
    e = html.escape
    ok = ap.get("status") == "ok" and ap.get("plan")
    verdict = verdict_lines(facts, ap)
    comps = ap.get("comps") or []
    tail = ["🔗 " + e(ad.get("ad_link", item_url(ad["ad_id"])))]
    comp_title = comp_title_text(ap)
    comp_block = (["", comp_title] + [comp_line(c) for c in comps]) if comps else []

    def body(compact):
        lines = header_lines(ad, facts)
        lines.append("📝 " + e(template_summary(facts, ap)))
        lines.append("")
        lines += state_lines(ad, facts, ap, compact) + [""]
        if ok:
            lines += market_block(facts, ap, compact) + [""]
            lines += variant1_lines(facts, ap, compact) + [""]
            lines += variant2_lines(facts, ap, compact) + [""]
        else:
            lines += market_lines(facts, ap) + [""]
        lines += risk_lines(facts, ap, compact) + [""]
        return lines + verdict

    text = None
    for compact, with_comps in ((False, True), (False, False), (True, False)):
        lines = body(compact)
        text = "\n".join(lines + (comp_block if with_comps else []) + [""] + tail)
        if len(text) <= 3900:
            return text
    if len(text) > 3990:  # всё ещё длинно: режем середину по границе строки, итоговый вывод и ссылка остаются
        rest = "\n".join(verdict + [""] + tail)
        head = "\n".join(lines[:-len(verdict)])[:max(0, 3990 - len(rest) - 3)].rsplit("\n", 1)[0]
        text = head + "\n…\n" + rest
    return text[:3990]


# ---------- Короткое сообщение (по умолчанию) ----------
# За несколько секунд понять, открывать ли объявление: модель и цена, рынок, уровни покупки, прибыль, один вердикт
# (ВЫГОДНО / НЕВЫГОДНО / НЕДОСТАТОЧНО ДАННЫХ) с уверенностью и числом аналогов. Описание продавца не пересказывается;
# неизвестное не прячется: неизвестный ремонт, противоречия и подозрительно низкая цена — одной строкой.

def _crit(facts):
    return [n for c, n in facts["defects"].items() if SEVERITY.get(c, 0) >= 3]


def _shown_variant(ap):
    """Какой вариант сделки показывать: лучший из посчитанных; если у ремонта неизвестна цена, а «как есть» посчитан — его."""
    plan = ap.get("plan") or {}
    best = plan.get("best")
    if best == "B" and plan.get("B") and not plan["B"]["final"] and plan.get("A"):
        best = "A"
    return best, (plan.get(best) if best else None)


def short_reason(facts, ap):
    """Почему решения нет — конкретно и коротко."""
    st, plan = ap.get("status"), ap.get("plan") or {}
    if facts.get("model_conflict"):
        return "модель не подтверждена: " + (facts.get("conflicts") or ["противоречие в названии"])[0]
    if st == "no_model":
        return "модель не определена"
    if st == "se_gen":
        return "у iPhone SE не указано поколение, а цены поколений сильно разные"
    if st == "no_market":
        return "аналоги не загружены (Куфар не ответил), оценка появится позже"
    if st == "error":
        return "внутренняя ошибка расчёта"
    if st == "few":
        return f"недостаточно аналогов: найдено {ap.get('found', 0)}, нужно хотя бы {REF_MIN}"
    if not facts["price"]:
        return "цена не указана — нужно уточнить у продавца"
    if ap.get("thin"):
        return f"недостаточно аналогов: {(ap.get('stats') or {}).get('n', 0)}, нужно хотя бы {MIN_COMPS}"
    _b, c = _shown_variant(ap)
    if c and not c["final"]:
        return f"неизвестна цена ремонта ({', '.join(c['rep_unknown'])})"
    if not c and not plan.get("upper"):
        return no_estimate_reason(facts, ap)
    _code, text = ap.get("decision") or decide(facts, ap)
    return text.partition(" — ")[2].rstrip(".") or "данных мало"


def short_verdict(facts, ap):
    """(значок, ВЕРДИКТ, пояснение). Только три вердикта; «покупать после торга» = НЕВЫГОДНО по текущей цене + цель торга."""
    code, _text = ap.get("decision") or decide(facts, ap)
    price, conf = facts["price"], ap.get("conf")
    plan = ap.get("plan") or {}
    _best, c = _shown_variant(ap)
    crit = _crit(facts)
    if crit:
        return "🔴", "НЕВЫГОДНО", f"{', '.join(crit)}: исход ремонта и цена продажи непредсказуемы."
    if code == "skip":
        ref = c or plan.get("upper")
        if ref and price:
            lim = max(0, ref["limit"])
            tail = " (даже если продать как исправный)" if not c else ""
            if lim <= 0:
                return "🔴", "НЕВЫГОДНО", f"Продавец просит {money(price)} BYN, а с учётом расходов и прибыли сделка не окупается ни при какой цене{tail}."
            return "🔴", "НЕВЫГОДНО", f"Продавец просит {money(price)} BYN, максимальная покупка для перепродажи — {money(lim)} BYN{tail}."
        return "🔴", "НЕВЫГОДНО", short_reason(facts, ap)
    if code == "buy":
        if conf == "низкая":
            why = "; ".join(ap.get("conf_why") or []) or "мало данных"
            return "⚪", "НЕДОСТАТОЧНО ДАННЫХ", f"по расчёту выгодно ({money(price)} ≤ {money(c['limit'])} BYN), но оценка ненадёжна: {why}."
        return "✅", "ВЫГОДНО", ""
    if code == "bargain" and c and price:
        if price > c["limit"]:
            if not c["final"]:
                return "🔴", "НЕВЫГОДНО по текущей цене", (f"Максимум {money(max(0, c['limit']))} BYN ещё до ремонта "
                                                         f"({', '.join(c['rep_unknown'])} — цена не известна), просят {money(price)} BYN.")
            return "🔴", "НЕВЫГОДНО по текущей цене", f"Станет выгодно, если сторговаться до {money(c['limit'])} BYN (сейчас {money(price)} BYN)."
        return "⚪", "НЕДОСТАТОЧНО ДАННЫХ", f"цена в пределах максимума, но оценка ненадёжна — торгуйся до {money(c['desired'])} BYN."
    return "⚪", "НЕДОСТАТОЧНО ДАННЫХ", short_reason(facts, ap)


def short_risk(facts, ap):
    """Одна строка о риске, который способен полностью изменить расчёт (или None)."""
    e = html.escape
    pc = facts.get("price_conflict")
    if pc:
        was = f"{money(pc['search'])} BYN" if pc["search"] else "без цены"
        now_ = f"{money(pc['card'])} BYN" if pc["card"] else "без цены"
        return f"⚠️ Цена в поиске {was}, на странице объявления — {now_}: расчёт по цене страницы, сверь перед покупкой."
    if facts.get("price_card_invalid"):
        return (f"⚠️ В карточке объявления нет действительной цены, цена {money(facts['price'])} BYN взята из поиска и не подтверждена"
                " — уточни у продавца.")
    if facts.get("price_src") != PRICE_SRC_CARD and (ap.get("status") == "ok" or facts.get("price_unverified")):
        return "⚠️ Цена и описание не сверены с карточкой объявления (взяты из поиска) — открой его перед решением."
    if facts.get("conflicts") and not facts.get("model_conflict"):
        return "⚠️ Противоречие: " + e(facts["conflicts"][0]) + " — уверенность снижена."
    ph = facts.get("photo") or {}
    if ph.get("status") == "analyzed" and ph.get("mismatch"):
        return "⚠️ Фото расходится с описанием: " + e(ph["mismatch"])
    clean_st = (ap.get("clean") or {}).get("st")
    if facts["price"] and clean_st and facts["price"] < 0.5 * clean_st["med"] and max_severity(facts["defects"]) < 2:
        return "⚠️ Цена вдвое ниже рынка — проверь блокировку iCloud/аккаунта и продавца."
    if ap.get("status") == "ok" and not facts["desc"]:
        return "⚠️ Описания нет — дефекты могли не указать, открой объявление."
    return None


def _profit_text(lo, hi):
    if lo >= 0:
        return f"около {rng(lo, hi)} BYN"
    return f"от {signed(lo)} до {signed(hi)} BYN"


def build_short_message(ad, facts, ap):
    """📱 модель · 💰 цена продавца · 📍 регион / 📊 перепродажа · ⚡ быстрая продажа · 💸 максимум · 🎯 желательно · 📈 прибыль /
    вердикт (ВЫГОДНО / НЕВЫГОДНО / НЕДОСТАТОЧНО ДАННЫХ) · уверенность · одно предупреждение · ссылка."""
    e = html.escape
    price = facts["price"]
    head = facts["label"] if facts["label"] != "Другое" else (ad.get("subject") if isinstance(ad.get("subject"), str) else "") or "Телефон"
    if facts["label"] != "Другое" and facts["mem"]:
        head += f" {facts['mem']} ГБ"
    cur = ""
    usd = price_usd(ad)
    if facts.get("currency") == "USD" and usd:
        cur = f" (продавец указал цену в $: {money(usd)})"  # страница показывает рубли по курсу Куфара — их и считаем
    lines = [f"📱 <b>{e(head)}</b>",
             "💰 Цена продавца: " + (f"{money(price)} BYN{cur}" if price else "не указана — нужно уточнить"),
             f"📍 {e(facts['region'] or 'регион не указан')}" + (" · магазин" if facts["seller"] == "магазин" else "")]
    defects = [n for _c, n in sorted(facts["defects"].items(), key=lambda kv: -SEVERITY.get(kv[0], 0)) if SEVERITY.get(_c, 0) >= 1]
    if defects:
        lines.append("🔧 По описанию: " + e("; ".join(defects[:3])))
    best, c = _shown_variant(ap)
    plan = ap.get("plan") or {}
    if ap.get("status") == "ok" and c:
        after = " после ремонта" if best == "B" else ""
        # верхняя граница — верхняя четверть цен ТЕХ ЖЕ аналогов, по которым посчитан показанный вариант (у расчёта между
        # категориями своих аналогов нет — показываем одно число)
        src_st = ((ap.get("clean") or {}).get("st") if best == "B" else (plan.get("asis") or {}).get("st")) or {}
        hi = rnd5(src_st["q3"]) if src_st.get("q3") and rnd5(src_st["q3"]) > c["list"] else c["list"]
        lines += ["", f"📊 Перепродажа{after}: {rng(c['list'], hi)} BYN", f"⚡ Быстрая продажа: около {money(c['quick'])} BYN"]
        if c["limit"] <= 0:
            lines.append("💸 Максимум покупки: не окупается при любой цене")
        else:
            lines.append(f"💸 Максимум покупки: {money(c['limit'])} BYN" + (" (до ремонта)" if not c["final"] else ""))
            lines.append(f"🎯 Желательно купить за: {money(max(0, c['desired']))} BYN")
        if price and "profit" in c:
            lo, hi_p = sorted((c["profit"], c["profit_opt"]))
            roi = ""
            if c.get("roi") is not None and c.get("roi_opt") is not None:
                r_lo, r_hi = sorted((c["roi"] * 100, c["roi_opt"] * 100))
                roi = f" (ROI {r_lo:+.0f}…{r_hi:+.0f}%)".replace("-", "−")
            lines.append(f"📈 Прибыль после расходов: {_profit_text(lo, hi_p)}{roi}" + (" — до вычета ремонта" if not c["final"] else ""))
        elif not price:
            lines.append("📈 Прибыль: цену нужно уточнить")
        rp = plan.get("repair") or {}
        be = plan.get("breakeven")
        if rp.get("unknown") and be is not None and best == "A":
            lines.append(f"🔧 Ремонт ({e(', '.join(rp['unknown']))}) имеет смысл, если обойдётся не дороже ≈ {money(max(0, be))} BYN")
        elif c and not c["final"] and price and c["limit"] > price:
            room = floor5((c["limit"] - price) / (1 + REPAIR_OVERRUN_PCT / 100))
            lines.append(f"🔧 Ремонт ({e(', '.join(c['rep_unknown']))}) должен уложиться в ≈ {money(room)} BYN")
    icon, verdict, why = short_verdict(facts, ap)
    lines.append("")
    if verdict == "ВЫГОДНО":
        cond = ", если дефекты не обнаружатся" if (plan.get("unconfirmed") or not facts["desc"]) else ""
        lines.append(f"{icon} <b>{verdict}</b>{cond}")
    else:
        lines.append(f"{icon} <b>{verdict}</b>")
        if why:
            lines.append(("Причина: " if verdict.startswith("НЕДОСТАТОЧНО") else "") + e(why[:1].upper() + why[1:] if verdict.startswith("НЕВЫГОДНО") else why))
    st = ap.get("stats") or {}
    if ap.get("conf") and st.get("n") and not _crit(facts):  # при критичном дефекте аналоги исправных к решению отношения не имеют
        approx = ""
        asis = plan.get("asis") or {}
        if asis.get("src") in ("cat", "interp") and best == "A":
            approx = ", расчёт приблизительный"
        lines.append(f"Уверенность: {ap['conf']} · {n_comps(st['n'])} (цены объявлений, не сделок{approx}).")
    risk = short_risk(facts, ap)
    if risk:
        lines.append(risk)
    lines += ["", "🔗 " + e(ad.get("ad_link") if isinstance(ad.get("ad_link"), str) and ad.get("ad_link") else item_url(ad["ad_id"]))]
    return "\n".join(lines)


def n_comps(n):
    return f"{n} {_ads_form(n, 'сопоставимое объявление', 'сопоставимых объявления', 'сопоставимых объявлений')}"


def build_message(ad, facts, ap):
    """Сообщение в Telegram: короткое (по умолчанию) или подробное (MESSAGE_STYLE=full)."""
    if MESSAGE_STYLE == "full":
        return build_full_message(ad, facts, ap)
    return build_short_message(ad, facts, ap)


# ---------- База рынка: market_history.json ----------
# Постоянная база НАБЛЮДЕНИЙ (не «обучение» нейросети): каждое увиденное объявление нужной модели — одна запись по номеру, повторное
# появление обновляет её. Используется для аналогов в оценке (вместе со свежей выдачей) и как журнал уведомлений.
# В записи только то, что действительно получено, с источником: «текст продавца», «параметры Куфара», «фото (нейросеть)».
# Исчезновение из выдачи не значит «продано»: такая запись получает статус not_seen («не видно в выдаче»), не «sold».
# Файл пишется по одной записи на строку и с сортировкой — так коммиты в git маленькие (меняются только строки изменённых записей).

MARKET_DB_FILE = Path(__file__).with_name("market_history.json")
MDB = {"ok": True, "loaded": 0, "why": "", "data": {"version": 1, "ads": {}}}
MDB_TOUCH_S = 6 * 3600  # last_seen у неизменившихся записей обновляется не чаще раза в 6 часов (маленькие коммиты)


def _iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def mdb_reset():
    MDB.update(ok=True, loaded=0, why="", data={"version": 1, "ads": {}})


def mdb_load():
    """Читает базу. Нет файла — пустая база. Файл повреждён — база выключается на этот запуск: файл НЕ перезаписывается
    (восстановить можно из истории git), уведомления продолжают работать по seen.json."""
    mdb_reset()
    try:
        text = MARKET_DB_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return True
    except OSError as e:
        MDB.update(ok=False, why=f"не читается: {e}")
        log("База рынка не читается, в этом запуске не сохраняю её:", e)
        return False
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("ads"), dict):
            raise ValueError("нет раздела ads")
    except Exception as e:
        MDB.update(ok=False, why=f"повреждена: {e}")
        log(f"База рынка {MARKET_DB_FILE.name} повреждена ({e}) — файл не трогаю и в этом запуске не перезаписываю. "
            "Восстанови прошлую версию из истории git.")
        return False
    data["ads"] = {k: v for k, v in data["ads"].items() if isinstance(v, dict)}
    MDB["data"], MDB["loaded"] = data, len(data["ads"])
    return True


def _mdb_ads():
    return MDB["data"].setdefault("ads", {})


def mdb_first_lt(ad_id):
    """Самый ранний list_time, который база видела у этого объявления (unix-время) или None."""
    rec = _mdb_ads().get(str(ad_id))
    if not rec:
        return None
    vals = [parse_list_time(x) for x in [rec.get("list_time")] + list(rec.get("list_time_hist") or [])]
    vals = [v for v in vals if v is not None]
    return min(vals) if vals else None


def price_hist_norm(hist):
    """История цены в формате [время, цена, источник]. Старые записи [время, цена] — наблюдения выдачи."""
    out = []
    for h in hist or []:
        if isinstance(h, list) and len(h) in (2, 3) and isinstance(h[1], (int, float)) and not isinstance(h[1], bool):
            out.append([h[0], h[1], h[2] if len(h) == 3 and h[2] in ("search", "card") else "search"])
    return out


def price_current(hist):
    """(текущая цена, источник). Карточка (цена страницы) в приоритете; выдача — только если ЕЁ значение изменилось позже
    последнего наблюдения карточки (значит, продавец снова поменял цену, а карточку с тех пор не смотрели)."""
    last = {}
    for h in hist:
        last[h[2]] = h
    c, srch = last.get("card"), last.get("search")
    if c and (not srch or c[0] >= srch[0]):
        return c[1], "card"
    if srch:
        return srch[1], "search"
    return None, None


def price_changes(hist):
    """Сколько раз цена действительно менялась: смены значения внутри каждого источника (выдача с выдачей, карточка с карточкой)."""
    hist = price_hist_norm(hist)
    return sum(max(0, sum(1 for h in hist if h[2] == src_) - 1) for src_ in ("search", "card"))


def mdb_observe(ad, comp=None, key=None, facts=None, now=None, checked=False):
    """Добавляет или обновляет запись об объявлении. Ничего не придумывает: пустое поле не записывается, факты из описания
    заменяются только новым описанием (выдача без описания их не стирает). Ошибки не выходят наружу."""
    try:
        return _mdb_observe(ad, comp, key, facts, now, checked)
    except Exception as e:
        log("База рынка: не удалось записать наблюдение:", (ad or {}).get("ad_id") if isinstance(ad, dict) else None, e)
        return None


def _mdb_observe(ad, comp, key, facts, now, checked):
    if not isinstance(ad, dict):
        return None
    try:
        ad_id = int(ad.get("ad_id"))
    except (TypeError, ValueError):
        return None
    now = int(now or time.time())
    ads = _mdb_ads()
    rec = ads.get(str(ad_id))
    new = rec is None
    if new:
        rec = {"first_seen": now}
    changed = new
    title = ad.get("subject") if isinstance(ad.get("subject"), str) else ""
    link = ad.get("ad_link") if isinstance(ad.get("ad_link"), str) and ad.get("ad_link") else item_url(ad_id)
    rec["url"], rec["title"] = link, title[:120]
    price = price_byn(ad)
    src = "card" if ad.get("_price_src") == PRICE_SRC_CARD else "search"
    # исходные поля цены — отдельно по источникам (старый плоский формат price_raw был наблюдением выдачи)
    pr = rec.get("price_raw") if isinstance(rec.get("price_raw"), dict) else {}
    if pr and not ({"search", "card"} & set(pr)):
        pr = {"search": pr}
    raw = {k: ad.get(k) for k in ("price_byn", "price_usd", "currency") if isinstance(ad.get(k), (str, int, float)) and not isinstance(ad.get(k), bool)}
    if "_price_raw_search" in ad:  # карточку применили поверх выдачи: исходное значение выдачи тоже сохраняем
        pr["search"] = dict(pr.get("search") or {}, price_byn=ad["_price_raw_search"])
    if "_price_raw_card" in ad:
        pr["card"] = dict(pr.get("card") or {}, price_byn=ad["_price_raw_card"])
    if raw:
        pr[src] = dict(pr.get(src) or {}, **raw)
    if pr:
        rec["price_raw"] = pr
    # история: [время, цена, источник]. Изменение = смена значения ВНУТРИ одного источника (сопоставимые наблюдения);
    # расхождение выдачи и карточки — не изменение цены, оно пишется отдельно в price_conflict
    hist = price_hist_norm(rec.get("price_hist"))
    if price > 0:  # наблюдение без действительной цены не затирает известную цену и не считается её изменением
        same = [h for h in hist if h[2] == src]
        if not same or same[-1][1] != price:
            hist.append([now, price, src])
            changed = True
    if hist:
        rec["price_hist"] = hist[-16:]
    cur_price, cur_src = price_current(hist)
    rec["price_byn"] = cur_price
    if cur_src:
        rec["price_src"] = "карточка" if cur_src == "card" else "выдача"
    if ad.get("_price_conflict"):  # выдача и карточка расходились: храним обе цифры с датой
        pc = ad["_price_conflict"]
        rec["price_conflict"] = {"search": pc["search"], "card": pc["card"], "t": now}
    if "_price_card_invalid" in ad:  # в карточке недействительная цена: храним, что пришло, цену выдачи не подтверждаем
        rec["price_card_invalid"] = {"raw": ad["_price_card_invalid"], "t": now}
    if isinstance(ad.get("currency"), str):
        rec["currency"] = ad["currency"]
    lt = parse_list_time(ad.get("list_time"))
    if lt is not None:
        iso = _iso(lt)
        old = rec.get("list_time")
        if old and old != iso:
            lh = [x for x in (rec.get("list_time_hist") or []) if isinstance(x, str)]
            if old not in lh:
                lh.append(old)
            rec["list_time_hist"] = lh[-5:]
            changed = True
        rec["list_time"] = iso
    elif ad.get("list_time") not in (None, ""):
        rec["list_time_raw"] = str(ad.get("list_time"))[:40]  # дата пришла, но не разобралась — храним как есть
    if facts is None:
        try:
            facts = rule_facts(ad)
        except Exception:
            facts = None
    if facts:
        rec["model"] = {"label": facts["label"], "conf": facts.get("model_conf"), "src": facts.get("model_src")}
        if facts["mem"]:
            rec["mem_gb"], rec["mem_src"] = facts["mem"], facts.get("mem_src") or "текст"
        for k_, v_ in (("region", facts["region"]), ("area", facts["area"]), ("seller", facts["seller"]),
                       ("condition", param(ad, "condition"))):
            if v_:
                rec[k_] = v_
        if facts["desc"] or "defects" not in rec:  # факты из текста: описание надёжнее одного заголовка
            if facts["defects"]:
                rec["defects"], rec["defects_src"] = dict(facts["defects"]), "текст продавца"
            elif facts["desc"]:
                rec.pop("defects", None)
                rec["defects_src"] = "текст продавца: дефекты не названы (это не подтверждение исправности)"
            if facts["battery_pct"] is not None:
                rec["battery"] = {"pct": facts["battery_pct"], "src": "текст продавца"}
            elif facts["desc"]:
                rec.pop("battery", None)
            kit = [x for x in facts["kit"] if x != "только телефон"]
            if kit:
                rec["kit"] = {"items": kit, "src": "текст продавца", "photo_confirmed": False}
            if facts.get("conflicts"):
                rec["conflicts"] = list(facts["conflicts"])
            else:
                rec.pop("conflicts", None)
            rec["has_desc"] = bool(facts["desc"]) or rec.get("has_desc", False)
        if comp is None and facts["label"] != "Другое":
            try:
                k2 = market_key(facts["label"])
                comp, key = comp_item(ad, k2), k2
            except Exception:
                comp = None
    if comp:
        new_comp = [int(round(rec["price_byn"])) if rec.get("price_byn") else comp[1], comp[2], comp[3], comp[4], comp[5]]
        if rec.get("comp") != new_comp:
            changed = True
        rec["comp"], rec["key"] = new_comp, key
    if changed or checked or now - int(rec.get("last_seen") or 0) >= MDB_TOUCH_S:
        rec["last_seen"] = now
    if checked:
        rec["last_check"] = now
    ads[str(ad_id)] = rec
    return rec


def mdb_note(ad_id, status, why="", now=None):
    """Отметка об уведомлении: sent (отправлено), expired (устарело к отправке), failed (Telegram не принял), skipped (не свежее)."""
    rec = _mdb_ads().setdefault(str(ad_id), {"first_seen": int(now or time.time()), "url": item_url(ad_id)})
    rec["notify"] = {"status": status, "t": int(now or time.time()), **({"why": why[:120]} if why else {})}


def mdb_notified(ad_id):
    rec = _mdb_ads().get(str(ad_id)) or {}
    return (rec.get("notify") or {}).get("status") == "sent"


def mdb_appraisal(ad_id, facts, ap, now=None):
    """Результат оценки (последние 3): вердикт, уровни цены, на скольких и каких аналогах посчитано."""
    try:
        rec = _mdb_ads().get(str(ad_id))
        if rec is None:
            return
        plan = ap.get("plan") or {}
        c = plan.get(plan.get("best")) if plan.get("best") else None
        st = ap.get("stats") or {}
        row = {"t": int(now or time.time()), "verdict": (ap.get("decision") or ("unknown", ""))[0], "status": ap.get("status"),
               "conf": ap.get("conf"), "n": st.get("n", 0), "db_comps": ap.get("db_comps", 0),
               "comps": [it[0] for it in (ap.get("comps") or [])][:5]}
        if ap.get("history"):  # прошлые (неактивные) предложения — отдельно от текущей оценки
            row["history"] = {k_: ap["history"][k_] for k_ in ("n", "med", "changed")}
        if c:
            row.update(max_buy=c["limit"], desired=c["desired"], quick=c["quick"], resale=c["list"])
        if facts.get("price"):
            row["price"] = facts["price"]
        rec["appraisals"] = ((rec.get("appraisals") or []) + [row])[-3:]
        ph = facts.get("photo") or {}
        if ph.get("status") == "analyzed":  # только если запрос к нейросети с фото действительно состоялся
            rec["photo"] = {"t": int(now or time.time()), "n": ph.get("n", 0), "src": "фото (нейросеть), не проверка",
                            "findings": [{"what": f["what"], "conf": f["conf"]} for f in ph.get("findings") or []][:4],
                            "kit_visible": list(ph.get("kit") or [])}
            if rec.get("kit") and ph.get("kit"):
                rec["kit"]["photo_confirmed"] = True
    except Exception as e:
        log("База рынка: не удалось записать оценку:", ad_id, e)


def mdb_is_active(rec, now=None):
    """Активное = объявление видели в выдаче не позже MARKET_ACTIVE_DAYS дней назад. Наличие записи в базе активности не означает.
    Исчезновение из выдачи не значит «продано»: такая запись просто перестаёт быть текущим предложением."""
    return (now or time.time()) - int(rec.get("last_seen") or 0) <= MARKET_ACTIVE_DAYS * 86400


def _comp_row(k_, rec):
    c = rec.get("comp")
    if not isinstance(c, list) or len(c) != 5:
        return None
    try:
        if not c[0] or c[0] <= 0:
            return None
        return [int(k_), int(c[0]), int(c[1] or 0), int(c[2] or 0), int(c[3] or 0), int(c[4] or 0), title_key(rec.get("title") or "")]
    except (TypeError, ValueError):
        return None


def mdb_comps(key, now=None):
    """ТЕКУЩИЕ аналоги из базы: та же модель, активная запись (видели в выдаче не позже MARKET_ACTIVE_DAYS), действительная
    последняя цена, без противоречий в характеристиках. Давно не встречавшиеся записи сюда не попадают — даже если аналогов мало:
    тогда честно падает уверенность, а выборка не раздувается устаревшими ценами."""
    if not key:
        return []
    out = []
    for k_, rec in _mdb_ads().items():
        if rec.get("key") != key or rec.get("conflicts") or not mdb_is_active(rec, now):
            continue
        row = _comp_row(k_, rec)
        if row:
            out.append(row)
    return out


def mdb_history(key, mem=0, now=None):
    """ИСТОРИЧЕСКАЯ сводка (отдельно от текущей оценки): записи той же модели (и памяти, если известна), которые уже не активны,
    но видны в базе. Это прошлые цены предложений: для анализа изменения цен, а не для максимума покупки.
    {n, med, min, max, changed (у скольких цена менялась)} или None."""
    if not key:
        return None
    prices, changed = [], 0
    for k_, rec in _mdb_ads().items():
        if rec.get("key") != key or rec.get("conflicts") or mdb_is_active(rec, now):
            continue
        row = _comp_row(k_, rec)
        if not row or (mem and row[2] and row[2] != mem) or row[3] & (F_DEF | F_PARTS):
            continue
        prices.append(row[1])
        changed += price_changes(rec.get("price_hist")) > 0
    if not prices:
        return None
    return {"n": len(prices), "med": statistics.median(prices), "min": min(prices), "max": max(prices), "changed": changed}


def _mdb_status(rec, now):
    rec["status"] = "active" if mdb_is_active(rec, now) else "not_seen"
    flags = []
    if price_changes(rec.get("price_hist")):
        flags.append("price_changed")
    if rec.get("price_conflict") or rec.get("price_card_invalid"):
        flags.append("price_sources_differ")  # выдача и карточка расходились — это не изменение цены
    if not rec.get("defects") and not rec.get("has_desc"):
        flags.append("condition_unconfirmed")
    if rec.get("list_time_hist"):
        flags.append("relisted")
    if flags:
        rec["flags"] = flags
    else:
        rec.pop("flags", None)


def mdb_prune(now=None):
    """Удаляет только то, что безопасно: записи, не появлявшиеся в выдаче MARKET_DB_DAYS дней (кроме отправленных за последние
    30 дней — они нужны против повторов), и при переполнении — тех, кого дольше всего не видели."""
    now = int(now or time.time())
    ads = _mdb_ads()
    keep_sent = now - 30 * 86400

    def protected(rec):
        n = rec.get("notify") or {}
        return n.get("status") == "sent" and int(n.get("t") or 0) >= keep_sent

    old = now - MARKET_DB_DAYS * 86400
    for k_ in [k_ for k_, r in ads.items() if int(r.get("last_seen") or r.get("first_seen") or 0) < old and not protected(r)]:
        del ads[k_]
    if len(ads) > MARKET_DB_MAX:
        victims = sorted((int(r.get("last_seen") or 0), k_) for k_, r in ads.items() if not protected(r))
        for _t, k_ in victims[:len(ads) - MARKET_DB_MAX]:
            del ads[k_]


def mdb_save(now=None):
    """Атомарная запись: временный файл → проверка, что он читается → замена. Возвращает True при успехе.
    Не пишет: в тестовом запуске; если база при загрузке оказалась повреждённой; если в памяти записей вдвое меньше, чем
    было загружено (это похоже на ошибку, а не на очистку). Ошибка записи не роняет запуск: уведомления хранятся в seen.json."""
    if DRY_RUN:
        return False
    if not MDB["ok"]:
        log(f"База рынка не сохранена: {MDB['why']}")
        return False
    now = int(now or time.time())
    ads = _mdb_ads()
    if MDB["loaded"] >= 100 and len(ads) < MDB["loaded"] * 0.5:
        log(f"База рынка не сохранена: в памяти {len(ads)} записей, а загружено было {MDB['loaded']} — похоже на ошибку")
        return False
    tmp = MARKET_DB_FILE.with_name(MARKET_DB_FILE.name + ".tmp")
    try:
        mdb_prune(now)
        for rec in ads.values():
            _mdb_status(rec, now)
        head = {k: v for k, v in MDB["data"].items() if k != "ads"}
        head.update(version=1, updated=_iso(now), count=len(ads),
                    note="Наблюдения за объявлениями Куфара: цены объявлений (не сделок). Статус not_seen — не видно в выдаче, не «продано».")
        lines = [f'"{k_}":' + json.dumps(ads[k_], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                 for k_ in sorted(ads, key=lambda x: (len(x), x))]
        text = json.dumps(head, ensure_ascii=False, separators=(",", ":"), sort_keys=True)[:-1] + ',"ads":{\n' + ",\n".join(lines) + "\n}}\n"
        tmp.write_text(text, encoding="utf-8")
        check = json.loads(tmp.read_text(encoding="utf-8"))
        if len(check.get("ads") or {}) != len(ads):
            raise ValueError("записанный файл не совпадает с базой в памяти")
        os.replace(tmp, MARKET_DB_FILE)
        MDB["loaded"] = len(ads)
        return True
    except Exception as e:
        log("База рынка не сохранена (ошибка записи), прежний файл не тронут:", e)
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


# ---------- Основной цикл ----------

SEEN_MAX =max(1, int(_env_float("SEEN_MAX", 10000)))  # сколько id объявлений помнить; вытесняются те, кого дольше всего не видели


class Seen(set):
    """Множество обработанных id, сохраняющее время последнего появления объявления в выдаче.

    Раньше в seen.json хранились 5000 самых больших id. Старые объявления из узких запросов
    выпадали из памяти и отправлялись повторно. Теперь вытесняются объявления, которые дольше всего не встречались.
    """

    def __init__(self, items=()):
        super().__init__()
        self.ts = {}  # id -> unix time последнего появления
        for item in items:
            self.add(item)

    def add(self, ad_id, ts=None):
        super().add(ad_id)
        self.ts[ad_id] = int(ts or time.time())

    def update(self, *others):
        for other in others:
            for ad_id in other:
                self.add(ad_id)

    def touch(self, ad_id):
        """Объявление ещё есть в выдаче: не чаще раза в сутки обновляем время в памяти."""
        now = int(time.time())
        if ad_id in self and now - self.ts.get(ad_id, 0) > 86400:
            self.ts[ad_id] = now


def load_seen():
    """Поддерживает новый формат seen={id: timestamp} и старые форматы списков id. None = первый запуск."""
    try:
        data = json.loads(SEEN_FILE.read_text())
    except Exception:
        return None
    if isinstance(data, list):
        data = {"seen": data}
    if not isinstance(data, dict):
        return None
    HISTORY.update(data.get("history") or {})
    raw = data.get("seen") or []
    now = int(time.time())
    seen = Seen()
    if isinstance(raw, dict):  # новый формат: {id: время последнего появления}
        for key, timestamp in raw.items():
            try:
                seen.add(int(key), int(timestamp))
            except (TypeError, ValueError):
                pass
    else:  # старый формат: считаем сохранённые id давно не встречавшимися
        for key in raw:
            try:
                seen.add(int(key), now - 30 * 86400)
            except (TypeError, ValueError):
                pass
    market = data.get("market")
    STATE["market"] = market if isinstance(market, dict) else {}
    base = data.get("baseline")
    # файл от старой версии: запросы iphone/samsung/ipod touch уже «запомнены», остальные запомним молча при первом заходе
    STATE["baseline"] = list(base) if isinstance(base, list) else (list(LEGACY_QUERIES) if seen else [])
    STATE["notice"] = int(data.get("notice") or 0)
    pending = data.get("pending")
    STATE["pending"] = pending if isinstance(pending, dict) else {}
    marks = data.get("marks")
    STATE["marks"] = {str(b): [int(v[0]), int(v[1])] for b, v in marks.items()
                      if str(b).isdigit() and isinstance(v, list) and len(v) == 2
                      and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)} if isinstance(marks, dict) else {}
    # При переходе со старого формата объявления из HISTORY тоже считаем уже обработанными,
    # кроме объявлений, которые явно ожидают повторной отправки.
    if not isinstance(raw, dict):
        for key, rec in HISTORY.items():
            if str(key).isdigit() and str(key) not in STATE["pending"] and isinstance(rec, dict):
                try:
                    seen.add(int(key), now)
                except (TypeError, ValueError):
                    pass
    return seen


def save_seen(seen):
    """Атомарно сохраняет состояние и вытесняет id, которых дольше всего не видели."""
    if DRY_RUN:
        return
    cutoff = time.time() - 35 * 86400  # историю старше 5 недель не храним
    for k in [k for k, r in HISTORY.items() if r.get("t", 0) < cutoff]:
        del HISTORY[k]
    week = time.time() - 7 * 86400
    market = {k: v for k, v in STATE["market"].items() if isinstance(v, dict) and v.get("t", 0) > week}
    # Держим не больше SEEN_MAX id; первыми вытесняются те, кого дольше всего не видели.
    newest = sorted(seen.ts.items(), key=lambda kv: kv[1])[-SEEN_MAX:]
    mark_cut = time.time() - 14 * 86400  # метки номеров нужны только за последние часы; две недели — с запасом
    marks = {b: v for b, v in sorted(STATE["marks"].items(), key=lambda kv: int(kv[0])) if v[1] >= mark_cut}
    data = {"seen": {str(ad_id): timestamp for ad_id, timestamp in sorted(newest)}, "history": HISTORY, "market": market,
            "baseline": sorted(set(STATE["baseline"])), "notice": STATE["notice"], "pending": STATE["pending"], "marks": marks}
    tmp = SEEN_FILE.with_name(SEEN_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, SEEN_FILE)

_KEEP = ("ad_id", "ad_link", "subject", "type", "company_ad", "price_byn", "price_usd", "body", "body_short", "list_time", "currency")


def stash(ad_id, ad):
    """Объявление не удалось отправить сейчас (Telegram недоступен, не хватило времени) — повторим в следующих запусках,
    даже если оно уже уйдёт из выдачи Куфара."""
    slim = {k: ad[k] for k in _KEEP if k in ad}
    slim["ad_parameters"] = [{"p": x.get("p"), "vl": x.get("vl")} for x in (ad.get("ad_parameters") or []) if isinstance(x, dict)]
    slim["images"] = [{"path": im["path"], "yams_storage": bool(im.get("yams_storage")), "media_storage": im.get("media_storage")}
                      for im in (ad.get("images") or [])[:max(PHOTOS_MAX, 1)] if isinstance(im, dict) and im.get("path")]  # чтобы повтор не потерял фото
    STATE["pending"][str(ad_id)] = {"t": STATE["pending"].get(str(ad_id), {}).get("t") or int(time.time()), "ad": slim}


def unstash(ad_id):
    STATE["pending"].pop(str(ad_id), None)


def pending_ads(seen):
    """Неотправленные объявления: убираем уже отправленные и старше PENDING_TTL_H часов, не больше 40 штук."""
    now, out = time.time(), {}
    for key, v in list(STATE["pending"].items()):
        try:
            ad_id = int(key)
            ok = isinstance(v, dict) and isinstance(v.get("ad"), dict) and now - v.get("t", 0) <= PENDING_TTL_H * 3600 and ad_id not in seen
        except (ValueError, TypeError):
            ok = False
        if not ok:
            STATE["pending"].pop(key, None)
        else:
            out[ad_id] = v["ad"]
    for key, _v in sorted(STATE["pending"].items(), key=lambda kv: kv[1].get("t", 0))[:-40]:
        STATE["pending"].pop(key, None)
        out.pop(int(key), None)
    return out


def pick_extra(now=None):
    """Дополнительные запросы на этот запуск: каждый ходит раз в 3 пятиминутных «слота»."""
    slot = int((now or time.time()) // 300)
    return [q for i, q in enumerate(EXTRA_QUERIES) if i % 3 == slot % 3 and q not in QUERIES]


def is_suspicious(facts, ap):
    """Цена вдвое ниже рынка без заметных дефектов — похоже на развод; в цены для недельного отчёта не берём."""
    st = (ap.get("clean") or {}).get("st") or ap.get("stats")
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


def _remaining(fresh_until):
    return float("inf") if fresh_until is None else fresh_until - time.time()


PRICE_SRC_CARD = "карточка объявления (совпадает со страницей Куфара)"
PRICE_SRC_SEARCH = "поисковая выдача (карточка не получена — с карточкой не сверено)"


def apply_card(ad, card):
    """Сверяет объявление из выдачи с его карточкой. Источник цены — карточка: страница kufar.by/item/… показывает именно её
    price_byn (проверено на живом объявлении: страница «2 150.29 р.» = price_byn «215029» карточки). Выдача — поисковый индекс,
    он может отставать после того, как продавец изменил цену. Минимальная из двух цен НЕ выбирается: при расхождении берётся
    цена страницы, а расхождение записывается (ad["_price_conflict"]) и показывается в сообщении."""
    if isinstance(card.get("body"), str) and card["body"]:
        ad["body"] = card["body"]
    ad["_price_raw_search"] = ad.get("price_byn")  # исходные значения сохраняем как есть, что бы ни случилось дальше
    if "price_byn" in card:
        ad["_price_raw_card"] = card.get("price_byn")
        cp, sp = _kopecks(card.get("price_byn")), price_byn(ad)
        if cp > 0:  # в карточке действительная цена — это цена страницы
            if cp != sp:
                ad["_price_conflict"] = {"search": sp, "card": cp, "search_raw": ad.get("price_byn"), "card_raw": card.get("price_byn")}
                ad["price_byn_search"], ad["price_byn"] = ad.get("price_byn"), card.get("price_byn")
                if "price_usd" in card:
                    ad["price_usd"] = card.get("price_usd")
            ad["_price_src"] = PRICE_SRC_CARD
        elif sp > 0:
            # в карточке цена нулевая, отрицательная или некорректная, а в выдаче — действительная: выдачу НЕ затираем,
            # но цену и не подтверждаем — неизвестно, «договорная» ли теперь цена или карточка отдала мусор
            ad["_price_card_invalid"] = card.get("price_byn")
            ad["_price_src"] = PRICE_SRC_SEARCH
        else:
            ad["_price_src"] = PRICE_SRC_CARD  # цены нет ни там, ни там — согласованно «не указана»
    if isinstance(card.get("currency"), str):
        ad["currency"] = card["currency"]
    clt, slt = parse_list_time(card.get("list_time")), parse_list_time(ad.get("list_time"))
    if clt is not None and slt is not None and abs(clt - slt) >= 1:
        log(f"list_time в карточке {ad.get('ad_id')} отличается от выдачи: беру более раннее (строже по свежести)")
        if clt < slt:
            ad["list_time"] = card.get("list_time")


def price_diag(ad, db_rec):
    """Строка журнала: откуда какая цена пришла (выдача, карточка, база). Только данные объявления — никаких токенов и ключей."""
    pc = ad.get("_price_conflict") or {}
    search_raw = ad.get("_price_raw_search", pc.get("search_raw", ad.get("price_byn")))
    card_raw = ad.get("_price_raw_card", "—")
    base = "записи нет"
    if db_rec and db_rec.get("price_byn"):
        base = f"{db_rec['price_byn']:g} BYN (источник: {db_rec.get('price_src') or 'выдача'})"
    note = ""
    if pc:
        note = " ⚠ ВЫДАЧА И КАРТОЧКА РАСХОДЯТСЯ"
    elif "_price_card_invalid" in ad:
        note = (f" ⚠ В КАРТОЧКЕ НЕТ ДЕЙСТВИТЕЛЬНОЙ ЦЕНЫ ({ad['_price_card_invalid']!r}): оставлена цена выдачи, она не подтверждена")
    return (f"Цена {ad.get('ad_id')}: выдача price_byn={search_raw!r}, карточка price_byn={card_raw!r}, currency={ad.get('currency')!r}, "
            f"price_usd={ad.get('price_usd')!r}; в базе: {base}; итог {price_byn(ad):g} BYN — {ad.get('_price_src') or PRICE_SRC_SEARCH}"
            + note)


def process_ad(ad, fresh_until=None):
    """Разбор + оценка + сообщение. Возвращает (текст, ok_для_статистики) или (None, False), если это не телефон.
    fresh_until — когда объявление перестанет быть свежим: дорогие шаги (карточка, фото, обновление аналогов) пропускаются,
    если на них уже нет времени, — лучше короткая оценка вовремя, чем полная, но опоздавшая."""
    RUN["no_photo"] = RUN["no_refresh"] = False
    RUN["ad_until"] = fresh_until
    try:
        for key_ in ("_price_conflict", "_price_src", "_price_unverified", "_price_card_invalid", "_price_raw_search", "_price_raw_card"):
            ad.pop(key_, None)
        if not (RUN["deadline"] and time.time() > RUN["deadline"]) and _remaining(fresh_until) > 15:
            card = fetch_card(ad["ad_id"])  # всегда: и описание, и цена со страницы (а не из возможно отставшей выдачи)
            if card:
                apply_card(ad, card)
            time.sleep(KUFAR_PAUSE)
        if ad.get("_price_src") != PRICE_SRC_CARD:
            ad["_price_unverified"] = True  # карточку не получили (сбой, лимит или не хватило времени): цена только из поиска
        log(price_diag(ad, _mdb_ads().get(str(ad.get("ad_id")))))
        RUN["no_photo"] = _remaining(fresh_until) < 40
        RUN["no_refresh"] = _remaining(fresh_until) < 20
        facts = analyze_ad(ad)
        if not facts["is_phone"]:
            return None, False
        ap = appraise(ad, facts)
        mdb_observe(ad, facts=facts, checked=True)
        mdb_appraisal(ad["ad_id"], facts, ap)
        return build_message(ad, facts, ap), not is_suspicious(facts, ap)
    except Exception as e:  # оценка не должна терять объявление: шлём в прежнем формате
        log("Ошибка оценки, шлю обычное сообщение:", e)
        return format_ad(ad, ""), True
    finally:
        RUN["no_photo"] = RUN["no_refresh"] = False
        RUN["ad_until"] = None


def candidate_reason(ad_id, ad, seen, prev_lt, now=None):
    """Почему объявление НЕ кандидат на уведомление ('' — кандидат). Порядок: уже отправлено → дата → поднятие."""
    if ad_id in seen or mdb_notified(ad_id):
        return "notified"
    ok, reason, _age, lt = fresh_status(ad, now)
    if not ok:
        return reason
    if prev_lt is not None and lt - prev_lt > 60:
        return "republished"  # база уже видела это объявление с более ранней датой: дату обновили, публикация не новая
    ok, reason = originality(ad_id, lt, STATE["marks"])
    return "" if ok else reason


def log_skips(why):
    """Журнал: почему объявления не отправлены. Обычные причины — числом, необычные (нет даты, поднятие…) — с номерами."""
    if not why:
        return
    parts = []
    for reason in ("old", "notified", "no_date", "bad_date", "future", "bumped", "republished", "unconfirmed", "expired"):
        ids = why.get(reason) or []
        if not ids:
            continue
        txt = f"{SKIP_RU[reason]}: {len(ids)}"
        if reason not in ("old", "notified"):
            txt += " (" + ", ".join(str(i) for i in ids[:10]) + ("…" if len(ids) > 10 else "") + ")"
        parts.append(txt)
    log("Не отправляю — " + "; ".join(parts))


def cycle(seen, first_run):
    """Один проход. Возвращает (сколько запросов прошло, сколько запускали).
    Два независимых процесса: (1) всё увиденное — в базу рынка и метки номеров; (2) уведомления — только свежие публикации
    (fresh_status + originality), с повторной проверкой возраста прямо перед отправкой."""
    t0 = time.time()
    RUN.update(deadline=t0 + RUN_BUDGET_S, cards=0, card_fails=0, img_fails=0, db_comps=0)
    _MARKET_REFRESHES["n"] = 0
    llm_reset()
    queries = list(QUERIES) + pick_extra(t0)
    found, ok_queries = {}, 0
    for q in queries:
        try:
            ads = [a for a in fetch_fresh(q, t0) if isinstance(a, dict) and a.get("ad_id") is not None]
        except Exception as e:
            log(f"Ошибка Куфара ({q}):", e)
            continue
        ok_queries += 1
        for a in ads:
            try:
                aid = int(a["ad_id"])
            except (TypeError, ValueError):
                continue
            found.setdefault(aid, a)  # одно объявление в нескольких запросах или на соседних страницах — одна запись
            seen.touch(aid)
        time.sleep(KUFAR_PAUSE)
    marks_add(STATE["marks"], found.values())
    if ok_queries and not marks_cover(STATE["marks"], time.time()):
        seed_marks(time.time())  # первый запуск / долгий простой: дочитываем выдачу ради опорных меток (без уведомлений)
    STATE["baseline"] = sorted(set(STATE["baseline"]) | set(queries))  # для совместимости со старым форматом seen.json
    now = time.time()
    cands, why = {}, {}
    for aid, ad in found.items():
        try:
            if not basic_filter(ad):  # не телефон (чехол, планшет и т.п.): в базу не пишем, повторная проверка стоит дёшево
                continue
            prev_lt = mdb_first_lt(aid)
            mdb_observe(ad, now=now)
            if first_run:  # всё, что уже висит в выдаче в момент первого запуска, — не новинки этого бота: не рассылаем
                seen.add(aid)  # (в seen.json, а не только в базе: так защита переживёт и повреждение базы)
                continue
            reason = candidate_reason(aid, ad, seen, prev_lt, now)
        except Exception as e:  # одно «ядовитое» объявление не роняет запуск
            log("Пропускаю странное объявление:", aid, e)
            continue
        if reason:
            why.setdefault(reason, []).append(aid)
        else:
            cands[aid] = ad
    if first_run:
        log(f"Первый запуск: запомнил {len(found)} объявлений (подходящие — как уже существующие), уведомлений не шлю")
        return ok_queries, len(queries)
    # очередь повторов (Telegram не принял): те же правила — устаревшее не отправляем никогда
    for aid, ad in pending_ads(seen).items():
        if aid in cands:
            continue
        if aid in found:  # уже проверено по свежей выдаче выше и не прошло — из очереди убираем
            unstash(aid)
            continue
        reason = candidate_reason(aid, ad, seen, None, now)
        if reason:
            why.setdefault("expired" if reason == "old" else reason, []).append(aid)
            unstash(aid)
            if reason == "old":
                mdb_note(aid, "expired", "из очереди повторов: старше допустимого возраста")
        else:
            cands[aid] = ad
    log_skips(why)
    if cands:
        log(f"Свежих публикаций для уведомления: {len(cands)}")
    # сначала те, у кого меньше всего времени до конца «окна свежести»
    todo = sorted(cands.items(), key=lambda kv: parse_list_time(kv[1].get("list_time")) or 0)
    for aid, ad in todo:
        ok, reason, age, lt = fresh_status(ad)
        if not ok:  # пока ждали своей очереди, объявление устарело
            log(f"Не отправляю {aid}: {SKIP_RU.get(reason, reason)}" + (f" ({age:.0f} с)" if age is not None else ""))
            mdb_note(aid, "expired", f"устарело до разбора: {SKIP_RU.get(reason, reason)}")
            seen.add(aid)
            unstash(aid)
            continue
        if time.time() > RUN["deadline"]:
            log("Время запуска вышло — остальное в очередь (уйдёт, только если ещё будет свежим)")
            try:
                if basic_filter(ad):
                    stash(aid, ad)
            except Exception:
                pass
            continue
        try:
            text, ok_stat = process_ad(ad, fresh_until=lt + FRESH_MAX_AGE_S)
            record_ad(ad, ok_stat)
        except Exception as e:
            log("Ошибка обработки объявления, пропускаю его:", aid, e)
            seen.add(aid)
            unstash(aid)
            mdb_note(aid, "failed", "ошибка обработки")
            continue
        if text is None:
            log("Не телефон (по мнению нейросети), пропускаю:", ad.get("subject"))
            seen.add(aid)
            unstash(aid)
            continue
        ok, reason, age, _lt = fresh_before_send(ad)  # последняя проверка прямо перед отправкой: 0 ≤ возраст ≤ 300 с
        if not ok:
            log(f"Не отправляю {aid}: к моменту отправки {SKIP_RU.get(reason, reason)}" + (f" ({age:.0f} с)" if age is not None else ""))
            mdb_note(aid, "expired", f"к моменту отправки: {SKIP_RU.get(reason, reason)}")
            seen.add(aid)
            unstash(aid)
            continue
        result = send_ad(text)
        if result == "retry":
            stash(aid, ad)  # не помечаем отправленным; повтор будет, только если объявление ещё свежее
            mdb_note(aid, "failed", "Telegram не принял сообщение")
            continue
        seen.add(aid)
        unstash(aid)
        if result == "sent":
            mdb_note(aid, "sent")
            log(f"Отправил: {ad.get('subject')} (возраст {age:.0f} с)")
            save_seen(seen)  # контрольная точка: оборванный запуск не пришлёт то же самое второй раз
            mdb_save()
            time.sleep(SEND_PAUSE)  # Telegram не любит очереди из десятков сообщений подряд
        else:
            mdb_note(aid, "failed", "Telegram отклонил текст сообщения")
    return ok_queries, len(queries)


def dry_run():
    """Тестовый запуск: реальные запросы к Куфару, разбор и оценка, но в Telegram ничего не уходит, seen.json и база не меняются.
    Показывает до DRY_LIMIT подходящих объявлений из выдачи (вне зависимости от свежести — чтобы было что посмотреть) и для
    каждого пишет, ушло бы оно в настоящем запуске и почему. В конце — сводка по свежести всей выдачи."""
    seen = load_seen() or Seen()  # кеш аналогов и метки номеров из seen.json, только чтение
    mdb_load()
    t0 = time.time()
    RUN.update(deadline=t0 + RUN_BUDGET_S, cards=0, card_fails=0, img_fails=0, db_comps=0)
    _MARKET_REFRESHES["n"] = 0
    llm_reset()
    log(f"ТЕСТОВЫЙ ЗАПУСК: покажу до {DRY_LIMIT} подходящих объявлений. В Telegram ничего не уходит, seen.json и база не меняются.")
    shown, ok_queries, found = set(), 0, {}
    for q in list(QUERIES) + pick_extra(t0):
        try:
            ads = fetch_fresh(q, t0)
        except Exception as e:
            log(f"Ошибка Куфара ({q}):", e)
            continue
        ok_queries += 1
        for a in ads:
            if isinstance(a, dict) and a.get("ad_id") is not None:
                found.setdefault(a["ad_id"], a)
        time.sleep(KUFAR_PAUSE)
    marks_add(STATE["marks"], found.values())
    why = {}
    for aid, ad in found.items():
        try:
            if not basic_filter(ad):
                continue
            reason = candidate_reason(int(aid), ad, seen, mdb_first_lt(aid))
        except Exception as e:
            log("Ошибка проверки объявления:", aid, e)
            continue
        why.setdefault(reason or "fresh", []).append(aid)
        if len(shown) >= DRY_LIMIT:
            continue
        try:
            text, _ok = process_ad(ad)
        except Exception as e:
            log("Ошибка обработки объявления:", e)
            continue
        if text is not None:
            shown.add(aid)
            _ok_f, _r, age, _lt = fresh_status(ad)
            log(f"Объявление {aid}: list_time={ad.get('list_time')!r}, возраст "
                f"{'—' if age is None else f'{age:.0f} с'} → " + ("УШЛО БЫ в Telegram" if not reason else f"не ушло бы: {SKIP_RU.get(reason, reason)}"))
            tg_send(text)
    llm_log_summary()
    if not ok_queries:
        sys.exit("Куфар не ответил ни на один запрос")
    log("Свежесть подходящих объявлений в выдаче: " + "; ".join(
        f"{'свежие (ушли бы)' if r == 'fresh' else SKIP_RU.get(r, r)} — {len(v)}" for r, v in sorted(why.items())))
    log(f"Тестовый запуск закончен: показано объявлений — {len(shown)}")


LOCK_FILE = Path(__file__).with_name(".kufar_bot.lock")
_LOCK = {}


def acquire_lock():
    """Не даёт двум копиям бота работать одновременно на одной машине (основная защита в GitHub Actions — concurrency
    в workflow). True — можно работать. Без fcntl (Windows) полагаемся только на workflow."""
    try:
        import fcntl
    except ImportError:
        return True
    try:
        fh = open(LOCK_FILE, "w")
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    _LOCK["fh"] = fh
    return True


NOTICE_TEXT = (
    "🔄 Бот обновлён. Теперь в Telegram приходят только объявления, опубликованные не больше 5 минут назад: дата проверяется "
    "перед отправкой ещё раз, а поднятые старые объявления отсеиваются. Сообщения стали короткими: рынок, максимум покупки, "
    "прибыль и вердикт. Цены аналогов — это цены объявлений, а не сделок; бот копит их в базе рынка (market_history.json)."
)


def main():
    if DRY_RUN:
        return dry_run()
    if not TG_TOKEN:
        sys.exit("Нужна переменная TG_TOKEN (токен от @BotFather)")
    if "--get-chat-id" in sys.argv:
        return get_chat_id()
    if not TG_CHAT_ID:
        sys.exit("Нужна переменная TG_CHAT_ID (узнать: python kufar_bot.py --get-chat-id)")

    if "--report" in sys.argv:
        load_seen()  # заполняет HISTORY
        mdb_load()   # отчёт берёт цены и из базы рынка
        send_report()
        llm_log_summary()
        return

    if not acquire_lock():
        log("Другая копия бота уже работает — этот запуск ничего не делает (защита от параллельных запусков)")
        return

    seen = load_seen()
    first_run = seen is None
    seen = seen or Seen()
    mdb_load()

    if "--once" in sys.argv:
        # Один проход и выход — для запуска по расписанию (GitHub Actions)
        ok_queries, total = cycle(seen, first_run)
        llm_log_summary()
        # Куфар не ответил (на первом запуске нужны все запросы) — состояние не трогаем и падаем,
        # иначе в следующий раз все старые объявления придут как новые
        if not ok_queries or (first_run and ok_queries < total):
            sys.exit("Куфар ответил не на все запросы — состояние не сохраняю")
        if first_run:
            tg_send("✅ Мониторинг Куфара запущен (по расписанию): " + ", ".join(QUERIES)
                    + f". Приходят только публикации не старше {FRESH_MAX_AGE_S / 60:g} мин.")
            STATE["notice"] = NOTICE_VERSION
        elif STATE["notice"] < NOTICE_VERSION:
            try:
                tg_send(NOTICE_TEXT)
                STATE["notice"] = NOTICE_VERSION
            except Exception as e:
                log("Не отправилось уведомление об обновлении, попробую позже:", e)
        save_seen(seen)
        mdb_save()
        return

    tg_send("✅ Мониторинг Куфара запущен: " + ", ".join(QUERIES))
    STATE["notice"] = NOTICE_VERSION
    log("Запущено. Запросы:", QUERIES, "| нейросеть:", "вкл" if (GEMINI_KEY or ANTHROPIC_KEY) else "выкл")

    while True:
        try:
            cycle(seen, first_run)
            llm_log_summary(always=False)
            first_run = False
            save_seen(seen)
            mdb_save()
        except Exception as e:
            log("Ошибка в цикле, продолжаю:", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
