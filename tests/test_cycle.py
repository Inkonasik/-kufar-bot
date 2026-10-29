"""Сквозные тесты основного цикла (сеть, Telegram и часы подменены — см. child.py): свежесть публикаций, защита от поднятых,
первый запуск, обновление со старого seen.json, база рынка, аналоги и кеш, сбои Telegram/Куфара, очередь повторов,
повторы запросов, пагинация, карточки, параллельные запуски, ошибки базы, тестовый запуск, недельный отчёт.
Номера объявлений-«новинок» в тестах больше 1000: опорное объявление (child.py, REF) имеет номер 1000 и опубликовано 45 минут назад."""
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, fresh_dir  # noqa: E402

bad = 0
T0 = 1_793_196_000.0  # «сейчас» в большинстве тестов: 28.10.2026 14:00 UTC (часы бота подменены, реального ожидания нет)


def check(name, cond, extra=""):
    global bad
    print(("OK  " if cond else "FAIL"), name, "" if cond else extra)
    bad += 0 if cond else 1


def run(d, ads, fail=(), argv=("--once",), tg="ok", market=None, raw=None, bodies=None, flaky=None, card="ok", clock=T0,
        cards=None, pages=None, ref=True, **extra):
    env = dict(os.environ)
    env.update(TG_TOKEN="t", TG_CHAT_ID="1", BOT_DIR=str(d), ADS=json.dumps(ads), FAIL=json.dumps(list(fail)), TG=tg, CARD=card,
               MARKET=json.dumps(market or {}), RAW=json.dumps(raw or []), BODIES=json.dumps(bodies or {}),
               FLAKY=json.dumps(flaky or {}), ARGV=json.dumps(list(argv)), CLOCK=str(clock), CARDS=json.dumps(cards or {}),
               PAGES=json.dumps(pages or {}), REF="1" if ref else "0")
    for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MODELS", "QUERIES", "EXTRA_QUERIES", "DRY_RUN", "MESSAGE_STYLE"):
        env.pop(key, None)
    env.update({k_: str(v) for k_, v in extra.items()})
    p = subprocess.run([sys.executable, str(HERE / "child.py")], env=env, capture_output=True, text=True, cwd=d, timeout=120)
    lines = [l for l in p.stdout.splitlines() if l.startswith("{")]
    if not lines:
        print(p.stdout[-1500:], p.stderr[-1500:])
        raise SystemExit("дочерний процесс не вернул результат")
    res = json.loads(lines[-1])
    res["stdout"] = p.stdout
    seen_path = d / "seen.json"
    return res, (json.loads(seen_path.read_text()) if seen_path.exists() else None)


def db(d):
    p = d / "market_history.json"
    return json.loads(p.read_text()) if p.exists() else None


def ad_msgs(res):
    return [m for m in res["sent"] + res["plain"] if m.startswith("📱")]


def seen_ids(state):
    return {int(x) for x in (state or {}).get("seen", {})}


def legacy_file(n=1300):
    """seen.json в формате старой версии бота: только seen и history."""
    d = fresh_dir()
    ids = [1088000000 + i * 7 for i in range(n)]
    hist = {str(ids[i]): {"t": int(time.time()) - 86400 * (i % 9), "m": "iPhone 5s", "p": 100.0 + i, "c": "Б/у", "s": f"iPhone 5s {i}",
                          "l": f"https://www.kufar.by/item/{ids[i]}", "ok": True} for i in range(40)}
    (d / "seen.json").write_text(json.dumps({"seen": ids, "history": hist}, ensure_ascii=False))
    return d / "seen.json", ids, hist


def ready():
    """Папка с уже работающим ботом (первый запуск прошёл): seen.json есть, уведомление об обновлении уже было."""
    d = fresh_dir()
    run(d, [{"id": 1001, "subject": "iPhone 5s", "age": 3600}])  # старое: в следующих запусках само не придёт
    st = json.loads((d / "seen.json").read_text())
    return d, st


LEGACY, OLD_IDS, OLD_HIST = legacy_file()
fx = lambda: fresh_dir(LEGACY)  # noqa: E731

# ---------- 1–3. первый запуск и повторы ----------
d = fresh_dir()
res, st = run(d, [(1001, "iPhone 5s"), (1002, "iPhone 14")])
check("1 первый запуск: exit 0, одно сообщение о старте, объявлений не шлёт", res["exit"] == 0 and len(res["sent"]) == 1
      and "запущен" in res["sent"][0] and "5 мин" in res["sent"][0] and ad_msgs(res) == [], res["sent"])
