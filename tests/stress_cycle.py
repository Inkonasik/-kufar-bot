"""Стресс-тест основного цикла на модели «мира» Куфара (всё подменено: сеть, Telegram, часы; ни одного внешнего запроса).
Мир: номера объявлений растут со временем, часть новинок публикуется с задержкой после выдачи номера (черновик/модерация),
старые объявления регулярно ПОДНИМАЮТ (list_time = сейчас), одно объявление находится несколькими запросами, выдача
постраничная, цена в карточке иногда отличается от выдачи (продавец изменил цену), Telegram иногда не принимает сообщение,
запуски идут каждые 5 минут с разбросом ±2 минуты.
Проверяется на КАЖДОЙ отправке: (1) с момента первой публикации прошло 0…300 с; (2) это не поднятое старое объявление;
(3) одно объявление не приходит дважды; (4) цена в сообщении — цена страницы (карточки) на момент отправки."""
import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fresh_dir  # noqa: E402

SEED = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 7
D = fresh_dir()
sys.path.insert(0, str(D))
sys.argv = ["kufar_bot.py", "--once"]
import kufar_bot as k  # noqa: E402

random.seed(SEED)
k.log = lambda *a: None
CLOCK = [1_793_196_000.0]
time.time = lambda: CLOCK[0]
time.sleep = lambda s: CLOCK.__setitem__(0, CLOCK[0] + max(0.0, float(s)))
k.SEEN_FILE, k.MARKET_DB_FILE = D / "seen.json", D / "market_history.json"
k.KUFAR_PAUSE = k.SEND_PAUSE = 0.0
k.QUERIES = ["iphone", "samsung", "айфон"]
k.EXTRA_QUERIES = ["iphone 8", "galaxy s9", "apple"]
bad = []


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


MODELS = [("iPhone 8 64gb", "iphone"), ("iPhone X 64gb", "iphone"), ("iPhone 11 128gb", "iphone"), ("iPhone 7 32gb", "iphone"),
          ("Samsung Galaxy S9 64gb", "samsung"), ("Samsung Galaxy S8 64gb", "samsung")]


class World:
    def __init__(self, t0):
        self.t0 = t0
        self.ads = {}  # id -> {"subject","price","card_price","created","published","list_time","bumped"}
        self.next_id = 1_091_000_000
        self.pending_pub = []  # (время публикации, id): номер уже выдан, объявление ещё не опубликовано
        self.last_t = t0 - 3 * 86400
        self.advance(t0)  # предыстория: три дня объявлений

    def _new(self, t):
        self.next_id += random.randint(30, 300)
        subj, fam = random.choice(MODELS)
        price = random.choice([90, 120, 150, 180, 200, 250, 300, 400, 600])
        delay = random.choice([0, 0, 0, 5, 20, 60, 240]) if random.random() > 0.03 else random.choice([900, 3000])
        self.ads[self.next_id] = {"subject": subj, "fam": fam, "price": price, "card_price": price, "created": t, "n_changes": 0,
                                  "published": None, "list_time": None, "bumped": False}
        self.pending_pub.append((t + delay, self.next_id))

    def advance(self, t):
        step = 20.0
        x = self.last_t
        while x < t:
            x = min(t, x + step)
            if random.random() < 0.45:
                self._new(x)
            for pub_t, i in [p for p in self.pending_pub if p[0] <= x]:
                self.pending_pub.remove((pub_t, i))
                a = self.ads[i]
                a["published"] = a["list_time"] = pub_t
            if random.random() < 0.08:  # поднятие старого объявления (старше суток)
                old = [i for i, a in self.ads.items() if a["published"] and x - a["created"] > 86400]
                if old:
                    i = random.choice(old)
                    self.ads[i]["list_time"], self.ads[i]["bumped"] = x, True
            if random.random() < 0.05:  # продавец изменил цену старого объявления: карточка новая, выдача отстаёт
                live = [i for i, a in self.ads.items() if a["published"]]
                if live:
                    i = random.choice(live)
                    new_p = random.choice([90, 100, 130, 300])
                    self.ads[i]["n_changes"] += new_p != self.ads[i]["card_price"]
                    self.ads[i]["card_price"] = new_p
            if random.random() < 0.3:  # …и свежего, только что опубликованного (тот самый случай «на странице 100, бот пишет 300»)
                recent = [i for i, a in self.ads.items() if a["published"] and x - a["published"] < 300]
                if recent:
                    i = random.choice(recent)
                    new_p = random.choice([p_ for p_ in (100, 130, 300) if p_ != self.ads[i]["price"]])
                    self.ads[i]["n_changes"] += new_p != self.ads[i]["card_price"]
                    self.ads[i]["card_price"] = new_p
        self.last_t = t

    def listing(self, query):
        q = query.lower()
        fam = "samsung" if any(w in q for w in ("samsung", "galaxy")) else "iphone"
        out = [(i, a) for i, a in self.ads.items() if a["list_time"] and a["fam"] == fam
               and (not re.search(r"\d", q) or any(tok in a["subject"].lower() for tok in q.split() if tok.isalnum() and tok not in ("iphone", "galaxy")))]
        out.sort(key=lambda ia: -ia[1]["list_time"])
        return out

    def ad_json(self, i, a, card=False):
        price = a["card_price"] if card else a["price"]
        return {"ad_id": i, "type": "sell", "subject": a["subject"], "price_byn": str(price * 100), "price_usd": str(price * 34),
                "currency": "BYR", "list_time": iso(a["list_time"]), "ad_link": f"https://www.kufar.by/item/{i}",
                "ad_parameters": [{"p": "condition", "vl": "Б/у"}, {"p": "region", "vl": "Минск"}],
                **({"body": "Всё работает"} if card else {"body": None})}


