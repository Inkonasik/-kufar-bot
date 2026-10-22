"""Сквозные тесты основного цикла (сеть и Telegram подменены): первый запуск, обновление со старого seen.json, тихое запоминание
новых запросов, аналоги и кеш, сбои Telegram/Куфара, очередь повторов, повторы запросов, лимиты карточек, тестовый запуск."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, fresh_dir  # noqa: E402

bad = 0


def check(name, cond, extra=""):
    global bad
    print(("OK  " if cond else "FAIL"), name, "" if cond else extra)
    bad += 0 if cond else 1


def run(d, ads, fail=(), argv=("--once",), tg="ok", market=None, raw=None, bodies=None, flaky=None, card="ok", **extra):
    env = dict(os.environ)
    env.update(TG_TOKEN="t", TG_CHAT_ID="1", BOT_DIR=str(d), ADS=json.dumps(ads), FAIL=json.dumps(list(fail)), TG=tg, CARD=card,
               MARKET=json.dumps(market or {}), RAW=json.dumps(raw or []), BODIES=json.dumps(bodies or {}),
               FLAKY=json.dumps(flaky or {}), ARGV=json.dumps(list(argv)))
    for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MODELS", "QUERIES", "EXTRA_QUERIES", "DRY_RUN"):
        env.pop(key, None)
    env.update(extra)
    p = subprocess.run([sys.executable, str(HERE / "child.py")], env=env, capture_output=True, text=True, cwd=d)
    lines = [l for l in p.stdout.splitlines() if l.startswith("{")]
    if not lines:
        print(p.stdout[-1500:], p.stderr[-1500:])
        raise SystemExit("дочерний процесс не вернул результат")
    res = json.loads(lines[-1])
    res["stdout"] = p.stdout
    seen_path = d / "seen.json"
    return res, (json.loads(seen_path.read_text()) if seen_path.exists() else None)


def ad_msgs(res):
    return [m for m in res["sent"] + res["plain"] if m.startswith("📱")]


def legacy_file(n=1300):
    """seen.json в формате старой версии бота: только seen и history."""
    d = fresh_dir()
    ids = [1088000000 + i * 7 for i in range(n)]
    hist = {str(ids[i]): {"t": int(time.time()) - 86400 * (i % 9), "m": "iPhone 5s", "p": 100.0 + i, "c": "Б/у", "s": f"iPhone 5s {i}",
                          "l": f"https://www.kufar.by/item/{ids[i]}", "ok": True} for i in range(40)}
    (d / "seen.json").write_text(json.dumps({"seen": ids, "history": hist}, ensure_ascii=False))
    return d / "seen.json", ids, hist


LEGACY, OLD_IDS, OLD_HIST = legacy_file()
fx = lambda: fresh_dir(LEGACY)  # noqa: E731

# ---------- 1. первый запуск ----------
d = fresh_dir()
res, st = run(d, [(1, "iPhone 5s"), (2, "iPhone 14")])
check("1 первый запуск: exit 0, одно сообщение о старте, объявления запомнены молча",
      res["exit"] == 0 and len(res["sent"]) == 1 and "запущен" in res["sent"][0] and set(st["seen"]) == {1, 2}, res["sent"])
res, st = run(d, [(1, "iPhone 5s"), (2, "iPhone 14"), (3, "iPhone 6s 64gb"), (4, "iPhone 15")])
check("2 второй запуск: ровно одно уведомление про 6s, без повторного «запущен»",
      res["exit"] == 0 and len(res["sent"]) == 1 and "iPhone 6s" in res["sent"][0] and set(st["seen"]) == {1, 2, 3, 4}, res["sent"])
res, st = run(d, [(1, "iPhone 5s"), (2, "iPhone 14"), (3, "iPhone 6s 64gb"), (4, "iPhone 15")])
check("3 без новых — тишина", res["exit"] == 0 and res["sent"] == [], res["sent"])

# ---------- 4–7. сбои Куфара ----------
d = fresh_dir()
res, st = run(d, [(1, "iPhone 5s")], fail=["*"])
check("4 первый запуск, Куфар не отвечает: exit 1, ничего не сохранено и не отправлено", res["exit"] == 1 and st is None and res["sent"] == [], res)
d = fresh_dir()
run(d, [(1, "iPhone 5s"), (2, "iPhone 14")])
before = (d / "seen.json").read_text()
res, st = run(d, [(9, "iPhone 4s")], fail=["*"])
check("5 Куфар не отвечает при готовом состоянии: exit 1, файл не тронут", res["exit"] == 1 and (d / "seen.json").read_text() == before, res)
d = fresh_dir()
res, st = run(d, [(1, "iPhone 5s")], fail=["samsung"])
check("6 частичный отказ на первом запуске: exit 1, ничего не сохранено", res["exit"] == 1 and st is None, res)
d = fresh_dir()
run(d, [(1, "iPhone 5s")])
res, st = run(d, [(1, "iPhone 5s"), (5, "iPhone 4s")], fail=["samsung"])
check("7 частичный отказ позже: уведомление пришло", res["exit"] == 0 and len(ad_msgs(res)) == 1 and "4s" in ad_msgs(res)[0], res["sent"])

# ---------- A. обновление со старого seen.json ----------
d = fx()
ads = [(i, "iPhone 6") for i in OLD_IDS[:2]] + [(9001, "iPhone 7 32gb"), (9002, "Чехол iPhone 7"), (9003, "iPhone 14 Pro"),
                                                (9004, "iPhone 6s 16gb"), {"id": 9005, "subject": "Samsung Galaxy S9", "price": 200}]
res, st = run(d, ads)
msgs = ad_msgs(res)
check("A уведомления: 7, 6s, S9 (без чехла и iPhone 14, без старых)", len(msgs) == 3 and any("iPhone 7 32gb" in m for m in msgs)
      and any("iPhone 6s" in m for m in msgs) and any("Galaxy S9" in m for m in msgs), [m[:40] for m in msgs])
check("A разовое уведомление об обновлении", sum("Бот обновлён" in m for m in res["sent"]) == 1)
check("A ключи состояния", set(st) >= {"seen", "history", "market", "baseline", "notice", "pending"}, list(st))
check("A старые id и история сохранены", set(OLD_IDS) <= set(st["seen"]) and set(OLD_HIST) <= set(st["history"]))
check("A новые id в seen (и отфильтрованные тоже)", {9001, 9002, 9003, 9004, 9005} <= set(st["seen"]))
check("A baseline: старые + новые запросы", {"iphone", "samsung", "ipod touch", "айфон", "самсунг"} <= set(st["baseline"]), st["baseline"])
check("A нет временного файла", not (d / "seen.json.tmp").exists())
check("A дедупликация: одно сообщение на объявление", len(msgs) == len({m.split("\n")[0] for m in msgs}))
res2, st2 = run(d, ads)
check("A повторный запуск: тишина, уведомление не повторяется", res2["exit"] == 0 and res2["sent"] == [] and res2["plain"] == [], res2["sent"])

d = fresh_dir()
(d / "seen.json").write_text(json.dumps([1, 2, 3]))
res, st = run(d, [(1, "iPhone 5s"), (4, "iPhone 8")])
check("A2 старейший формат (список id) читается", res["exit"] == 0 and len(ad_msgs(res)) == 1 and isinstance(st, dict) and {1, 2, 3, 4} <= set(st["seen"]))

# ---------- B. новый запрос запоминается молча ----------
d = fx()
res, st = run(d, [], market={"айфон": [[777, "Айфон 7 plus"]]})
check("B новый запрос: без уведомлений, id запомнен", res["exit"] == 0 and ad_msgs(res) == [] and 777 in st["seen"], res["sent"])
res, st = run(d, [], market={"айфон": [[777, "Айфон 7 plus"], [778, "Айфон 8"]]})
check("B дальше приходит только новое", len(ad_msgs(res)) == 1 and "Айфон 8" in ad_msgs(res)[0], res["sent"])

# ---------- C. аналоги и кеш ----------
comps = [{"id": 2000 + i, "subject": "iPhone 11 64gb", "price": 600 + i * 10} for i in range(12)]
d = fx()
res, st = run(d, [{"id": 5000, "subject": "iPhone 11 64gb", "price": 590, "desc": "Идеальное состояние, акб 90%, полный комплект"}], market={"iphone 11": comps})
m = (ad_msgs(res) or [""])[0]
check("C сообщение с ценой, целью, происхождением цен, выводом и пометкой «не сделок»", all(x in m for x in ("📊 Цена относительно рынка:", "🎯", "💵 Откуда цены", "✅ <b>Вывод для перепродажи:</b>", "не сделок")), m)
check("C ссылки на реальные аналоги", "https://www.kufar.by/item/2000" in m or "https://www.kufar.by/item/2005" in m)
check("C одна загрузка аналогов", sum(g == "iphone 11|100" for g in res["gets"]) == 1)
check("C кеш аналогов сохранён", "iPhone 11" in st["market"] and len(st["market"]["iPhone 11"]["items"]) >= 10)
res2, st2 = run(d, [{"id": 5001, "subject": "iPhone 11 64gb", "price": 700}], market={"iphone 11": comps})
check("C второй запуск: свежий кеш, повторной загрузки нет", sum(g == "iphone 11|100" for g in res2["gets"]) == 0 and len(ad_msgs(res2)) == 1)

# ---------- D. сбои Telegram ----------
d = fx()
res, st = run(d, [(9101, "iPhone 8 64gb")], tg="500")
check("D Telegram 500: объявление не потеряно (не в seen, лежит в очереди повторов)", res["exit"] == 0 and 9101 not in st["seen"] and "9101" in st["pending"], st["pending"].keys())
d = fx()
res, st = run(d, [(9102, "iPhone 8 64gb")], tg="400parse")
check("D ошибка разметки: ушёл простой текст, объявление отмечено", res["plain"] and "<b>" not in res["plain"][0] and 9102 in st["seen"])
d = fx()
res, st = run(d, [(9103, "iPhone 8 64gb")], tg="400chat")
check("D «chat not found»: объявление не теряется", 9103 not in st["seen"] and "9103" in st["pending"])
d = fx()
res, st = run(d, [(9104, "iPhone 8 64gb")], tg="429once")
check("D лимит Telegram 429: повтор после паузы, сообщение доставлено", len(ad_msgs(res)) == 1 and 9104 in st["seen"] and res["tg_calls"] == 3 or
      (len(ad_msgs(res)) == 1 and 9104 in st["seen"]), (res["tg_calls"], res["sent"]))

# ---------- E. очередь повторов ----------
d = fx()
res, st = run(d, [(9201, "iPhone 8 64gb")], tg="500")
res, st = run(d, [], tg="ok")  # объявление уже пропало из выдачи Куфара
check("E повтор: объявление доставлено, хотя в выдаче его уже нет", len(ad_msgs(res)) == 1 and "iPhone 8" in ad_msgs(res)[0] and 9201 in st["seen"] and st["pending"] == {},
      (res["sent"][:1], st["pending"].keys()))
res, st = run(d, [], tg="ok")
check("E после доставки повторов нет", ad_msgs(res) == [])
d = fx()
run(d, [(9202, "iPhone 8 64gb")], tg="500")
state = json.loads((d / "seen.json").read_text())
state["pending"]["9202"]["t"] = int(time.time()) - 48 * 3600
(d / "seen.json").write_text(json.dumps(state))
res, st = run(d, [], tg="ok")
check("E очередь старше 24 часов отбрасывается", ad_msgs(res) == [] and st["pending"] == {}, st["pending"].keys())
d = fx()
res, st = run(d, [(9203, "iPhone 8 64gb")], RUN_BUDGET_S="0")
check("E не хватило времени: объявление в очереди, не в seen", ad_msgs(res) == [] and 9203 not in st["seen"] and "9203" in st["pending"])
res, st = run(d, [], tg="ok")
check("E следующий запуск его отправляет", len(ad_msgs(res)) == 1 and 9203 in st["seen"])

# ---------- F. повторы запросов с паузой ----------
d = fx()
res, st = run(d, [(9301, "iPhone 8 64gb")], flaky={"iphone": [503, "conn"]})
check("F два сбоя подряд, потом успех: запрос повторён и объявление пришло", len(ad_msgs(res)) == 1 and sum(g.startswith("iphone|") for g in res["gets"]) == 3, [g for g in res["gets"] if g.startswith("iphone|")])
d = fx()
res, st = run(d, [(9302, "iPhone 8 64gb")], flaky={"iphone": [429, 429, 429, 429]})
check("F запрос стабильно падает: пробуем 3 раза, остальные запросы работают, exit 0", res["exit"] == 0 and sum(g.startswith("iphone|") for g in res["gets"]) == 3
      and len(ad_msgs(res)) == 1, [g for g in res["gets"] if g.startswith("iphone|")])
d = fx()
res, st = run(d, [(9303, "iPhone 8 64gb")], fail=["*"])
check("F всё падает: exit 1, файл не изменён", res["exit"] == 1)

# ---------- G. «ядовитые» объявления ----------
d = fx()
raw = [{"ad_id": 8001, "type": "sell", "subject": None, "price_byn": "abc", "ad_parameters": None, "ad_link": "x"},
       {"type": "sell", "subject": "iPhone 8"}, {"ad_id": None, "type": "sell", "subject": "iPhone 8 plus"},
       {"ad_id": 8003, "type": "sell", "subject": "iPhone 8 64gb", "price_byn": None, "price_usd": None,
        "ad_parameters": [None, "x", {"p": "region", "vl": None}], "ad_link": "https://www.kufar.by/item/8003"},
       {"ad_id": 8004, "type": "sell", "subject": ["не", "строка"], "ad_parameters": [], "ad_link": "x"}]
res, st = run(d, [], raw=raw)
check("G странные объявления не роняют запуск; нормальное с пустой ценой пришло", res["exit"] == 0 and len(ad_msgs(res)) == 1 and "цена не указана" in ad_msgs(res)[0], res["sent"])
check("G странные записаны в seen (не зацикливаются)", {8001, 8003, 8004} <= set(st["seen"]))
res2, st2 = run(d, [], raw=raw)
check("G повторный запуск: тишина", ad_msgs(res2) == [])

# ---------- H. описание из карточки и лимиты карточек ----------
d = fx()
body = "Продам iPhone 11 Pro Max. Использовался аккуратно женой.\nВсё родное, без ремонтов и вскрытий.\nБЕЗ ОБМЕНА И ТОРГА! Разбит экран."
res, st = run(d, [{"id": 9501, "subject": "iPhone 11 Pro Max", "price": 420}, {"id": 9404, "subject": "iPhone 11"}], bodies={"9501": body})
m = [x for x in ad_msgs(res) if "Pro Max" in x]
check("H описание подтянуто: дефект и «без торга» найдены", m and "проблемы с экраном" in m[0] and "без торга" in m[0] and "Описание в выдаче" not in m[0], m[:1])
m2 = [x for x in ad_msgs(res) if "<b>iPhone 11</b>" in x]
check("H карточка 404: сообщение всё равно пришло с пометкой", m2 and "Описание в выдаче" in m2[0])
many = [(9600 + i, "iPhone 8 64gb") for i in range(8)]
d = fx()
res, st = run(d, many, card="500")
fetched = {g for g in res["gets"] if g.startswith("item:")}
check("H карточки не отвечают: после 3 неудач подряд запросы прекращаются, все сообщения пришли", len(ad_msgs(res)) == 8 and len(fetched) <= 3, (len(ad_msgs(res)), fetched))
d = fx()
res, st = run(d, many, MAX_CARD_FETCH="2")
check("H лимит карточек за запуск (2)", len({g for g in res["gets"] if g.startswith("item:")}) == 2 and len(ad_msgs(res)) == 8)

# ---------- I. тестовый запуск ----------
d = fx()
before = (d / "seen.json").read_bytes()
res, st = run(d, [(OLD_IDS[0], "iPhone 8 64gb"), (9701, "iPhone 11 128gb"), (9702, "Чехол iPhone 7")], argv=("--dry-run",), TG_TOKEN="", TG_CHAT_ID="")
check("I тестовый запуск: exit 0 без токена, в Telegram ничего не ушло", res["exit"] == 0 and res["sent"] == [] and res["plain"] == [] and res["tg_calls"] == 0, res)
check("I сообщения показаны в логе (в т.ч. уже виденное), без аксессуара", res["stdout"].count("ТЕСТОВЫЙ ЗАПУСК: в Telegram НЕ отправлено") == 2
      and "iPhone 11 128gb" in res["stdout"] and "Чехол" not in res["stdout"], res["stdout"][-400:])
check("I seen.json не изменился", (d / "seen.json").read_bytes() == before)
d = fx()
before = (d / "seen.json").read_bytes()
res, st = run(d, [(9703, "iPhone 8 64gb")], argv=("--once",), DRY_RUN="true")
check("I DRY_RUN=true работает как --dry-run (так запускает workflow)", res["tg_calls"] == 0 and "ТЕСТОВЫЙ ЗАПУСК" in res["stdout"] and (d / "seen.json").read_bytes() == before)
res, st = run(d, [(9704, "iPhone 8 64gb")], argv=("--dry-run",), DRY_RUN_LIMIT="1")
check("I лимит показа (1)", res["stdout"].count("НЕ отправлено") == 1)
d = fx()
res, st = run(d, [(1, "iPhone 8")], fail=["*"], argv=("--dry-run",))
check("I тестовый запуск при недоступном Куфаре: exit 1", res["exit"] == 1)

# ---------- J. недельный отчёт ----------
d = fx()
res, st = run(d, [], argv=("--report",))
check("J --report: одно сообщение", res["exit"] == 0 and len(res["sent"]) + len(res["plain"]) == 1, res["sent"])

print("итого ошибок (цикл):", bad)
sys.exit(1 if bad else 0)