base = db(d)
check("1 первый запуск: база рынка создана, в ней только подходящая модель", base and "1001" in base["ads"] and "1002" not in base["ads"],
      list((base or {}).get("ads", {}))[:5])
check("1 первый запуск: метки номеров сохранены в seen.json", st and st.get("marks"), st and list(st))
check("1 техническая статистика базы — в журнале (а не в Telegram)", "База рынка: объявлений" in res["stdout"]
      and not any("База рынка" in m for m in res["sent"]), res["stdout"][-300:])
check("1 первый запуск: висевшие в выдаче подходящие объявления помечены обработанными (не разошлются позже)", seen_ids(st) == {1001}, seen_ids(st))
# номера растут со временем, как на Куфаре: часовой давности — 1003, свежие — 1004 и 1005
res, st = run(d, [{"id": 1001, "subject": "iPhone 5s", "age": 300 + 120 + 1}, (1002, "iPhone 14"),
                  {"id": 1003, "subject": "iPhone 7 32gb", "age": 3600},
                  {"id": 1004, "subject": "iPhone 15"}, {"id": 1005, "subject": "iPhone 6s 64gb", "age": 60}], clock=T0 + 120)
check("2 второй запуск: одно уведомление про свежий 6s; iPhone 15 (не наша модель), iPhone 7 часовой давности и 5s, увиденный "
      "в первом запуске и уже устаревший, — нет",
      res["exit"] == 0 and len(ad_msgs(res)) == 1 and "iPhone 6s" in ad_msgs(res)[0] and 1005 in seen_ids(st) and 1003 not in seen_ids(st),
      [m[:40] for m in ad_msgs(res)])
check("2 сообщение короткое: цена продавца, вердикт, ссылка; без длинных разделов",
      ad_msgs(res) and "Цена продавца: 150 BYN" in ad_msgs(res)[0] and "🔗 https://www.kufar.by/item/1005" in ad_msgs(res)[0]
      and "Вариант 2" not in ad_msgs(res)[0] and len(ad_msgs(res)[0]) < 1200, ad_msgs(res)[:1])
res, st = run(d, [{"id": 1005, "subject": "iPhone 6s 64gb", "lt": T0 + 60}], clock=T0 + 240)
check("3 повторный запуск: то же объявление второй раз не приходит", res["exit"] == 0 and ad_msgs(res) == [], res["sent"])

# ---------- 4–7. сбои Куфара ----------
d = fresh_dir()
res, st = run(d, [(1001, "iPhone 5s")], fail=["*"])
check("4 первый запуск, Куфар не отвечает: exit 1, ничего не сохранено и не отправлено",
      res["exit"] == 1 and st is None and db(d) is None and res["sent"] == [], res)
d, _ = ready()
before, before_db = (d / "seen.json").read_text(), (d / "market_history.json").read_text()
res, st = run(d, [(1009, "iPhone 4s")], fail=["*"])
check("5 Куфар не отвечает при готовом состоянии: exit 1, seen.json и база не тронуты",
      res["exit"] == 1 and (d / "seen.json").read_text() == before and (d / "market_history.json").read_text() == before_db, res)
d = fresh_dir()
res, st = run(d, [(1001, "iPhone 5s")], fail=["samsung"])
check("6 частичный отказ на первом запуске: exit 1, ничего не сохранено", res["exit"] == 1 and st is None, res)
d, _ = ready()
res, st = run(d, [(1001, "iPhone 5s"), (1005, "iPhone 4s")], fail=["samsung"])
check("7 частичный отказ позже: свежее уведомление пришло", res["exit"] == 0 and len(ad_msgs(res)) == 1 and "4s" in ad_msgs(res)[0], res["sent"])

# ---------- S. свежесть: граница, вчерашние, без даты, поднятые ----------
for age, want in ((60, 1), (299, 1), (300, 1), (301, 0), (86400, 0)):
    d, _ = ready()
    res, st = run(d, [{"id": 2001, "subject": "iPhone 8 64gb", "age": age}])
    check(f"S возраст {age} с → {'отправлено' if want else 'не отправлено'} (граница 300 с включительно)", len(ad_msgs(res)) == want,
          (age, len(ad_msgs(res))))
