"""Запускает kufar_bot.py с подменённой сетью и часами (вызывается из test_cycle.py). Параметры — через переменные окружения.
CLOCK: «сейчас» для бота (unix-время; по умолчанию настоящее). Подменяется time.time — ни одного реального ожидания часов нет.
ADS: список [id, subject] или словарей {id, subject, price, desc, cond, region, company, age | lt | list_time}; отдаётся на
     каждый поисковый запрос. age — сколько секунд назад опубликовано (по умолчанию 60), lt — абсолютное unix-время,
     list_time — сырое значение как есть (в т.ч. None, мусор, миллисекунды).
REF: "1" (по умолчанию) — в каждую выдачу добавляется опорное объявление (чехол, номер REF_ID=1000, опубликован 45 мин назад):
     по нему бот подтверждает, что объявления с номерами больше 1000 — новые публикации, а не поднятые старые.
MARKET: {поисковый запрос: список объявлений} — переопределяет ADS для этого запроса. RAW: «сырые» объявления, добавляются как есть.
PAGES: {запрос: [[страница 1], [страница 2], ...]} — постраничная выдача с курсором.
FAIL: запросы, на которые Куфар отвечает 503 ("*" = на все). FLAKY: {запрос: [коды по порядку, "conn" = обрыв связи]} до первого успеха.
BODIES: {id: описание} для карточек; CARDS: {id: {body, price_byn, list_time}}; CARD: ok | 500. TG: ok | 500 | 400parse | 400chat | 429once.
SEND_DELAY: на сколько секунд «сдвигаются часы» при каждом вызове Telegram (имитация долгой отправки).
CARD_DELAY: то же для запроса карточки (имитация долгого разбора объявления)."""
import json
import os
import sys
import time
from datetime import datetime, timezone

CLOCK = [float(os.environ.get("CLOCK") or time.time())]
time.time = lambda: CLOCK[0]  # до импорта бота
_real_sleep = time.sleep


def fake_sleep(s):
    CLOCK[0] += max(0.0, float(s))  # время идёт, а реально не ждём


time.sleep = fake_sleep
sys.path.insert(0, os.environ["BOT_DIR"])
sys.argv = ["kufar_bot.py"] + json.loads(os.environ.get("ARGV", '["--once"]'))  # до импорта: бот читает флаги при загрузке
import requests  # noqa: E402
import kufar_bot as k  # noqa: E402

ADS = json.loads(os.environ["ADS"])
FAIL = set(json.loads(os.environ["FAIL"]))
TG = os.environ.get("TG", "ok")
CARD = os.environ.get("CARD", "ok")
MARKET = json.loads(os.environ.get("MARKET", "{}"))
BODIES = json.loads(os.environ.get("BODIES", "{}"))
CARDS = json.loads(os.environ.get("CARDS", "{}"))
RAW = json.loads(os.environ.get("RAW", "[]"))
FLAKY = json.loads(os.environ.get("FLAKY", "{}"))
PAGES = json.loads(os.environ.get("PAGES", "{}"))
REF = os.environ.get("REF", "1") == "1"
REF_ID = int(os.environ.get("REF_ID", "1000"))
SEND_DELAY = float(os.environ.get("SEND_DELAY", "0"))
CARD_DELAY = float(os.environ.get("CARD_DELAY", "0"))
NOW0 = CLOCK[0]
sent, plain, gets = [], [], []
flaky_pos, tg_calls = {}, [0]


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class R:
    def __init__(self, data=None, code=200, headers=None):
        self.data, self.code, self.headers = data, code, headers or {}
        self.status_code = code
        self.response = self

    def raise_for_status(self):
        if self.code >= 400:
            e = requests.HTTPError(str(self.code))
            e.response = self
            raise e

    def json(self):
        return self.data


def make_ad(a):
    if not isinstance(a, dict):
        a = {"id": a[0], "subject": a[1]}
    params = [{"p": "condition", "vl": a.get("cond", "Б/у")}, {"p": "region", "vl": a.get("region", "Минск")}]
    if "list_time" in a:
        lt = a["list_time"]
    elif "lt" in a:
        lt = iso(a["lt"])
    else:
        lt = iso(NOW0 - a.get("age", 60))
    d = {"ad_id": a["id"], "type": "sell", "company_ad": a.get("company", False), "price_byn": str(a.get("price", 150) * 100),
         "price_usd": "5000", "subject": a["subject"], "ad_link": f"https://www.kufar.by/item/{a['id']}",
         "ad_parameters": params, "body": a.get("desc"), "body_short": None, "currency": "BYR"}
    if lt is not None or "list_time" in a:
        d["list_time"] = lt
    return d


def ref_ad():
    return {"ad_id": REF_ID, "type": "sell", "subject": "Чехол для iPhone", "price_byn": "1000", "ad_parameters": [],
            "ad_link": f"https://www.kufar.by/item/{REF_ID}", "list_time": iso(NOW0 - 2700)}


def fake_get(url, params=None, **kw):
    if "/item/" in url:
        i = int(url.split("/item/")[1].split("/")[0])
        gets.append(f"item:{i}")
        CLOCK[0] += CARD_DELAY
        if CARD == "500":
            return R(code=500)
        if i == 9404:
            return R(code=404)
        card = dict(CARDS.get(str(i)) or {})
        card.setdefault("body", BODIES.get(str(i)))
        return R({"result": card})
    q = params["query"]
    cur = params.get("cursor")
    gets.append(f"{q}|{params['size']}" + (f"|{cur}" if cur else ""))
    plan, pos = FLAKY.get(q), flaky_pos.get(q, 0)
    if plan and pos < len(plan):
        flaky_pos[q] = pos + 1
        if plan[pos] == "conn":
            raise requests.ConnectionError("обрыв связи")
        return R(code=plan[pos], headers={"Retry-After": "1"} if plan[pos] == 429 else {})
    if "*" in FAIL or q in FAIL:
        return R(code=503)
    if q in PAGES:
        n = int(cur or 0)
        pages = PAGES[q]
        data = {"ads": [make_ad(a) for a in pages[n]]}
        if n + 1 < len(pages):
            data["pagination"] = {"pages": [{"label": "self", "num": n + 1, "token": None},
                                            {"label": "next", "num": n + 2, "token": str(n + 1)}]}
        return R(data)
    return R({"ads": [make_ad(a) for a in MARKET.get(q, ADS)] + RAW + ([ref_ad()] if REF else [])})


def fake_post(url, **kw):
    if "api.telegram.org" not in url:
        return R(code=500)  # нейросети в тестах не нужны
    body = kw["json"]
    tg_calls[0] += 1
    CLOCK[0] += SEND_DELAY
    if TG == "500":
        return R(code=500)
    if TG == "429once" and tg_calls[0] == 1:
        return R({"ok": False, "parameters": {"retry_after": 1}}, 429)
    if TG == "400chat":
        return R({"ok": False, "description": "Bad Request: chat not found"}, 400)
    if TG == "400parse" and body.get("parse_mode"):
        return R({"ok": False, "description": "Bad Request: can't parse entities: Unsupported start tag"}, 400)
    (sent if body.get("parse_mode") else plain).append(body["text"])
    return R()


requests.get, requests.post = fake_get, fake_post
code = 0
try:
    k.main()
except SystemExit as e:
    code = 1 if e.code else 0
print(json.dumps({"exit": code, "sent": sent, "plain": plain, "gets": gets, "tg_calls": tg_calls[0], "clock": CLOCK[0]}, ensure_ascii=False))