W = World(CLOCK[0])


def fake_fetch(query, size=30, cursor=None):
    rows = W.listing(query)
    page = int(cursor or 0)
    chunk = rows[page * size:(page + 1) * size]
    k._NEXT[query] = str(page + 1) if (page + 1) * size < len(rows) else None
    return [W.ad_json(i, a) for i, a in chunk]


CARD_FAIL = [False]


def fake_card(ad_id):
    CLOCK[0] += random.choice([0, 0, 0, 1, 5, 25, 60])  # медленный ответ карточки: разбор иногда съедает окно свежести
    a = W.ads.get(int(ad_id))
    if not a or CARD_FAIL[0]:
        return {}
    card = W.ad_json(int(ad_id), a, card=True)
    if random.random() < 0.05:  # карточка отдала недействительную цену: бот должен оставить цену выдачи и пометить неопределённость
        card["price_byn"] = random.choice(["0", "-500", "abc", None, ""])
        CARD_STATE[int(ad_id)] = "invalid"
    else:
        CARD_STATE[int(ad_id)] = "ok"
    return card


CARD_STATE = {}  # номер -> чем ответила карточка в последний раз (ok / invalid)


sent_log, tg_fail = [], [False]


def fake_tg(text, parse_mode="HTML"):
    CLOCK[0] += random.choice([0.2, 0.5, 1.0, 3.0])
    if tg_fail[0]:
        e = k.requests.HTTPError("500")
        e.response = type("R", (), {"status_code": 500, "json": lambda self: {}})()
        raise e
    m = re.search(r"kufar\.by/item/(\d+)", text)
    if m:
        sent_log.append((int(m.group(1)), CLOCK[0], text))