d, _ = ready()
res, st = run(d, [{"id": 2002, "subject": "iPhone 8 64gb", "list_time": None}, {"id": 2003, "subject": "iPhone 8 64gb", "list_time": "вчера"},
                  {"id": 2004, "subject": "iPhone 8 64gb", "list_time": "2026-10-28T13:59:00"}])
check("S нет даты / мусор / дата без часового пояса: ничего не отправлено", ad_msgs(res) == [], res["sent"])
check("S причина записана в журнал с номерами объявлений",
      "нет даты публикации: 1 (2002)" in res["stdout"] and "дата публикации повреждена: 2 (2003, 2004)" in res["stdout"], res["stdout"][-600:])
d, _ = ready()
res, st = run(d, [{"id": 2005, "subject": "iPhone 8 64gb", "list_time": str(int((T0 - 90) * 1000))}])
check("S unix-время в миллисекундах понимается: свежее объявление отправлено", len(ad_msgs(res)) == 1, res["stdout"][-300:])
d, _ = ready()
res, st = run(d, [{"id": 900, "subject": "iPhone 8 64gb", "age": 60}])
check("S поднятое старое объявление (номер меньше, чем у опубликованного 45 мин назад): не отправлено, в журнале — «поднятое»",
      ad_msgs(res) == [] and "старое объявление, поднятое заново: 1 (900)" in res["stdout"], res["stdout"][-400:])
d = fresh_dir()
run(d, [(1001, "iPhone 5s")], ref=False)
res, st = run(d, [{"id": 2006, "subject": "iPhone 8 64gb", "age": 60}], ref=False)
check("S новизну подтвердить нечем (нет опорных наблюдений): не отправлено, причина в журнале",
      ad_msgs(res) == [] and "новизну не подтвердить" in res["stdout"], res["stdout"][-400:])
d, _ = ready()
res, st = run(d, [], market={q: [{"id": 2007, "subject": "iPhone 8 64gb", "age": 30}] for q in ("iphone", "айфон", "apple")}, clock=T0)
check("S одна свежая публикация в трёх запросах — одно уведомление", len(ad_msgs(res)) == 1, len(ad_msgs(res)))
d, _ = ready()
res, st = run(d, [{"id": 2008, "subject": "iPhone 8 64gb", "lt": T0 - 3600, "price": 100}])
res, st = run(d, [{"id": 2008, "subject": "iPhone 8 64gb", "lt": T0 - 3600, "price": 120}], clock=T0 + 300)
rec = db(d)["ads"]["2008"]
check("S старое объявление с новой ценой не становится новой публикацией; в базе — история цены и пометка",
      ad_msgs(res) == [] and [h[1] for h in rec["price_hist"] if h[2] == "search"] == [100, 120] and "price_changed" in rec.get("flags", []), rec)
d, _ = ready()
run(d, [{"id": 2009, "subject": "iPhone 8 64gb", "lt": T0 - 3 * 3600}])
res, st = run(d, [{"id": 2009, "subject": "iPhone 8 64gb", "lt": T0 + 3540}], clock=T0 + 3600)
check("S то же объявление пришло с новой датой (база видела его раньше): не отправлено как «уже было в базе»",
      ad_msgs(res) == [] and "уже было в базе с более ранней датой: 1 (2009)" in res["stdout"]
      and len(db(d)["ads"]["2009"].get("list_time_hist", [])) == 1, res["stdout"][-400:])
d, _ = ready()
res, st = run(d, [{"id": 2010, "subject": "iPhone 8 64gb", "age": 270}], CARD_DELAY=40)
check("S разбор занял 40 с, к отправке объявлению 310 с: не отправлено, проверка прямо перед отправкой",
      ad_msgs(res) == [] and "к моменту отправки" in res["stdout"] and db(d)["ads"]["2010"]["notify"]["status"] == "expired", res["stdout"][-400:])
d, _ = ready()
res, st = run(d, [{"id": 2011, "subject": "iPhone 8 64gb", "age": 296}])
check("S до конца окна 4 с: карточка и фото пропускаются (не успеть), короткая оценка уходит вовремя",
      len(ad_msgs(res)) == 1 and not any(g.startswith("item:") for g in res["gets"]), res["gets"][-4:])
