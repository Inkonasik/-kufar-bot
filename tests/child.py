"""Запускает kufar_bot.py с подменённой сетью (вызывается из test_cycle.py). Параметры — через переменные окружения.
ADS: список [id, subject] или словарей {id, subject, price, desc, cond, region, company}; отдаётся на каждый поисковый запрос.
MARKET: {поисковый запрос: список объявлений} — переопределяет ADS для этого запроса. RAW: «сырые» объявления, добавляются как есть.
FAIL: запросы, на которые Куфар отвечает 503 ("*" = на все). FLAKY: {запрос: [коды по порядку, "conn" = обрыв связи]} до первого успеха.
BODIES: {id: описание} для карточек; CARD: ok | 500. TG: ok | 500 | 400parse | 400chat | 429once."""
import json
import os
import sys

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
RAW = json.loads(os.environ.get("RAW", "[]"))
FLAKY = json.loads(os.environ.get("FLAKY", "{}"))
ARGV = json.loads(os.environ.get("ARGV", '["--once"]'))
sent, plain, gets = [], [], []
flaky_pos, tg_calls = {}, [0]


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
    d = {"ad_id": a["id"], "type": "sell", "company_ad": a.get("company", False), "price_byn": str(a.get("price", 150) * 100),
         "price_usd": "5000", "subject": a["subject"], "ad_link": f"https://www.kufar.by/item/{a['id']}",
         "ad_parameters": params, "body": a.get("desc"), "body_short": None}
    return d


def fake_get(url, params=None, **kw):
    if "/item/" in url:
        i = int(url.split("/item/")[1].split("/")[0])
        gets.append(f"item:{i}")
        if CARD == "500":
            return R(code=500)
        return R(code=404) if i == 9404 else R({"result": {"body": BODIES.get(str(i), None)}})
    q = params["query"]
    gets.append(f"{q}|{params['size']}")
    plan, pos = FLAKY.get(q), flaky_pos.get(q, 0)
    if plan and pos < len(plan):
        flaky_pos[q] = pos + 1
        if plan[pos] == "conn":
            raise requests.ConnectionError("обрыв связи")
        return R(code=plan[pos], headers={"Retry-After": "1"} if plan[pos] == 429 else {})
    if "*" in FAIL or q in FAIL:
        return R(code=503)
    return R({"ads": [make_ad(a) for a in MARKET.get(q, ADS)] + RAW})


def fake_post(url, **kw):
    if "api.telegram.org" not in url:
        return R(code=500)  # нейросети в тестах не нужны
    body = kw["json"]
    tg_calls[0] += 1
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
print(json.dumps({"exit": code, "sent": sent, "plain": plain, "gets": gets, "tg_calls": tg_calls[0]}, ensure_ascii=False))
