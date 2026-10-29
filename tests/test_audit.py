"""Аудит базы рынка: 15 сценариев из задания «Финальный аудит». Без сети, Telegram и нейросети; часы подменены.
Части 1–10 — внутри одного процесса (функции бота напрямую). Части 11–15 — настоящие отдельные запуски бота (tests/child.py),
которые общаются ТОЛЬКО через файлы seen.json / market_history.json, как два запуска GitHub Actions; часть 12 — настоящий git:
«удалённый» репозиторий, два клона и шаг сохранения, взятый как есть из .github/workflows/kufar.yml.
Живые seen.json и market_history.json репозитория не читаются и не меняются: всё во временных папках."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BOT, HERE, fresh_dir  # noqa: E402

REPO = HERE.parent
LIVE = {f: (REPO / f) for f in ("seen.json", "market_history.json", "market_history.backup.json")}
LIVE_HASH = {f: hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for f, p in LIVE.items()}

D = fresh_dir()
sys.path.insert(0, str(D))
sys.argv = ["kufar_bot.py", "--once"]
import kufar_bot as k  # noqa: E402

LOGS = []
k.log = lambda *a: LOGS.append(" ".join(str(x) for x in a))
T0 = 1_793_196_000.0  # 28.10.2026 14:00 UTC
NOW = [T0]
_real_time = time.time
time.time = lambda: NOW[0]
time.sleep = lambda s: NOW.__setitem__(0, NOW[0] + max(0.0, float(s)))
k.KUFAR_PAUSE = k.SEND_PAUSE = 0.0
k.SEEN_FILE, k.MARKET_DB_FILE, k.MARKET_DB_BACKUP, k.DEALS_FILE = (D / "seen.json", D / "market_history.json",
                                                                   D / "market_history.backup.json", D / "deals.json")
k.fetch_card = lambda i: {}
k.tg_send = lambda text, parse_mode="HTML": (_ for _ in ()).throw(AssertionError("в частях 1–10 Telegram не вызывается"))
bad = 0


def check(name, cond, extra=""):
    global bad
    print(("OK  " if cond else "FAIL"), name, "" if cond else extra)
    bad += 0 if cond else 1


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ad(ad_id, title="iPhone X 64gb", price=200, age=3600, desc="Всё работает, без дефектов", region="Минск", card=True):
    a = {"ad_id": ad_id, "type": "sell", "subject": title, "price_byn": str(int(price * 100)), "price_usd": "0", "currency": "BYR",
         "list_time": iso(NOW[0] - age), "ad_link": f"https://www.kufar.by/item/{ad_id}", "body_short": desc or None,
         "ad_parameters": [{"p": "condition", "vl": "Б/у"}, {"p": "region", "vl": region}]}
    if card:
        a["_price_src"] = k.PRICE_SRC_CARD
    return a


def reset():
    k.mdb_reset()
    k.STATE.update(market={}, baseline=[], pending={}, marks={}, notice=k.NOTICE_VERSION)
    k.HISTORY.clear()
    for f in (k.SEEN_FILE, k.MARKET_DB_FILE, k.MARKET_DB_BACKUP, k.DEALS_FILE):
        if f.exists():
            f.unlink()
    NOW[0] = T0


def reload_db():
    """Как следующий запуск: память пустая, база — только из файла."""
    k.mdb_reset()
    k.STATE["market"] = {}
    return k.mdb_load()


def recs():
    return k._mdb_ads()


# ------------------------------------------------------------------------------------------------------------------
# 1. Первое объявление создаёт одну запись
# ------------------------------------------------------------------------------------------------------------------
reset()
k.mdb_observe(ad(5001, price=200, card=False), now=T0)
k.mdb_save(T0)
reload_db()
r = recs().get("5001")
check("1 первое объявление → ровно одна запись в сохранённом файле", len(recs()) == 1 and r is not None
      and r["first_seen"] == int(T0) and r["price_hist"] == [[int(T0), 200, "search"]] and r["key"] == "iPhone X", r)

# ------------------------------------------------------------------------------------------------------------------
# 2. Повторное обнаружение обновляет запись без дубликата
# ------------------------------------------------------------------------------------------------------------------
for i, dt in enumerate((300, 7 * 3600, 30 * 3600)):
    NOW[0] = T0 + dt
    k.mdb_observe(ad(5001, price=200, card=False), now=NOW[0])
    k.mdb_save(NOW[0])
    reload_db()
r = recs().get("5001")
check("2 три повторных наблюдения (в т.ч. через сохранение/загрузку) → та же одна запись, first_seen прежний, история цены "
      "без повторов, last_seen обновлён", len(recs()) == 1 and r["first_seen"] == int(T0) and len(r["price_hist"]) == 1
      and r["last_seen"] == int(T0 + 30 * 3600), r)

# ------------------------------------------------------------------------------------------------------------------
# 3. Изменение подтверждённой цены сохраняется с корректным временем
# ------------------------------------------------------------------------------------------------------------------
reset()
t1, t2 = T0, T0 + 5 * 3600
k.mdb_observe(ad(5002, price=300), now=t1, checked=True)
k.mdb_observe(ad(5002, price=280), now=t2, checked=True)
k.mdb_save(t2)
reload_db()
r = recs()["5002"]
check("3 цена карточки 300 → 280: два наблюдения с точным временем, одно изменение, флаг price_changed, текущая 280",
      r["price_hist"] == [[int(t1), 300, "card"], [int(t2), 280, "card"]] and k.price_changes(r["price_hist"]) == 1
      and "price_changed" in r.get("flags", []) and r["price_byn"] == 280, r)

# ------------------------------------------------------------------------------------------------------------------
# 4. Расхождение выдачи и карточки само по себе не создаёт изменения цены
# ------------------------------------------------------------------------------------------------------------------
reset()
a = ad(5003, price=300, card=False)  # выдача: 300 (индекс отстал)
k.mdb_observe(a, now=T0)
k.apply_card(a, {"price_byn": "10000"})  # карточка (= страница): 100
k.mdb_observe(a, now=T0 + 60, checked=True)
for j in range(3):  # следующие запуски: выдача по-прежнему 300
    k.mdb_observe(ad(5003, price=300, card=False), now=T0 + 3600 * (j + 1))
k.mdb_save(T0 + 4 * 3600)
reload_db()
r = recs()["5003"]
check("4 выдача 300 / карточка 100, потом ещё 3 раза выдача 300 → изменений цены 0, нет price_changed, расхождение записано "
      "отдельно, текущая цена 100 (страница)", k.price_changes(r["price_hist"]) == 0 and "price_changed" not in r.get("flags", [])
      and r.get("price_conflict", {}).get("card") == 100 and r["price_byn"] == 100 and r["comp"][0] == 100
      and "price_sources_differ" in r.get("flags", []), r)

# ------------------------------------------------------------------------------------------------------------------
# 5. Новая оценка читает ранее сохранённую историю (кеша выдачи нет, Куфар по модели недоступен)
# ------------------------------------------------------------------------------------------------------------------
reset()
PRICES5 = [180, 190, 200, 210, 220, 230]
for i, p in enumerate(PRICES5):
    k.mdb_observe(ad(6000 + i, price=p), now=T0 - 3600)
k.mdb_save(T0 - 3600)
reload_db()


def kufar_down(*a_, **kw):
    raise k.requests.ConnectionError("Куфар недоступен")


k.fetch = kufar_down
target = ad(6100, price=150, age=60)
ap5 = k.appraise(target, k.rule_facts(target))
st5 = ap5.get("stats") or {}
check("5 оценка без кеша и без выдачи: аналоги взяты из сохранённой базы (6 из файла), медиана = медиана сохранённых цен",
      ap5.get("db_comps") == 6 and st5.get("n") == 6 and st5.get("med") == 205, (ap5.get("status"), ap5.get("db_comps"), st5))
check("5в аналоги из базы видели час назад: оценка не помечена устаревшей (возраст ≈ 1 ч)",
      ap5.get("stale") is False and abs((ap5.get("age_h") or 0) - 1.0) < 0.01, (ap5.get("stale"), ap5.get("age_h")))
reset()
for i, p in enumerate(PRICES5):
    k.mdb_observe(ad(6000 + i, price=p), now=T0 - 10 * 3600)
k.mdb_save(T0 - 10 * 3600)
reload_db()
ap5s = k.appraise(target, k.rule_facts(target))
check("5г те же аналоги, но последний раз видели 10 ч назад (больше MARKET_TTL_HOURS=6): оценка помечена устаревшей, "
      "уверенность не выше, чем у свежих", ap5s.get("stale") is True and ap5s.get("db_comps") == 6
      and ["низкая", "средняя", "высокая"].index(ap5s.get("conf") or "низкая") <= ["низкая", "средняя", "высокая"].index(ap5.get("conf") or "низкая"),
      (ap5s.get("stale"), ap5s.get("conf"), ap5.get("conf")))
reset()
ap5b = k.appraise(target, k.rule_facts(target))
check("5б контроль: та же оценка БЕЗ файла базы — аналогов нет (значит, в 5 работала именно база)",
      ap5b.get("status") == "no_market" and not ap5b.get("stats"), ap5b.get("status"))

# ------------------------------------------------------------------------------------------------------------------
# 6. После нового наблюдения статистика обновляется и следующая оценка использует обновлённые данные
#    (в том числе когда у модели есть кеш выдачи со СТАРЫМИ ценами — свежая цена базы важнее)
# ------------------------------------------------------------------------------------------------------------------
reset()
for i, p in enumerate(PRICES5):
    k.mdb_observe(ad(6000 + i, price=p), now=T0 - 3600, checked=True)
k.STATE["market"]["iPhone X"] = {"t": int(T0 - 3600),
                                 "items": [k.comp_item(ad(6000 + i, price=p), "iPhone X") for i, p in enumerate(PRICES5)]}
k.mdb_save(T0 - 3600)
reload_db()
k.STATE["market"]["iPhone X"] = {"t": int(T0 - 3600),
                                 "items": [k.comp_item(ad(6000 + i, price=p), "iPhone X") for i, p in enumerate(PRICES5)]}
ap6a = k.appraise(target, k.rule_facts(target))
ms_a = k.market_stats("iPhone X", 64)
for i in range(6):  # все продавцы снизили цену на 40 BYN — видно по карточкам
    k.mdb_observe(ad(6000 + i, price=PRICES5[i] - 40), now=T0, checked=True)
k.mdb_save(T0)
reload_db()  # следующий запуск
k.STATE["market"]["iPhone X"] = {"t": int(T0 - 3600),  # кеш выдачи этого запуска ещё со старыми ценами (TTL 6 ч не истёк)
                                 "items": [k.comp_item(ad(6000 + i, price=p), "iPhone X") for i, p in enumerate(PRICES5)]}
ap6b = k.appraise(target, k.rule_facts(target))
ms_b = k.market_stats("iPhone X", 64)
qa, qb = (ap6a.get("plan") or {}).get("A") or {}, (ap6b.get("plan") or {}).get("A") or {}
check("6 статистика базы обновилась: медиана активных 205 → 165, у всех 6 зафиксировано снижение",
      ms_a["med"] == 205 and ms_b["med"] == 165 and all(k.price_changes(recs()[str(6000 + i)]["price_hist"]) == 1 for i in range(6)),
      (ms_a["med"], ms_b["med"]))
check("6б следующая оценка использует новые цены, хотя кеш выдачи помнит старые: медиана 205 → 165, быстрая продажа ниже",
      (ap6a.get("stats") or {}).get("med") == 205 and (ap6b.get("stats") or {}).get("med") == 165
      and qa.get("quick") and qb.get("quick") and qb["quick"] < qa["quick"],
      ((ap6a.get("stats") or {}).get("med"), (ap6b.get("stats") or {}).get("med"), qa.get("quick"), qb.get("quick")))

# ------------------------------------------------------------------------------------------------------------------
# 7. Нерелевантные модели, память, состояния и дефекты не попадают в выборку
# ------------------------------------------------------------------------------------------------------------------
reset()
GOOD = [190, 195, 200, 205, 210, 215]
for i, p in enumerate(GOOD):
    k.mdb_observe(ad(7000 + i, price=p), now=T0 - 600)
noise = {
    7100: ad(7100, title="iPhone 11 64gb", price=241),                               # другая модель
    7101: ad(7101, title="iPhone X 256gb", price=243),                               # другая память
    7102: ad(7102, price=247, desc="Разбит экран, не работает Face ID"),            # дефекты
    7103: ad(7103, price=249, desc="На запчасти, не включается"),                   # на запчасти
    7104: ad(7104, title="Куплю iPhone X 64gb", price=251),                          # не продажа
    7105: ad(7105, title="Чехол для iPhone X", price=253),                           # аксессуар
}
for a_ in noise.values():
    k.mdb_observe(a_, now=T0 - 600)
conf_ad = ad(7106, price=257)  # противоречие модели: заголовок iPhone X, в параметрах — iPhone 8
conf_ad["ad_parameters"].append({"p": "phones_model", "vl": "iPhone 8"})
k.mdb_observe(conf_ad, now=T0 - 600)
k.mdb_save(T0 - 600)
reload_db()
k.fetch = kufar_down
t7 = ad(7200, price=170, age=60)
ap7 = k.appraise(t7, k.rule_facts(t7))
used = sorted((ap7.get("stats") or {}).get("prices") or [])
check("7 оценка исправного iPhone X 64: в выборке ровно 6 таких же, ни одной цены от другой модели/памяти/дефектных/"
      "запчастей/«куплю»/чехла/противоречивого", used == GOOD, used)
dfx = ad(7201, price=120, age=60, desc="Разбит экран")
pool_d = k.select_pool(k.market_items("iPhone X")[0], k.rule_facts(dfx), 7201)
check("7б для телефона с дефектом исправные и дефектные не смешиваются: разбитый экран не сравнивается с «на запчасти»",
      7103 not in {it[0] for it in pool_d["items"]}, [it[0] for it in pool_d["items"]])

# ------------------------------------------------------------------------------------------------------------------
# 8. Устаревшие/исчезнувшие объявления исключаются из текущей оценки (но остаются в истории)
# ------------------------------------------------------------------------------------------------------------------
reset()
for i, p in enumerate(GOOD):
    k.mdb_observe(ad(8000 + i, price=p), now=T0 - 600)
for i in range(6):  # давно не видели (4 суток): дорогие 400 BYN
    k.mdb_observe(ad(8100 + i, price=400), now=T0 - 4 * 86400)
k.mdb_save(T0)
reload_db()
k.fetch = kufar_down
t8 = ad(8200, price=170, age=60)
ap8 = k.appraise(t8, k.rule_facts(t8))
hist8 = ap8.get("history") or {}
check("8 6 записей по 400 BYN, которых не видно 4 суток: в оценку не вошли (медиана 202.5 по 6 активным), статус not_seen, "
      "в истории — отдельно (n=6, med 400)", sorted((ap8.get("stats") or {}).get("prices") or []) == GOOD
      and all(recs()[str(8100 + i)]["status"] == "not_seen" for i in range(6)) and hist8.get("n") == 6 and hist8.get("med") == 400,
      (ap8.get("stats"), hist8))
check("8б not_seen — не «продано»: ни в базе, ни в оценке нет статуса sold и сделок",
      not any(r_.get("status") == "sold" for r_ in recs().values()) and k.load_deals() == [] and "sold" not in json.dumps(recs()))

# ------------------------------------------------------------------------------------------------------------------
# 9. Малая выборка → низкая уверенность, а не ложная точность
# ------------------------------------------------------------------------------------------------------------------
reset()
for i, p in enumerate((190, 200, 210)):
    k.mdb_observe(ad(9000 + i, price=p), now=T0 - 600)
k.mdb_save(T0)
reload_db()
t9 = ad(9100, price=120, age=60)
f9 = k.rule_facts(t9)
ap9 = k.appraise(t9, f9)
msg9 = k.build_short_message(t9, f9, ap9)
check("9 3 аналога (меньше MIN_COMPS=5): уверенность низкая, «мало аналогов», вердикт не ВЫГОДНО даже при цене 120 против 200",
      ap9.get("conf") == "низкая" and ap9.get("thin") and "✅ ВЫГОДНО" not in msg9 and "Уверенность" in msg9,
      (ap9.get("conf"), ap9.get("thin"), ap9.get("decision"), msg9[-400:]))

# 9б. Нейросеть не выдаёт предположения за факты
t9b = ad(9200, price=150, age=60, desc="Всё работает")
f9b = k.rule_facts(t9b)
f9b["photo"].update(status="analyzed", n=2)
llm = {"photos": {"findings": [{"part": "экран", "kind": "screen", "what": "трещина", "confidence": "высокая"}],
                  "kit_visible": ["коробка", "золотой слиток"]},
       "battery_pct": 50, "defects": {"board": "не включается"}, "model": "iPhone 15 Pro", "memory": 512}
f9b = k.merge_llm(f9b, llm)
k.mdb_observe(t9b, facts=f9b, now=T0, checked=True)
k.mdb_appraisal(9200, f9b, k.appraise(t9b, f9b), now=T0)
r9b = recs()["9200"]
check("9б ответ нейросети: модель/память/аккумулятор/дефекты из текста НЕ приняты; трещина на фото — отдельно, с пометкой "
      "«не проверка», в дефекты расчёта не попала; неизвестный предмет комплекта отброшен",
      f9b["label"] == "iPhone X" and f9b["mem"] == 64 and f9b["battery_pct"] is None and not f9b["defects"]
      and "defects" not in r9b and "не проверка" in r9b["photo"]["src"] and r9b["photo"]["kit_visible"] == ["коробка"]
      and r9b["photo"]["findings"][0]["what"] == "трещина", (f9b["label"], f9b["mem"], f9b["defects"], r9b.get("photo")))

# ------------------------------------------------------------------------------------------------------------------
# 10. Сбой сохранения не уничтожает предыдущую корректную базу
# ------------------------------------------------------------------------------------------------------------------
reset()
for i in range(120):
    k.mdb_observe(ad(10000 + i, price=200 + i % 7), now=T0)
k.mdb_save(T0)
good_bytes = k.MARKET_DB_FILE.read_bytes()
reload_db()
k.mdb_observe(ad(10500, price=210), now=T0 + 60)
orig_replace = os.replace
os.replace = lambda *a_: (_ for _ in ()).throw(OSError(28, "No space left on device"))
ok10 = k.mdb_save(T0 + 60)
os.replace = orig_replace
check("10 диск переполнен при замене файла: mdb_save вернул False, прежний файл байт в байт цел, временный удалён",
      ok10 is False and k.MARKET_DB_FILE.read_bytes() == good_bytes and not list(D.glob("*.tmp")), ok10)
recs()["10501"] = {"last_seen": int(T0 + 120), "x": {1, 2}}  # несериализуемое значение (множество) в памяти
ok10b = k.mdb_save(T0 + 120)
check("10б ошибка сериализации: файл не тронут", ok10b is False and k.MARKET_DB_FILE.read_bytes() == good_bytes, ok10b)
reload_db()
for k_ in list(recs())[:100]:
    del recs()[k_]
ok10c = k.mdb_save(T0 + 180)
check("10в в памяти вдвое меньше записей, чем загружено (похоже на ошибку) — сохранение отказано, файл цел",
      ok10c is False and k.MARKET_DB_FILE.read_bytes() == good_bytes, ok10c)
k.MARKET_DB_FILE.write_text('{"ads": {"1": ', encoding="utf-8")  # оборванный файл
k.MARKET_DB_BACKUP.unlink() if k.MARKET_DB_BACKUP.exists() else None
reload_db()
broken = k.MARKET_DB_FILE.read_bytes()
k.mdb_observe(ad(10600, price=210), now=T0 + 240)
check("10г повреждённый файл без резервной копии: база выключена, файл не перезаписан", not k.MDB["ok"]
      and k.mdb_save(T0 + 240) is False and k.MARKET_DB_FILE.read_bytes() == broken)

# ------------------------------------------------------------------------------------------------------------------
# 12 (часть в памяти). Слияние двух разошедшихся версий ОДНОЙ записи и двух seen.json
# ------------------------------------------------------------------------------------------------------------------
base_rec = {"first_seen": int(T0 - 86400), "last_seen": int(T0 - 3600), "key": "iPhone X", "title": "iPhone X 64gb",
            "price_hist": [[int(T0 - 86400), 200, "search"]], "price_byn": 200, "comp": [200, 64, 0, 1, 0],
            "has_desc": True, "defects": {"screen": "царапины"}}
ver_a = json.loads(json.dumps(base_rec))  # запуск A: карточка показала снижение до 180, уведомление отправлено
ver_a["price_hist"].append([int(T0 - 600), 180, "card"])
ver_a.update(last_seen=int(T0 - 600), notify={"status": "sent", "t": int(T0 - 600)},
             appraisals=[{"t": int(T0 - 600), "quick": 170}])
ver_b = json.loads(json.dumps(base_rec))  # запуск B (устаревшая копия, но позже): выдача снова 200, своя оценка, без отправки
ver_b.update(last_seen=int(T0 - 60), notify={"status": "expired", "t": int(T0 - 60)}, appraisals=[{"t": int(T0 - 60), "quick": 175}])
ver_b.pop("defects")  # B видел новое описание без дефектов
ver_b["defects_src"] = "текст продавца: дефекты не названы (это не подтверждение исправности)"
m = k.merge_db_records(ver_a, ver_b)
check("12г слияние одной записи: обе цены в истории с временем, текущая — карточки 180, отметка «отправлено» сохранилась, "
      "обе оценки, first_seen — ранний, last_seen — поздний", m["price_hist"] == [[int(T0 - 86400), 200, "search"],
      [int(T0 - 600), 180, "card"]] and m["price_byn"] == 180 and m["comp"][0] == 180 and m["notify"]["status"] == "sent"
      and [x["quick"] for x in m["appraisals"]] == [170, 175] and m["first_seen"] == int(T0 - 86400)
      and m["last_seen"] == int(T0 - 60) and k.price_changes(m["price_hist"]) == 0, m)
check("12д факты описания берутся из более поздней версии: дефект, который новое описание не подтвердило, не возвращается",
      "defects" not in m and "не названы" in m.get("defects_src", ""), m.get("defects"))
check("12е порядок аргументов не важен", k.merge_db_records(ver_b, ver_a) == m)
s_a = {"seen": {"3001": 100, "1500": 50}, "marks": {"1": [3001, 10]}, "pending": {"3002": {"t": 5, "ad": {}}}, "notice": 2,
       "market": {"iPhone X": {"t": 10, "items": [1]}}, "history": {"3001": {"t": 1}}, "baseline": ["iphone"]}
s_b = {"seen": {"3002": 120, "1500": 70}, "marks": {"1": [2999, 9], "2": [3100, 20]}, "pending": {}, "notice": 2,
       "market": {"iPhone X": {"t": 20, "items": [2]}}, "history": {"3002": {"t": 2}}, "baseline": ["samsung"]}
ms = k.merge_seen_data(s_a, s_b)
check("12ж слияние seen.json: оба номера, время — позднее, в каждом окне — наибольший номер, кеш — новее, очередь без "
      "уже отправленного (3002 отправлен вторым запуском)", ms["seen"] == {"1500": 70, "3001": 100, "3002": 120}
      and ms["marks"] == {"1": [3001, 10], "2": [3100, 20]} and ms["market"]["iPhone X"]["t"] == 20 and ms["pending"] == {}
      and set(ms["history"]) == {"3001", "3002"} and ms["baseline"] == ["iphone", "samsung"], ms)
dA, dB = fresh_dir(), fresh_dir()
(dA / "market_history.json").write_text(json.dumps({"version": 1, "ads": {"1": ver_a}}))
(dA / "seen.json").write_text(json.dumps(s_a))
(dB / "market_history.json").write_text('{"ads": {"1": ')  # их версия базы испорчена
(dB / "seen.json").write_text(json.dumps(s_b))
k.SEEN_FILE, k.MARKET_DB_FILE, k.MARKET_DB_BACKUP = dA / "seen.json", dA / "market_history.json", dA / "market_history.backup.json"
code = k.merge_state_cli(str(dB))
mdb_a = json.loads((dA / "market_history.json").read_text())
check("12з --merge-state: их база испорчена → наша база сохранена целиком, seen.json слит, код 0",
      code == 0 and mdb_a["ads"]["1"]["notify"]["status"] == "sent" and set(json.loads((dA / "seen.json").read_text())["seen"]) == {"1500", "3001", "3002"},
      (code, list(mdb_a["ads"])))
(dA / "market_history.json").write_text("испорчено")
before_b = (dB / "market_history.json").read_text()
code2 = k.merge_state_cli(str(dB))
check("12и обе базы испорчены → ни одна не перезаписана, код 0 (workflow оставит файлы как есть)",
      code2 == 0 and (dA / "market_history.json").read_text() == "испорчено" and (dB / "market_history.json").read_text() == before_b)

# ======================================================================================================================
# Части 11–15: отдельные процессы бота (как разные запуски GitHub Actions), общие только файлы
# ======================================================================================================================
time.time = _real_time


def run(d, ads, clock, market=None, fail=(), extra_env=None, cards=None):
    env = dict(os.environ)
    env.update(TG_TOKEN="t", TG_CHAT_ID="1", BOT_DIR=str(d), ADS=json.dumps(ads), FAIL=json.dumps(list(fail)), CLOCK=str(clock),
               MARKET=json.dumps(market or {}), CARDS=json.dumps(cards or {}), ARGV='["--once"]', MESSAGE_STYLE="short")
    for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "DRY_RUN", "QUERIES", "EXTRA_QUERIES"):
        env.pop(key, None)
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, str(HERE / "child.py")], env=env, capture_output=True, text=True, cwd=d, timeout=120)
    lines = [ln for ln in p.stdout.splitlines() if ln.startswith("{")]
    if not lines:
        print(p.stdout[-2000:], p.stderr[-2000:])
        raise SystemExit("дочерний процесс не вернул результат")
    res = json.loads(lines[-1])
    res["stdout"] = p.stdout
    return res


def msgs(res):
    return [m for m in res["sent"] + res["plain"] if m.startswith("📱")]


def dbf(d):
    p = d / "market_history.json"
    return json.loads(p.read_text()) if p.exists() else None


def hashes(d):
    return {f: hashlib.sha256((d / f).read_bytes()).hexdigest() for f in ("seen.json", "market_history.json",
                                                                          "market_history.backup.json") if (d / f).exists()}


C0 = T0
COMPS = [{"id": 1500 + i, "subject": "iPhone X 64gb", "price": p, "age": 2 * 86400 + i * 3600, "desc": "Всё работает"}
         for i, p in enumerate((180, 190, 200, 210, 220, 230, 240))]
FRESH = {"id": 2001, "subject": "iPhone X 64gb", "price": 130, "age": 60, "desc": "Всё работает, без дефектов"}

# ------------------------------------------------------------------------------------------------------------------
# 13. Старые объявления собираются в базу, не уходя в Telegram (процесс B независим от правила 5 минут)
# ------------------------------------------------------------------------------------------------------------------
d = fresh_dir()
run(d, [], C0 - 7200)  # первый запуск: пустая выдача, уведомление «запущен»
r13 = run(d, COMPS, C0 - 3600)
db13 = dbf(d)
check("13 запуск видит 7 объявлений возрастом 2–3 суток: все 7 в базе с ценами, в Telegram объявлений — 0",
      db13 and all(str(c["id"]) in db13["ads"] and db13["ads"][str(c["id"])]["price_byn"] == c["price"] for c in COMPS)
      and msgs(r13) == [], (msgs(r13), list((db13 or {}).get("ads", {}))[:10]))
check("13б в журнале — причина: «старое»", "Не отправляю" in r13["stdout"] and "старше" in r13["stdout"].lower()
      or "стар" in r13["stdout"].lower(), r13["stdout"][-600:])

# ------------------------------------------------------------------------------------------------------------------
# 11. Два последовательных запуска используют одну и ту же сохранённую историю
# ------------------------------------------------------------------------------------------------------------------
st = json.loads((d / "seen.json").read_text())
st["market"] = {}  # кеш выдачи в seen.json убираем — в следующем запуске аналоги могут прийти ТОЛЬКО из базы
(d / "seen.json").write_text(json.dumps(st))
d_nodb = fresh_dir()
shutil.copy(d / "seen.json", d_nodb / "seen.json")  # то же состояние, но без файла базы
d_twice = fresh_dir()
for f in ("seen.json", "market_history.json"):
    shutil.copy(d / f, d_twice / f)
mk = {"iphone x": [], "iphone": [FRESH], "айфон": [FRESH]}
CARD11 = {"2001": {"price_byn": "13000", "body": FRESH["desc"]}}  # карточка: цена страницы совпадает — цена сверена
r11 = run(d, [], C0, market=mk, fail=["iphone x"], cards=CARD11)
r11_nodb = run(d_nodb, [], C0, market=mk, fail=["iphone x"], cards=CARD11)
m11, m11n = msgs(r11), msgs(r11_nodb)
check("11 второй запуск (отдельный процесс) прочитал базу первого: свежее объявление оценено по 7 сохранённым аналогам",
      len(m11) == 1 and "Цена для быстрой продажи" in m11[0] and "Максимальная цена покупки" in m11[0]
      and "Сопоставимых объявлений: 7" in m11[0], m11)
check("11б контроль: тот же запуск без файла базы — оценки по аналогам нет («недостаточно данных»)",
      len(m11n) == 1 and "НЕДОСТАТОЧНО ДАННЫХ" in m11n[0] and "Цена для быстрой продажи" not in m11n[0]
      and "Сопоставимых объявлений" not in m11n[0], m11n)
check("11д аналоги из базы видели час назад — сообщение не называет их «давно не обновлявшимися»",
      len(m11) == 1 and "давно" not in m11[0], m11)
r11_twice = run(d_twice, [], C0, market=mk, fail=["iphone x"], cards=CARD11)
check("11в воспроизводимость: тот же запуск на копии того же состояния даёт то же сообщение слово в слово",
      msgs(r11_twice) == m11, (msgs(r11_twice), m11))
db11 = dbf(d)
ap_rec = (db11["ads"].get("2001") or {}).get("appraisals") or [{}]
check("11г оценка записана в базу с числом аналогов из базы (db_comps=7) — следующий запуск увидит, на чём она построена",
      ap_rec[-1].get("db_comps") == 7 and ap_rec[-1].get("n") == 7, ap_rec)

# ------------------------------------------------------------------------------------------------------------------
# 14. Повторные запуски не отправляют одно объявление несколько раз
# ------------------------------------------------------------------------------------------------------------------
r14a = run(d, [], C0 + 60, market=mk, fail=["iphone x"])  # то же объявление, ему 120 с — ещё «свежее»
d14 = fresh_dir()
shutil.copy(d / "market_history.json", d14 / "market_history.json")
st14 = json.loads((d / "seen.json").read_text())
st14["seen"] = {i_: t_ for i_, t_ in st14["seen"].items() if i_ != "2001"}  # seen.json «потерял» это id (откат файла и т.п.)
(d14 / "seen.json").write_text(json.dumps(st14))
r14b = run(d14, [], C0 + 90, market=mk, fail=["iphone x"])
check("14 тот же свежий номер через 60 с — не отправлен повторно", msgs(r14a) == [], msgs(r14a))
check("14б даже если seen.json потерял номер, отметка «отправлено» в базе не даёт повтора", msgs(r14b) == [], msgs(r14b))

# ------------------------------------------------------------------------------------------------------------------
# 15. Тестовый режим ничего не отправляет и не меняет живое состояние; нет покупок и контактов с продавцами
# ------------------------------------------------------------------------------------------------------------------
before = hashes(d)
r15 = run(d, [], C0 + 120, market={"iphone": [dict(FRESH, id=2002, age=30)]}, extra_env={"DRY_RUN": "1"})
check("15 DRY_RUN=1: Telegram не вызывался ни разу, seen.json / база / копия — байт в байт прежние, временных файлов нет",
      r15["tg_calls"] == 0 and hashes(d) == before and not list(d.glob("*.tmp")) and r15["exit"] == 0,
      (r15["tg_calls"], r15["exit"], r15["stdout"][-800:]))
check("15б в журнале тестового запуска видно, что сообщение НЕ отправлено", "в Telegram НЕ отправлено" in r15["stdout"])
try:
    import yaml
    wf = yaml.safe_load((REPO / ".github" / "workflows" / "kufar.yml").read_text(encoding="utf-8"))
    save_step = [s_ for s_ in wf["jobs"]["check"]["steps"] if "Сохранить" in s_.get("name", "")][0]
    check("15в workflow: в тестовом запуске шаг сохранения в репозиторий не выполняется", "!inputs.dry_run" in save_step.get("if", ""))
    co = wf["jobs"]["check"]["steps"][0]
    check("12к workflow: checkout берёт свежую вершину main (ref: main), а не коммит на момент вызова — запуск из очереди не "
          "начинает со старого снимка", co.get("uses", "").startswith("actions/checkout") and (co.get("with") or {}).get("ref") == "main", co)
    check("12л workflow: старое правило «-X theirs» (одна версия затирает другую) больше не используется",
          "-X theirs" not in save_step["run"] and "--merge-state" in save_step["run"])
except ImportError:
    save_step = None
    print("SKIP 15в нет модуля yaml")
src = BOT.read_text(encoding="utf-8")
import re  # noqa: E402
posts = re.findall(r"requests\.post\(\s*f?[\"']([^\"']+)", src)
check("15г бот делает POST только в Telegram и нейросети — никаких запросов к Куфару на покупку/сообщение продавцу",
      posts and all(("api.telegram.org" in u_) or ("generativelanguage" in u_) or ("anthropic" in u_) or u_.startswith("{")
                    for u_ in posts) and "kufar.by" not in " ".join(posts), posts)

# ------------------------------------------------------------------------------------------------------------------
# 16. Испорченные поля (ручная правка, сбой): запуск не падает, свежее уходит, база продолжает обновляться
# ------------------------------------------------------------------------------------------------------------------
import random  # noqa: E402

GARBAGE = [None, "abc", -5, 3.5, [], ["x", 1], {}, {"a": 1}, True, "2026-13-45T99:99:99Z"]
REC_FIELDS = ["price_hist", "price_raw", "list_time", "list_time_hist", "first_list_time", "appraisals", "forecast_checks",
              "notify", "comp", "key", "model", "last_seen", "first_seen", "conflicts", "defects", "battery", "kit",
              "price_byn", "publication", "condition_cat", "has_desc", "last_check", "price_conflict", "mem_gb"]
bad16 = []
for seed in range(6):
    rnd = random.Random(seed)
    d16 = fresh_dir()
    run(d16, [], C0 - 7200)
    run(d16, COMPS, C0 - 3600)
    dbj = json.loads((d16 / "market_history.json").read_text())
    for rec_ in dbj["ads"].values():
        for f_ in rnd.sample(REC_FIELDS, 6):
            rec_[f_] = rnd.choice(GARBAGE)
    dbj["weekly"] = rnd.choice([None, "x", {"iPhone X|64": "x"}, {"iPhone X|64": {"2026-W44": "x"}}, []])
    dbj["backup_t"] = rnd.choice(GARBAGE)
    (d16 / "market_history.json").write_text(json.dumps(dbj))
    stj = json.loads((d16 / "seen.json").read_text())
    stj["notice"] = rnd.choice(["abc", [], {}, None, 2])
    stj["marks"] = rnd.choice([{"1": "x"}, {"x": [1, 2]}, {"5": [None, "a"]}, [], "x", stj.get("marks")])
    stj["pending"] = rnd.choice([{"1": "x"}, {"x": {"t": "a", "ad": 5}}, [], "x"])
    stj["market"] = rnd.choice([{"iPhone X": "x"}, {"iPhone X": {"t": "a", "items": "b"}}, [], "x", {"iPhone X": {"t": 1, "items": [["x"]]}}])
    stj["history"] = rnd.choice([{"1": "x"}, [], "x", {"2": {"t": "a"}}])
    (d16 / "seen.json").write_text(json.dumps(stj))
    r16 = run(d16, COMPS, C0, market={"iphone": [dict(FRESH, id=4001)] + COMPS},
              cards={"4001": {"price_byn": "13000", "body": FRESH["desc"]}})
    sent16 = [m_ for m_ in msgs(r16) if "item/4001" in m_]
    db16 = dbf(d16) or {"ads": {}}
    errs = [ln for ln in r16["stdout"].splitlines() if "Traceback" in ln or "не удалось записать" in ln or "Пропускаю странное" in ln
            or "Ошибка оценки" in ln or "Ошибка в цикле" in ln]
    ok16 = (r16["exit"] == 0 and len(sent16) == 1 and db16["ads"].get("4001", {}).get("notify", {}).get("status") == "sent"
            and not errs)
    if not ok16:
        bad16.append((seed, r16["exit"], len(sent16), errs[:4], r16["stdout"][-700:] if r16["exit"] else ""))
check("16 6 вариантов испорченных полей в базе (по 6 полей в каждой записи) и в seen.json: запуск не падает, свежее "
      "объявление ушло ровно один раз и отмечено в базе, ошибок записи/оценки в журнале нет", not bad16, bad16)

# ------------------------------------------------------------------------------------------------------------------
# 12. Параллельный запуск / устаревшая копия не теряет более новые данные (настоящий git + шаг сохранения из kufar.yml)
# ------------------------------------------------------------------------------------------------------------------


def git(cwd, *args, check_=True):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check_ and p.returncode:
        raise SystemExit(f"git {' '.join(args)}: {p.stderr}")
    return p.stdout.strip()


def save_script(yml_text):
    return [s_ for s_ in yaml.safe_load(yml_text)["jobs"]["check"]["steps"] if "Сохранить" in s_.get("name", "")][0]["run"]


def scenario(script):
    """Удалённый main с состоянием S0. Запуск A (начал с S0) отправил объявление 3001 и записал запись базы; запуск B тоже начал
    с S0 (устаревший снимок: ждал в очереди) и отправил 3002. Оба по очереди сохраняют состояние скриптом из workflow.
    Возвращает (seen, база) в удалённом main после обоих сохранений и вывод скрипта B."""
    root = Path(tempfile.mkdtemp(prefix="kufar_git_"))
    remote = root / "remote.git"
    git(root, "init", "-q", "--bare", "-b", "main", str(remote))
    seed = root / "seed"
    git(root, "clone", "-q", str(remote), str(seed))
    for f in ("user.name", "user.email"):
        git(seed, "config", f, "t@t" if "email" in f else "t")
    shutil.copy(BOT, seed / "kufar_bot.py")
    shutil.copy(REPO / ".gitignore", seed / ".gitignore")  # как в репозитории: __pycache__, замок и *.tmp не коммитятся
    run(seed, [], C0 - 7200)  # S0: бот уже работает
    run(seed, COMPS, C0 - 3600)
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "S0")
    git(seed, "push", "-q", "origin", "HEAD:main")
    clones = {}
    for name in ("A", "B"):
        c = root / name
        git(root, "clone", "-q", str(remote), str(c))
        clones[name] = c
    ra = run(clones["A"], [], C0, market={"iphone": [dict(FRESH, id=3001)]})
    rb = run(clones["B"], [], C0 + 30, market={"iphone": [dict(FRESH, id=3002, price=140)]})
    bin_ = root / "bin"
    bin_.mkdir()
    (bin_ / "python").symlink_to(sys.executable)  # в Actions `python` — интерпретатор с установленным requests
    env = dict(os.environ, RUNNER_TEMP=str(root / "tmp"), PATH=f"{bin_}:{os.environ['PATH']}")
    for v in ("TG_TOKEN", "TG_CHAT_ID", "GEMINI_API_KEY"):
        env.pop(v, None)
    out = {}
    for name in ("A", "B"):
        (root / "tmp").mkdir(exist_ok=True)
        p = subprocess.run(["bash", "-e", "-o", "pipefail", "-c", script], cwd=clones[name], env=env, capture_output=True,
                           text=True, timeout=180)
        out[name] = (p.returncode, p.stdout + p.stderr)
    chk = root / "check"
    git(root, "clone", "-q", str(remote), str(chk))
    seen_ = json.loads((chk / "seen.json").read_text())
    db_ = json.loads((chk / "market_history.json").read_text())
    shutil.rmtree(root, ignore_errors=True)
    return seen_, db_, out, (msgs(ra), msgs(rb))


if save_step is not None:
    new_script = save_step["run"]
    seen12, db12, out12, sent12 = scenario(new_script)
    ok_sent = len(sent12[0]) == 1 and len(sent12[1]) == 1
    check("12 два запуска с одного снимка (второй — устаревшая копия): после сохранения обоих в main есть ОБА отправленных "
          "номера в seen.json и обе отметки «отправлено» в базе, старые записи на месте",
          ok_sent and {"3001", "3002"} <= set(seen12["seen"]) and db12["ads"]["3001"]["notify"]["status"] == "sent"
          and db12["ads"]["3002"]["notify"]["status"] == "sent" and all(str(c["id"]) in db12["ads"] for c in COMPS)
          and out12["B"][0] == 0 and "слито" in out12["B"][1], (sent12, out12["B"]))
    check("12б слияние не создало фиктивных изменений цены и дублей", all(k.price_changes(r_.get("price_hist")) == 0
                                                                       for r_ in db12["ads"].values()), "")
    old_yml = subprocess.run(["git", "show", "origin/main:.github/workflows/kufar.yml"], cwd=REPO, capture_output=True, text=True)
    if old_yml.returncode == 0 and "-X theirs" in old_yml.stdout:
        seen_o, db_o, out_o, _ = scenario(save_script(old_yml.stdout))
        lost = "3001" not in seen_o["seen"] or "3001" not in db_o["ads"]
        check("12в воспроизведение прежней ошибки: старый шаг сохранения (git pull --rebase -X theirs) в той же ситуации "
              "ТЕРЯЕТ номер 3001 — новая версия это исправляет", lost, (len(seen_o["seen"]), "3001" in seen_o["seen"], "3002" in seen_o["seen"], "3001" in db_o["ads"], out_o["B"][1][-1500:]))
    else:
        print("SKIP 12в старой версии workflow с -X theirs нет в origin/main — сравнение не проводится")

check("живые seen.json / market_history.json репозитория не изменились за время теста",
      {f: hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None for f, p in LIVE.items()} == LIVE_HASH)

print(f"\n{'Всё в порядке' if not bad else f'Ошибок: {bad}'}")
sys.exit(1 if bad else 0)