d, _ = ready()
res, st = run(d, [{"id": 2012, "subject": "iPhone 8 64gb", "age": 100}, {"id": 2013, "subject": "iPhone 7 32gb", "age": 200}], SEND_DELAY=210)
check("S долгая отправка первого сообщения (210 с): второе к этому моменту устарело и не отправлено; первым шло более старое",
      len(ad_msgs(res)) == 1 and "iPhone 7" in ad_msgs(res)[0] and db(d)["ads"]["2012"]["notify"]["status"] == "expired",
      [m[:30] for m in ad_msgs(res)])

# ---------- S0. первый запуск: безопасное заполнение опорных меток ----------
p1 = [{"id": 6100 + i, "subject": "iPhone 8 64gb", "age": 10 + i * 5} for i in range(30)]     # свежие (в т.ч. уже существующие)
p2 = [{"id": 6000 + i, "subject": "iPhone 7 32gb", "age": 200 + i * 5} for i in range(30)]   # ещё «в окне»
p3 = [{"id": 5900 + i, "subject": "iPhone 6s 32gb", "age": 2400 + i * 60} for i in range(30)]  # 40–70 минут назад
d = fresh_dir()
res, st = run(d, [], pages={"iphone": [p1, p2, p3]}, ref=False, MAX_PAGES="1")
check("S0 первый запуск: существующие свежие объявления не рассылаются массово (0 уведомлений), метки дочитаны",
      ad_msgs(res) == [] and "Опорные метки: дочитал" in res["stdout"] and "покрытие есть" in res["stdout"]
      and any(g.startswith("iphone|50|") for g in res["gets"]), res["stdout"][-500:])
res, st = run(d, [], pages={"iphone": [[{"id": 6200, "subject": "iPhone X 64gb", "age": 30}] + p1, p2, p3]}, ref=False, MAX_PAGES="1", clock=T0 + 60)
check("S0 следующий запуск: настоящая новинка (номер больше всех) приходит — первый запуск не блокирует новые публикации",
      len(ad_msgs(res)) == 1 and "6200" in ad_msgs(res)[0], (res["stdout"][-500:], [m[:40] for m in ad_msgs(res)]))
check("S0 …а свежие объявления, висевшие в выдаче в момент первого запуска (61xx), не рассылаются и во втором",
      not any("item/61" in m for m in ad_msgs(res)), [m[-40:] for m in ad_msgs(res)])

# ---------- A. обновление со старого seen.json ----------
d = fx()
ads = [(i, "iPhone 6") for i in OLD_IDS[:2]] + [(1088901001, "iPhone 7 32gb"), (1088901002, "Чехол iPhone 7"), (1088901003, "iPhone 14 Pro"),
                                                (1088901004, "iPhone 6s 16gb"), {"id": 1088901005, "subject": "Samsung Galaxy S9", "price": 200}]
res, st = run(d, ads, REF_ID="1088900000")
msgs = ad_msgs(res)
check("A уведомления: 7, 6s, S9 (без чехла и iPhone 14, без старых)", len(msgs) == 3 and any("iPhone 7 32" in m or "iPhone 7" in m for m in msgs)
      and any("iPhone 6s" in m for m in msgs) and any("Galaxy S9" in m for m in msgs), [m[:40] for m in msgs])
check("A разовое уведомление об обновлении (про 5 минут)", sum("Бот обновлён" in m and "5 минут" in m for m in res["sent"]) == 1)
check("A ключи состояния", set(st) >= {"seen", "history", "market", "baseline", "notice", "pending", "marks"}, list(st))
check("A старые id и история сохранены", set(OLD_IDS) <= seen_ids(st) and set(OLD_HIST) <= set(st["history"]))
check("A отправленные — в seen, аксессуары и неподдерживаемые модели — нет",
      {1088901001, 1088901004, 1088901005} <= seen_ids(st) and not ({1088901002, 1088901003} & seen_ids(st)), seen_ids(st))
check("A база рынка создана, отправленные помечены sent", all(db(d)["ads"][str(i)]["notify"]["status"] == "sent" for i in (1088901001, 1088901004, 1088901005)))
check("A нет временных файлов", not (d / "seen.json.tmp").exists() and not (d / "market_history.json.tmp").exists())
res2, st2 = run(d, ads, REF_ID="1088900000", clock=T0 + 60)
check("A повторный запуск: тишина, уведомление не повторяется", res2["exit"] == 0 and res2["sent"] == [] and res2["plain"] == [], res2["sent"])

d = fresh_dir()
(d / "seen.json").write_text(json.dumps([1, 2, 3]))
res, st = run(d, [(1, "iPhone 5s"), (1004, "iPhone 8")])
check("A2 старейший формат (список id) читается, свежее приходит", res["exit"] == 0 and len(ad_msgs(res)) == 1 and isinstance(st, dict)
      and {1, 2, 3, 1004} <= seen_ids(st))