k.fetch, k.fetch_card, k.tg_send = fake_fetch, fake_card, fake_tg
runs, checked, diverged, unverified_n, invalid_n = 72, 0, 0, 0, 0  # ~6 часов работы
first = True
for r in range(runs):
    CLOCK[0] += 300 + random.uniform(-120, 120)
    W.advance(CLOCK[0])
    tg_fail[0] = random.random() < 0.1
    CARD_FAIL[0] = random.random() < 0.1
    seen = k.load_seen()
    first_run = seen is None
    seen = seen or k.Seen()
    k.mdb_load()
    before = len(sent_log)
    k.cycle(seen, first_run)
    k.save_seen(seen)
    k.mdb_save()
    for ad_id, t_sent, text in sent_log[before:]:
        checked += 1
        a = W.ads[ad_id]
        age_orig = t_sent - a["published"]
        if a["bumped"] and a["list_time"] != a["published"]:
            bad.append(("отправлено поднятое старое объявление", ad_id, a))
        if not (0 <= age_orig <= 300 + 3.0):  # +3 с: время самой отправки (fake_tg двигает часы после проверки)
            bad.append(("возраст от первой публикации вне 0…300 с", ad_id, round(age_orig, 1)))
        m = re.search(r"Цена продавца: ([\d ]+) BYN", text)
        unverified = "не сверены с карточкой" in text  # карточку не получили (сбой / не хватило времени) — так и сказано
        diverged += a["card_price"] != a["price"] and not unverified
        if CARD_STATE.get(ad_id) == "invalid" and not unverified:
            invalid_n += 1
            if not m or int(m.group(1).replace(" ", "")) != a["price"] or "нет действительной цены" not in text:
                bad.append(("недействительная цена карточки затёрла цену выдачи или не отмечена", ad_id, text[:120]))
            if "<b>ВЫГОДНО</b>" in text:
                bad.append(("цена не подтверждена карточкой, а вывод уверенный", ad_id))
            continue
        if unverified:
            unverified_n += 1
            if re.search(r"<b>ВЫГОДНО</b>", text) or "Уверенность: низкая" not in text and "Уверенность:" in text:
                bad.append(("непроверенная цена, а вывод уверенный", ad_id))
        elif m and int(m.group(1).replace(" ", "")) != a["card_price"]:
            bad.append(("цена в сообщении не равна цене страницы", ad_id, m.group(1), a["card_price"]))
        elif a["card_price"] != a["price"] and "⚠️ Цена в поиске" not in text:
            bad.append(("расхождение цены выдачи и страницы не показано", ad_id))
ids = [i for i, _t, _x in sent_log]
dups = {i for i in ids if ids.count(i) > 1}
if dups:
    bad.append(("одно объявление пришло дважды", sorted(dups)[:5]))
genuine = [i for i, a in W.ads.items() if a["published"] and W.t0 < a["published"] and not a["bumped"]]
coverage = len(set(ids)) / max(1, len(genuine))
db = json.loads(k.MARKET_DB_FILE.read_text())
false_changes = 0
for id_, rec in db["ads"].items():
    h = rec.get("price_hist") or []
    a = W.ads.get(int(id_))
    if any(x[1] <= 0 for x in h):
        bad.append(("в истории цены ноль или отрицательная цена", id_, h))
    if sum(1 for x in h if x[2] == "search") > 1:  # цена в выдаче в этом мире не меняется никогда
        bad.append(("ложное изменение цены выдачи", id_, h))
    if a and a["n_changes"] == 0 and "price_changed" in (rec.get("flags") or []):
        false_changes += 1
        bad.append(("price_changed без настоящего изменения цены", id_, h))
for b in bad[:10]:
    if len(b) > 1 and "цена" in b[0]:
        print("   текст:", [t for i_, _t, t in sent_log if i_ == b[1]][0].replace("\n", " | ")[:400])
    print("FAIL", *b)
print(f"зерно {SEED}: запусков: {runs}, отправлено: {len(sent_log)} (проверено {checked}), поднятий в мире: {sum(a['bumped'] for a in W.ads.values())}, "
      f"из них с расхождением цены выдачи и страницы: {diverged}, без карточки (честно «не сверено»): {unverified_n}, с недействительной ценой в карточке: {invalid_n}, новых публикаций за время работы: {len(genuine)}, доля отправленных: {coverage:.0%}, записей в базе: {len(db['ads'])}")
print("итого ошибок (стресс):", len(bad))
sys.exit(1 if bad or not sent_log else 0)