# ---------- B. несовпадение seen.json и базы ----------
d, _ = ready()
state = db(d)
state["ads"]["3001"] = {"first_seen": int(T0) - 100, "notify": {"status": "sent", "t": int(T0) - 100}, "url": "u"}
(d / "market_history.json").write_text(json.dumps(state))
res, st = run(d, [{"id": 3001, "subject": "iPhone 8 64gb", "age": 30}])
check("B в базе «отправлено», в seen.json нет — повторно не отправляется", ad_msgs(res) == [], res["sent"])
d, st0 = ready()
st0["seen"]["3002"] = int(T0) - 100
(d / "seen.json").write_text(json.dumps(st0))
res, st = run(d, [{"id": 3002, "subject": "iPhone 8 64gb", "age": 30}])
check("B в seen.json есть, в базе нет — не отправляется, запись в базе появляется", ad_msgs(res) == [] and "3002" in db(d)["ads"], res["sent"])

# ---------- C. аналоги, кеш и база рынка ----------
comps = [{"id": 1100 + i, "subject": "iPhone 11 64gb", "price": 600 + i * 10, "age": 86400 * (1 + i % 3)} for i in range(12)]
d, _ = ready()
res, st = run(d, [{"id": 5000, "subject": "iPhone 11 64gb", "price": 590, "desc": "Идеальное состояние, акб 90%, полный комплект"}],
              market={"iphone 11": comps})
m = (ad_msgs(res) or [""])[0]
check("C короткое сообщение: оценка рынка, максимум покупки, прибыль, вердикт, уверенность",
      all(x in m for x in ("<b>РЫНОК</b>", "Перепродажа:", "Цена для быстрой продажи:", "Сопоставимых объявлений:", "<b>ПОКУПКА</b>",
                          "Максимальная цена покупки:", "Желательно купить за:", "Предполагаемая прибыль после расходов:",
                          "Доходность на вложенные деньги:", "<b>ИТОГ</b>", "Уверенность:", "не сделок")), m)
check("C описание продавца не пересказывается", "полный комплект" not in m and "Идеальное" not in m, m)
check("C одна загрузка аналогов", sum(g == "iphone 11|100" for g in res["gets"]) == 1)
check("C кеш аналогов сохранён", "iPhone 11" in st["market"] and len(st["market"]["iPhone 11"]["items"]) >= 10)
rec = db(d)["ads"]
check("C аналоги попали в базу рынка с моделью и ценой", all(str(1100 + i) in rec and rec[str(1100 + i)]["key"] == "iPhone 11" for i in range(12)))
check("C в базе у отправленного объявления: оценка с аналогами, аккумулятор и комплект — со ссылкой на источник",
      rec["5000"]["appraisals"] and rec["5000"]["appraisals"][-1]["comps"] and rec["5000"]["battery"] == {"pct": 90, "src": "текст продавца"}
      and rec["5000"]["kit"]["src"] == "текст продавца" and rec["5000"]["kit"]["photo_confirmed"] is False, rec["5000"])
res2, st2 = run(d, [{"id": 5001, "subject": "iPhone 11 64gb", "price": 700}], market={"iphone 11": comps}, clock=T0 + 60)
check("C второй запуск: свежий кеш, повторной загрузки нет", sum(g == "iphone 11|100" for g in res2["gets"]) == 0 and len(ad_msgs(res2)) == 1)
state = json.loads((d / "seen.json").read_text())
state["market"] = {}
(d / "seen.json").write_text(json.dumps(state))
res3, st3 = run(d, [{"id": 5002, "subject": "iPhone 11 64gb", "price": 640}], fail=["iphone 11"], clock=T0 + 120)
m3 = (ad_msgs(res3) or [""])[0]
check("C кеша нет и Куфар не отдал аналоги — оценка по базе рынка (не «аналоги не загружены»)",
      len(ad_msgs(res3)) == 1 and "Максимальная цена покупки" in m3 and "не загружены" not in m3, m3)

# ---------- D. сбои Telegram ----------
d, _ = ready()
res, st = run(d, [{"id": 9101, "subject": "iPhone 8 64gb", "age": 60}], tg="500")
check("D Telegram 500: не помечено отправленным, лежит в очереди, в базе — failed",
      res["exit"] == 0 and 9101 not in seen_ids(st) and "9101" in st["pending"] and db(d)["ads"]["9101"]["notify"]["status"] == "failed", st["pending"].keys())
res, st = run(d, [], tg="ok", clock=T0 + 360)
check("D через 6 минут очередь не отправляет устаревшее; очередь пуста, в базе — expired",
      ad_msgs(res) == [] and st["pending"] == {} and db(d)["ads"]["9101"]["notify"]["status"] == "expired", (res["sent"], st["pending"]))
d, _ = ready()
res, st = run(d, [(9102, "iPhone 8 64gb")], tg="400parse")
check("D ошибка разметки: ушёл простой текст, объявление отмечено", res["plain"] and "<b>" not in res["plain"][0] and 9102 in seen_ids(st))
d, _ = ready()
res, st = run(d, [(9103, "iPhone 8 64gb")], tg="400chat")
check("D «chat not found»: объявление не теряется (в очереди)", 9103 not in seen_ids(st) and "9103" in st["pending"])
d, _ = ready()
res, st = run(d, [(9104, "iPhone 8 64gb")], tg="429once")
check("D лимит Telegram 429: повтор после паузы, сообщение доставлено", len(ad_msgs(res)) == 1 and 9104 in seen_ids(st), (res["tg_calls"], res["sent"]))

# ---------- E. очередь повторов ----------
d, _ = ready()
run(d, [{"id": 9201, "subject": "iPhone 8 64gb", "age": 30}], tg="500")
res, st = run(d, [], tg="ok", clock=T0 + 90)  # объявление уже пропало из выдачи, но ещё свежее (120 с)
check("E повтор, пока свежее: доставлено, хотя в выдаче его уже нет", len(ad_msgs(res)) == 1 and 9201 in seen_ids(st) and st["pending"] == {},
      (res["sent"][:1], st["pending"].keys()))
res, st = run(d, [], tg="ok", clock=T0 + 150)
check("E после доставки повторов нет", ad_msgs(res) == [])
d, _ = ready()
res, st = run(d, [{"id": 9203, "subject": "iPhone 8 64gb", "age": 30}], RUN_BUDGET_S="-1")  # часы подменены и стоят: бюджет «в прошлом»
check("E не хватило времени запуска: объявление в очереди, не в seen", ad_msgs(res) == [] and 9203 not in seen_ids(st) and "9203" in st["pending"])
res, st = run(d, [], tg="ok", clock=T0 + 60)
check("E следующий запуск через минуту его отправляет (ещё свежее)", len(ad_msgs(res)) == 1 and 9203 in seen_ids(st))

# ---------- F. повторы запросов с паузой, пагинация ----------
d, _ = ready()
res, st = run(d, [(9301, "iPhone 8 64gb")], flaky={"iphone": [503, "conn"]})
check("F два сбоя подряд, потом успех: запрос повторён и объявление пришло", len(ad_msgs(res)) == 1 and sum(g.startswith("iphone|") for g in res["gets"]) == 3,
      [g for g in res["gets"] if g.startswith("iphone|")])
d, _ = ready()
res, st = run(d, [(9302, "iPhone 8 64gb")], flaky={"iphone": [429, 429, 429, 429]})
check("F запрос стабильно падает: 3 попытки, остальные запросы работают, exit 0", res["exit"] == 0 and sum(g.startswith("iphone|") for g in res["gets"]) == 3
      and len(ad_msgs(res)) == 1, [g for g in res["gets"] if g.startswith("iphone|")])
d, _ = ready()
page1 = [{"id": 9400 + i, "subject": "Чехол iPhone", "age": 10 + i} for i in range(30)]
page2 = [{"id": 9450, "subject": "iPhone 8 64gb", "age": 100}, {"id": 1000, "subject": "Чехол", "age": 2700}]
res, st = run(d, [], pages={"iphone": [page1, page2, [{"id": 9460, "subject": "iPhone 7", "age": 9000}]]}, QUERIES="iphone", EXTRA_QUERIES="")
check("F свежее объявление на второй странице выдачи найдено и отправлено; третья (старая) не запрашивается",
      len(ad_msgs(res)) == 1 and "9450" in ad_msgs(res)[0] and "iphone|30|1" in res["gets"] and "iphone|30|2" not in res["gets"],
      [g for g in res["gets"] if g.startswith("iphone")])

# ---------- G. «ядовитые» объявления ----------
d, _ = ready()
now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(T0 - 60))
raw = [{"ad_id": 8001, "type": "sell", "subject": None, "price_byn": "abc", "ad_parameters": None, "ad_link": "x", "list_time": now_iso},
       {"type": "sell", "subject": "iPhone 8"}, {"ad_id": None, "type": "sell", "subject": "iPhone 8 plus"},
       {"ad_id": 8003, "type": "sell", "subject": "iPhone 8 64gb", "price_byn": None, "price_usd": None, "list_time": now_iso,
        "ad_parameters": [None, "x", {"p": "region", "vl": None}], "ad_link": "https://www.kufar.by/item/8003"},
       {"ad_id": 8004, "type": "sell", "subject": ["не", "строка"], "ad_parameters": [], "ad_link": "x", "list_time": now_iso},
       {"ad_id": "мусор", "type": "sell", "subject": "iPhone 8", "list_time": now_iso}]
res, st = run(d, [], raw=raw)
check("G странные объявления не роняют запуск; нормальное с пустой ценой пришло с «нужно уточнить»",
      res["exit"] == 0 and len(ad_msgs(res)) == 1 and "не указана — нужно уточнить" in ad_msgs(res)[0], res["sent"])
check("G мусор не занимает память", 8003 in seen_ids(st) and not ({8001, 8004} & seen_ids(st)), seen_ids(st))
res2, st2 = run(d, [], raw=raw, clock=T0 + 30)
check("G повторный запуск: тишина", ad_msgs(res2) == [])

# ---------- H. карточка: описание, цена, лимиты ----------
d, _ = ready()
body = "Продам iPhone 11 Pro Max. Использовался аккуратно женой.\nВсё родное, без ремонтов и вскрытий.\nБЕЗ ОБМЕНА И ТОРГА! Разбит экран."
res, st = run(d, [{"id": 9501, "subject": "iPhone 11 Pro Max", "price": 420}, {"id": 9404, "subject": "iPhone 11"}], bodies={"9501": body})
m = [x for x in ad_msgs(res) if "Pro Max" in x]
rec9501 = (db(d) or {"ads": {}})["ads"].get("9501") or {}
check("H описание подтянуто из карточки: дефект экрана из полного текста учтён (в базе — со ссылкой на текст продавца), "
      "описание в сообщении не пересказано и отдельного раздела «по описанию» нет",
      m and "screen" in (rec9501.get("defects") or {}) and rec9501.get("defects_src") == "текст продавца"
      and "женой" not in m[0] and "По описанию" not in m[0], (m[:1], rec9501.get("defects")))
m2 = [x for x in ad_msgs(res) if "<b>iPhone 11" in x and "Pro" not in x]
check("H карточка 404: сообщение всё равно пришло", bool(m2), [x[:40] for x in ad_msgs(res)])
d, _ = ready()
res, st = run(d, [{"id": 9502, "subject": "iPhone 8 64gb", "price": 100}], cards={"9502": {"body": "Всё работает", "price_byn": "12000"}})
check("H цена в карточке (120, как на странице) отличается от выдачи (100): расчёт по карточке, расхождение — в сообщении и в журнале",
      ad_msgs(res) and "Цена продавца: 120 BYN" in ad_msgs(res)[0] and "⚠️ Цена в поиске 100 BYN, на странице объявления — 120 BYN" in ad_msgs(res)[0]
      and "выдача price_byn='10000', карточка price_byn='12000'" in res["stdout"] and "РАСХОДЯТСЯ" in res["stdout"], res["stdout"][-600:])
many = [(9600 + i, "iPhone 8 64gb") for i in range(8)]
d, _ = ready()
res, st = run(d, many, card="500")
fetched = {g for g in res["gets"] if g.startswith("item:")}
check("H карточки не отвечают: после 3 неудач подряд запросы прекращаются, все сообщения пришли", len(ad_msgs(res)) == 8 and len(fetched) <= 3, (len(ad_msgs(res)), fetched))
d, _ = ready()
res, st = run(d, many, MAX_CARD_FETCH="2")
check("H лимит карточек за запуск (2)", len({g for g in res["gets"] if g.startswith("item:")}) == 2 and len(ad_msgs(res)) == 8)

# ---------- P. параллельный запуск и ошибки базы ----------
d, _ = ready()
before = (d / "seen.json").read_text()
fh = open(d / ".kufar_bot.lock", "w")
fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
res, st = run(d, [{"id": 9701, "subject": "iPhone 8 64gb", "age": 30}])
fcntl.flock(fh, fcntl.LOCK_UN)
fh.close()
check("P вторая копия бота при работающей первой: ничего не шлёт и не пишет", res["exit"] == 0 and ad_msgs(res) == []
      and (d / "seen.json").read_text() == before and "Другая копия" in res["stdout"], res["stdout"][-300:])
d, _ = ready()
(d / "market_history.json").write_text("{повреждённый файл")
res, st = run(d, [{"id": 9702, "subject": "iPhone 8 64gb", "age": 30}])
check("P база повреждена, резервная копия цела: восстановление из копии, уведомление пришло, база снова читается",
      len(ad_msgs(res)) == 1 and 9702 in seen_ids(st) and "1001" in db(d)["ads"] and "9702" in db(d)["ads"]
      and "восстанавливаю из резервной копии" in res["stdout"], res["stdout"][-400:])
d, _ = ready()
(d / "market_history.json").write_text("{повреждённый файл")
(d / "market_history.backup.json").write_text("{и копия тоже")
res, st = run(d, [{"id": 9702, "subject": "iPhone 8 64gb", "age": 30}])
check("P повреждены и база, и копия: уведомление всё равно пришло, seen.json записан, файлы не перезаписаны",
      len(ad_msgs(res)) == 1 and 9702 in seen_ids(st) and (d / "market_history.json").read_text() == "{повреждённый файл"
      and (d / "market_history.backup.json").read_text() == "{и копия тоже" and "повреждена" in res["stdout"], res["stdout"][-400:])
d, _ = ready()
db_before = (d / "market_history.json").read_text()
(d / "market_history.json.tmp").mkdir()  # запись временного файла не удастся
res, st = run(d, [{"id": 9703, "subject": "iPhone 8 64gb", "age": 30}])
check("P ошибка сохранения базы: запуск не падает, уведомление учтено в seen.json, прежний файл базы цел",
      res["exit"] == 0 and len(ad_msgs(res)) == 1 and 9703 in seen_ids(st) and (d / "market_history.json").read_text() == db_before
      and "База рынка не сохранена" in res["stdout"], res["stdout"][-400:])
res, st = run(d, [{"id": 9703, "subject": "iPhone 8 64gb", "age": 30}], clock=T0 + 30)
check("P …и при следующем запуске то же объявление не приходит повторно (seen.json)", ad_msgs(res) == [])

# ---------- I. тестовый запуск ----------
d = fx()
before = (d / "seen.json").read_bytes()
res, st = run(d, [(OLD_IDS[0], "iPhone 8 64gb"), (1088909701, "iPhone 11 128gb"), (1088909702, "Чехол iPhone 7")], argv=("--dry-run",),
              TG_TOKEN="", TG_CHAT_ID="", REF_ID="1088900000")
check("I тестовый запуск: exit 0 без токена, в Telegram ничего не ушло", res["exit"] == 0 and res["sent"] == [] and res["plain"] == [] and res["tg_calls"] == 0, res)
check("I сообщения показаны в логе (в т.ч. уже виденное), без аксессуара; для каждого — ушло бы или нет и почему",
      res["stdout"].count("ТЕСТОВЫЙ ЗАПУСК: в Telegram НЕ отправлено") == 2 and "iPhone 11" in res["stdout"] and "Чехол" not in res["stdout"]
      and "УШЛО БЫ в Telegram" in res["stdout"] and "не ушло бы: уже отправлено" in res["stdout"], res["stdout"][-800:])
check("I сводка свежести по выдаче", "Свежесть подходящих объявлений в выдаче:" in res["stdout"])
check("I seen.json не изменился, база не создана", (d / "seen.json").read_bytes() == before and db(d) is None)
d = fx()
before = (d / "seen.json").read_bytes()
res, st = run(d, [(1088909703, "iPhone 8 64gb")], argv=("--once",), DRY_RUN="true", REF_ID="1088900000")
check("I DRY_RUN=true работает как --dry-run", res["tg_calls"] == 0 and "ТЕСТОВЫЙ ЗАПУСК" in res["stdout"] and (d / "seen.json").read_bytes() == before)
res, st = run(d, [(1088909704, "iPhone 8 64gb"), (1088909705, "iPhone 7 32gb")], argv=("--dry-run",), DRY_RUN_LIMIT="1", REF_ID="1088900000")
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
