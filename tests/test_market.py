"""База рынка, которая улучшает оценки со временем (без сети, Telegram и нейросети; часы подменены; никаких случайных чисел):
процесс A (только свежее → Telegram) и процесс B (сбор рынка → база), повторные наблюдения без дублей, история цен с датами,
использование накопленных данных в следующей оценке, свежие против устаревших, разные модели/состояния не смешиваются,
исчезновение ≠ продажа, сохранение/восстановление между запусками, сбой сохранения, воспроизводимость, поправка прогноза
по истории цен и по подтверждённым сделкам, сверка прошлых прогнозов, недельная история, статистика базы."""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fresh_dir  # noqa: E402

D = fresh_dir()
sys.path.insert(0, str(D))
sys.argv = ["kufar_bot.py", "--once"]
import kufar_bot as k  # noqa: E402

LOGS = []
k.log = lambda *a: LOGS.append(" ".join(str(x) for x in a))
T0 = 1_793_196_000.0
NOW = [T0]
time.time = lambda: NOW[0]
time.sleep = lambda s: NOW.__setitem__(0, NOW[0] + max(0.0, float(s)))
k.KUFAR_PAUSE = k.SEND_PAUSE = 0.0
k.SEEN_FILE, k.MARKET_DB_FILE, k.MARKET_DB_BACKUP, k.DEALS_FILE = (D / "seen.json", D / "market_history.json",
                                                                   D / "market_history.backup.json", D / "deals.json")
bad = 0


def check(name, cond, extra=""):
    global bad
    print(("OK  " if cond else "FAIL"), name, "" if cond else extra)
    bad += 0 if cond else 1


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ad(ad_id, title="iPhone X 64gb", price=200, age=3600, desc="Всё работает", region="Минск", card=True):
    a = {"ad_id": ad_id, "type": "sell", "subject": title, "price_byn": str(int(price * 100)), "price_usd": "0", "currency": "BYR",
         "list_time": iso(NOW[0] - age), "ad_link": f"https://www.kufar.by/item/{ad_id}", "body_short": desc or None,
         "ad_parameters": [{"p": "condition", "vl": "Б/у"}, {"p": "region", "vl": region}]}
    if card:
        a["_price_src"] = k.PRICE_SRC_CARD
    return a


def reset_all():
    k.mdb_reset()
    k.STATE.update(market={}, baseline=[], pending={}, marks={}, notice=k.NOTICE_VERSION)
    k.HISTORY.clear()
    WORLD.clear()  # подменённая выдача из прошлого раздела не должна попадать в следующий
    for f in (k.SEEN_FILE, k.MARKET_DB_FILE, k.MARKET_DB_BACKUP, k.DEALS_FILE):
        if f.exists():
            f.unlink()
    NOW[0] = T0


# ---------------------------------------------------------------------------------------------------------------------
# 1. Процесс A и B в одном запуске: всё подходящее — в базу, в Telegram — только свежее
# ---------------------------------------------------------------------------------------------------------------------
WORLD = {}  # запрос -> список объявлений
reset_all()
SENT = []
k.fetch = lambda q, size=30, cursor=None: [dict(a) for a in WORLD.get(q, WORLD.get("*", []))]
k.fetch_card = lambda i: {}
k.tg_send = lambda text, parse_mode="HTML": SENT.append(text)
ref = {"ad_id": 1000, "type": "sell", "subject": "Чехол для iPhone", "price_byn": "1000", "list_time": iso(T0 - 2700), "ad_parameters": []}
old_ad = ad(1100, price=210, age=3 * 86400, card=False)
fresh_ad = ad(1200, price=190, age=40, card=False)
WORLD["*"] = [fresh_ad, old_ad, ref]
seen = k.Seen()
k.cycle(seen, False)
rec_old, rec_new = k._mdb_ads().get("1100"), k._mdb_ads().get("1200")
check("1 оба объявления попали в базу (процесс B), в Telegram — только свежее (процесс A)",
      rec_old and rec_new and len(SENT) == 1 and "item/1200" in SENT[0] and not any("item/1100" in m for m in SENT), (len(SENT), list(k._mdb_ads())[:5]))
check("1 у свежего — пометка «публикация проверена» с честным основанием; у старого её нет",
      "publication" in rec_new and "не дата первой публикации" in rec_new["publication"]["basis"] and "publication" not in rec_old)
check("1 у записи: категория состояния с уверенностью и источником, самое раннее размещение",
      rec_new["condition_cat"]["cat"] == "ok" and rec_new["condition_cat"]["conf"] == "средняя" and rec_new["condition_cat"]["src"].startswith("текст")
      and rec_new["first_list_time"] == iso(T0 - 40), rec_new.get("condition_cat"))

# ---------------------------------------------------------------------------------------------------------------------
# 2. Повторное наблюдение обновляет запись; история цены — все изменения с датами
# ---------------------------------------------------------------------------------------------------------------------
n_before = len(k._mdb_ads())
for i, (dt, pr) in enumerate(((3600, 200), (7200, 200), (10800, 180), (14400, 170))):
    NOW[0] = T0 + dt
    k.mdb_observe(ad(1100, price=pr, age=3 * 86400 + dt, card=False), now=NOW[0])  # тот же источник, что в запуске (выдача)
r = k._mdb_ads()["1100"]
check("2 повторные наблюдения — та же запись, дубликатов нет", len(k._mdb_ads()) == n_before)
check("2 история цены хранит все настоящие изменения с датами: 210 → 200 → 180 → 170 (повтор 200 не дублируется)",
      [h[1] for h in r["price_hist"]] == [210, 200, 180, 170] and [h[0] for h in r["price_hist"]][1:] == [int(T0 + 3600), int(T0 + 10800), int(T0 + 14400)]
      and k.price_changes(r["price_hist"]) == 3, r["price_hist"])
NOW[0] = T0

# ---------------------------------------------------------------------------------------------------------------------
# 3. Следующая оценка использует ранее собранные данные; устаревшие не перевешивают; модели и состояния не смешиваются
# ---------------------------------------------------------------------------------------------------------------------
reset_all()
for i in range(8):  # активные исправные iPhone X 64: 200…270
    k.mdb_observe(ad(2000 + i, price=200 + i * 10), now=T0 - 3600)
for i in range(6):  # давно не наблюдавшиеся — дороже (400, в пределах фильтра выбросов), должны остаться только историей
    k.mdb_observe(ad(2100 + i, price=400), now=T0 - 6 * 86400)
for i in range(5):  # другая модель — iPhone 8
    k.mdb_observe(ad(2200 + i, "iPhone 8 64gb", price=90), now=T0 - 3600)
for i in range(4):  # тот же iPhone X, но с разбитым экраном
    k.mdb_observe(ad(2300 + i, "iPhone X 64gb разбит экран", price=110 + i, desc="Разбит экран"), now=T0 - 3600)
target = ad(2999, price=150, age=60)
f = k.rule_facts(target)
ap1 = k.appraise(target, f)
check("3 следующая оценка построена на ранее собранных наблюдениях (выдачи по модели нет, кеш пуст): статус ok, аналоги из базы",
      ap1["status"] == "ok" and ap1["db_comps"] >= 8 and ap1["stats"]["n"] >= 5, (ap1["status"], ap1.get("db_comps"), (ap1.get("stats") or {}).get("n")))
ms = ap1["market"]
check("3 устаревшие (400 BYN, 6 дней назад) не перевешивают свежие: в расчёте только активные (≤ 270), история — отдельно (медиана 400)",
      ms["med"] < 300 and ap1["history"] and ap1["history"]["med"] == 400 and max(ap1["plan"]["asis"]["st"]["prices"]) <= 270
      and ap1["plan"]["asis"]["st"]["n"] == 8,
      (ms.get("med"), ap1.get("history")))
check("3 разные модели не смешиваются: iPhone 8 (90 BYN) не попал в сводку и аналоги iPhone X",
      all(it[0] < 2200 or it[0] >= 2300 for it in k.mdb_comps("iPhone X", T0)) and ms["n"] == 12, (ms["n"], [it[0] for it in k.mdb_comps("iPhone X", T0)]))
check("3 разные состояния не смешиваются: оценка исправного — по исправным, телефоны с разбитым экраном отдельно в сводке",
      min(ap1["plan"]["asis"]["st"]["prices"]) >= 200 and ms["by_cat"]["visible"]["n"] == 4
      and (ms["clean_vs_defect"] or 0) > 0, (ap1["plan"]["asis"]["st"]["prices"], ms["by_cat"]))
fd = k.rule_facts(ad(2998, "iPhone X 64gb", price=80, desc="Разбит экран"))
apd = k.appraise(ad(2998, price=80, desc="Разбит экран"), fd)
check("3 телефон с разбитым экраном оценён по аналогам с таким же дефектом, а не по исправным", apd["basis"] == "defect"
      and max(apd["stats"]["prices"]) < 200, (apd.get("basis"), (apd.get("stats") or {}).get("prices")))
reset_all()
for i in range(3):
    k.mdb_observe(ad(2400 + i, price=200 + i * 10), now=T0 - 3600)
ap_few = k.appraise(ad(2499, price=150, age=60), k.rule_facts(ad(2499, price=150, age=60)))
check("3 мало аналогов (3): уверенность низкая / решения нет, база не подмешала устаревшие для количества",
      ap_few["status"] == "few" or ap_few.get("conf") == "низкая", (ap_few["status"], ap_few.get("conf")))

# ---------------------------------------------------------------------------------------------------------------------
# 4. Исчезновение ≠ продажа; сверка прошлого прогноза при изменении цены
# ---------------------------------------------------------------------------------------------------------------------
reset_all()
for i in range(8):
    k.mdb_observe(ad(3000 + i, price=200 + i * 10), now=T0 - 3600)
t_ad = ad(3100, price=160, age=60)
ft = k.rule_facts(t_ad)
apt = k.appraise(t_ad, ft)
k.mdb_observe(t_ad, facts=ft, now=T0, checked=True)
k.mdb_appraisal(3100, ft, apt, now=T0)
NOW[0] = T0 + 2 * 86400
k.mdb_observe(ad(3100, price=140, age=60 + 2 * 86400), now=NOW[0])
r = k._mdb_ads()["3100"]
fc = r.get("forecast_checks") or []
check("4 цена изменилась после оценки: записана сверка с прогнозом (было 160 → стало 140, прогноз и максимум покупки)",
      len(fc) == 1 and fc[0]["price_before"] == 160 and fc[0]["price_after"] == 140 and fc[0]["max_buy"] == r["appraisals"][-1]["max_buy"]
      and "не цена сделки" in fc[0]["note"], fc)
NOW[0] = T0 + 10 * 86400
k.mdb_save(NOW[0])
data = json.loads(k.MARKET_DB_FILE.read_text())
check("4 объявление исчезло из выдачи: статус not_seen, нигде нет «продано/sold»",
      data["ads"]["3100"]["status"] == "not_seen" and "sold" not in json.dumps(data).lower() and "продан" not in json.dumps(data).lower())
NOW[0] = T0

# ---------------------------------------------------------------------------------------------------------------------
# 5. Сохранение и восстановление между запусками (как в GitHub Actions: новый процесс читает файл из репозитория)
# ---------------------------------------------------------------------------------------------------------------------
reset_all()
for i in range(10):
    k.mdb_observe(ad(4000 + i, price=200 + i * 5), now=T0 - 3600)
k.mdb_observe(ad(4000, price=190), now=T0)
ok1 = k.mdb_save(T0)
snapshot = json.loads(k.MARKET_DB_FILE.read_text())
k.mdb_reset()
k.mdb_load()
check("5 сохранено и прочитано заново: все записи, история цен и недельная сводка на месте",
      ok1 and set(k._mdb_ads()) == set(snapshot["ads"]) and k._mdb_ads()["4000"]["price_hist"] == snapshot["ads"]["4000"]["price_hist"]
      and k.MDB["data"]["weekly"], (ok1, len(k._mdb_ads())))
check("5 резервная копия записана вместе с первым сохранением суток", k.MARKET_DB_BACKUP.exists()
      and json.loads(k.MARKET_DB_BACKUP.read_text())["ads"].keys() == snapshot["ads"].keys())
wk_before = json.loads(json.dumps(k.MDB["data"]["weekly"]))
NOW[0] = T0 + 70 * 86400  # прошло 70 дней: записи удалятся, а недельная история — нет
k.mdb_save(NOW[0])
k.mdb_reset()
k.mdb_load()
NOW[0] += 300
k.mdb_save(NOW[0])  # ещё одно сохранение уже без записей: история не должна пропасть и потом
after = json.loads(k.MARKET_DB_FILE.read_text())
check("5 старые записи удалены по сроку, но их недельная история цен сохранилась (полезные наблюдения не потеряны)",
      wk_before and not after["ads"] and all(w in after["weekly"].get(kk, {}) for kk, ws in wk_before.items() for w in ws),
      (len(after["ads"]), list(after["weekly"])))
NOW[0] = T0
reset_all()
for i in range(5):
    k.mdb_observe(ad(4100 + i, price=200), now=T0)
k.mdb_save(T0)
good_text = k.MARKET_DB_FILE.read_text()
(D / "market_history.json.tmp").mkdir()
k.mdb_observe(ad(4200, price=300), now=T0 + 60)
ok_fail = k.mdb_save(T0 + 60)
(D / "market_history.json.tmp").rmdir()
check("5 сбой сохранения: функция сообщает о неудаче, прежний файл базы цел (старые данные не потеряны)",
      ok_fail is False and k.MARKET_DB_FILE.read_text() == good_text)

# ---------------------------------------------------------------------------------------------------------------------
# 6. Воспроизводимость: те же входные данные и та же версия базы → тот же результат
# ---------------------------------------------------------------------------------------------------------------------
reset_all()
for i in range(9):
    k.mdb_observe(ad(5000 + i, price=200 + i * 7), now=T0 - 3600)
k.mdb_save(T0)
t5 = ad(5999, price=170, age=60)
m1 = k.build_short_message(t5, k.rule_facts(t5), k.appraise(t5, k.rule_facts(t5)))
m2 = k.build_short_message(t5, k.rule_facts(t5), k.appraise(t5, k.rule_facts(t5)))
k.mdb_reset()
k.mdb_load()
m3 = k.build_short_message(t5, k.rule_facts(t5), k.appraise(t5, k.rule_facts(t5)))
check("6 повторная оценка тех же данных при той же базе даёт тот же результат (и после записи/чтения файла)", m1 == m2 == m3, (m1, m3))

# ---------------------------------------------------------------------------------------------------------------------
# 7. Поправка прогноза по накопленной истории (только реальные наблюдения, без случайных чисел)
# ---------------------------------------------------------------------------------------------------------------------
def history_of_drops(n, drop, start_id, key_title="iPhone X 64gb", base=220):
    """n объявлений, наблюдавшихся 4 дня: цена снизилась на долю drop (0 — не менялась)."""
    for i in range(n):
        k.mdb_observe(ad(start_id + i, key_title, price=base), now=T0 - 8 * 86400)
        k.mdb_observe(ad(start_id + i, key_title, price=round(base * (1 - drop))), now=T0 - 4 * 86400)


reset_all()
for i in range(8):
    k.mdb_observe(ad(6000 + i, price=200 + i * 10), now=T0 - 3600)
t7 = ad(6999, price=150, age=60)
base_ap = k.appraise(t7, k.rule_facts(t7))
check("7 истории мало (0 объявлений с 3+ днями наблюдения): поправки нет, это сказано",
      base_ap["plan"]["calib"]["factor"] == 1.0 and base_ap["plan"]["calib"]["src"] == "none" and "мало" in base_ap["plan"]["calib"]["text"])
history_of_drops(k.CALIB_MIN_ADS - 1, 0.10, 6100)
check("7 на одно объявление меньше порога (29): поправки по-прежнему нет", k.calibration("iPhone X", T0)["src"] == "none")
history_of_drops(11, 0.10, 6200)
cal = k.calibration("iPhone X", T0)
ap7 = k.appraise(t7, k.rule_facts(t7))
m7 = k.build_short_message(t7, k.rule_facts(t7), ap7)
check("7 40 объявлений в среднем подешевели на 10%: поправка ×0.90 по истории цен (модель)",
      cal["src"] == "drift" and cal["n"] == 40 and abs(cal["factor"] - 0.9) < 0.005 and cal["scope"] == "модель", cal)
check("7 поправка реально меняет расчёт: быстрая продажа и максимум покупки ниже, чем без истории (ровно ×0.9 до округления)",
      ap7["plan"]["A"]["quick"] == k.floor5(base_ap["plan"]["asis"]["quick"] * 0.9) and ap7["plan"]["A"]["limit"] < base_ap["plan"]["A"]["limit"],
      (base_ap["plan"]["A"]["quick"], ap7["plan"]["A"]["quick"]))
check("7 в коротком сообщении — одна пометка «поправка по истории цен −10%», без технической статистики",
      "поправка по истории цен −10%" in m7 and "База рынка" not in m7 and len(m7) < 1100, m7)
reset_all()
for i in range(8):
    k.mdb_observe(ad(6000 + i, price=200 + i * 10), now=T0 - 3600)
history_of_drops(40, 0.0, 6300)
check("7 цены не снижались (40 объявлений без изменений): поправка ×1.00, ничего не сдвигается",
      k.calibration("iPhone X", T0)["factor"] == 1.0 and k.appraise(t7, k.rule_facts(t7))["plan"]["A"]["quick"] == base_ap["plan"]["A"]["quick"])
reset_all()
history_of_drops(40, 0.6, 6400)
check("7 аномальное снижение (−60%) ограничено: поправка не ниже ×0.80", k.calibration("iPhone X", T0)["factor"] == 0.8)
reset_all()
history_of_drops(40, 0.10, 6500, "iPhone 8 64gb", base=100)
c_other = k.calibration("iPhone X", T0)
check("7 по самой модели истории нет — берётся общая по всем моделям, и это подписано", c_other["src"] == "drift" and c_other["scope"] == "все модели")
check("7 поправка детерминирована (одни данные — один результат)", k.calibration("iPhone X", T0) == k.calibration("iPhone X", T0))

# ---------------------------------------------------------------------------------------------------------------------
# 8. Подтверждённые сделки пользователя (deals.json) — отдельно от цен объявлений, приоритетнее истории
# ---------------------------------------------------------------------------------------------------------------------
reset_all()
for i in range(8):
    k.mdb_observe(ad(7000 + i, price=200 + i * 10), now=T0 - 3600)
history_of_drops(40, 0.10, 7100)
deals = []
for i in range(5):  # бот когда-то оценил объявления, пользователь купил и продал — фактическая продажа 0.8 от прогноза
    aid = 7500 + i
    a_ = ad(aid, price=150, age=60)
    f_ = k.rule_facts(a_)
    ap_ = k.appraise(a_, f_)
    k.mdb_observe(a_, facts=f_, now=T0, checked=True)
    k.mdb_appraisal(aid, f_, ap_, now=T0)
    q_raw = ap_["plan"]["A"]["quick"] / ap_["plan"]["calib"]["factor"]
    deals.append({"date": "2026-11-02", "ad_id": aid, "model": "iPhone X", "mem": 64, "buy_price": 150, "repair": 0, "costs": 5,
                  "sell_price": round(q_raw * 0.8, 2)})
deals.append({"date": "2026-11-03", "ad_id": 1, "sell_price": -5})  # ошибочная запись — пропускается
k.DEALS_FILE.write_text(json.dumps(deals), encoding="utf-8")
LOGS.clear()
cal8 = k.calibration("iPhone X", T0)
check("8 подтверждённые сделки (5): поправка по сделкам ×0.80 — приоритетнее истории цен; ошибочная запись пропущена с пометкой в журнале",
      cal8["src"] == "deals" and cal8["n"] == 5 and abs(cal8["factor"] - 0.8) < 0.01 and any("сделка №6 пропущена" in l for l in LOGS), (cal8, LOGS[-2:]))
check("8 сделки хранятся отдельно (deals.json), прибыль сделки посчитана из её цифр, а не взята из объявлений",
      len(k.load_deals()) == 5 and abs(k.load_deals()[0]["profit"] - (deals[0]["sell_price"] - 150 - 0 - 5)) < 1e-9
      and "deals" not in json.dumps(k.MDB["data"].get("ads", {})).lower().replace("price_sources_differ", ""))
k.DEALS_FILE.write_text(json.dumps(deals[:4]), encoding="utf-8")
check("8 сделок меньше порога (4): используется история цен, а не сделки", k.calibration("iPhone X", T0)["src"] == "drift")
k.DEALS_FILE.write_text("{не json", encoding="utf-8")
check("8 испорченный deals.json не роняет оценку: сделки не учитываются", k.load_deals() == [] and k.calibration("iPhone X", T0)["src"] == "drift")
k.DEALS_FILE.unlink()

# ---------------------------------------------------------------------------------------------------------------------
# 9. Процесс B: регулярное обновление аналогов без уведомлений; статистика базы — в журнал
# ---------------------------------------------------------------------------------------------------------------------
reset_all()
for key_, t_ in (("iPhone X", T0 - 30 * 3600), ("iPhone 8", T0 - 10 * 3600), ("Galaxy S9", T0 - 3600)):
    k.STATE["market"][key_] = {"t": int(t_), "items": []}
CALLS, SENT = [], []
WORLD.update({"iphone x": [ad(8000 + i, price=200 + i) for i in range(6)], "iphone 8": [ad(8100 + i, "iPhone 8 64gb", price=90 + i) for i in range(6)]})
k.fetch = lambda q, size=30, cursor=None: (CALLS.append((q, size)), [dict(a) for a in WORLD.get(q, [])])[1]
k.RUN["deadline"] = NOW[0] + 200
k.market_rotation(NOW[0])
check("9 сбор рынка обновил 2 самые давние модели (iPhone X, iPhone 8), свежую (Galaxy S9, 1 ч) не трогал, ничего не отправил",
      [c[0] for c in CALLS] == ["iphone x", "iphone 8"] and SENT == [] and all(str(8000 + i) in k._mdb_ads() for i in range(6)), CALLS)
CALLS.clear()
k.RUN["deadline"] = NOW[0] + 10
k.market_rotation(NOW[0])
check("9 если времени запуска почти не осталось, сбор рынка не начинается (уведомления важнее)", CALLS == [])
line = k.mdb_stats_line(NOW[0])
check("9 статистика базы для журнала: объявлений, обновлено за сутки, изменений цены, качественных аналогов, сделки, поправка",
      all(x in line for x in ("объявлений 12", "обновлено за сутки", "изменений цены", "качественных активных аналогов 12", "подтверждённых сделок 0", "поправки")), line)

# статистика для журнала: изменения «за сутки» — только смены цены внутри одного источника (живой журнал показал 14 всего / 61 за сутки)
k.mdb_reset()
k._mdb_ads()["1"] = {"key": "iPhone X", "price_hist": [[int(T0 - 100), 300, "search"], [int(T0 - 90), 100, "card"]], "last_seen": int(T0)}
k._mdb_ads()["2"] = {"key": "iPhone X", "price_hist": [[int(T0 - 3 * 86400), 200, "card"], [int(T0 - 50), 180, "card"]], "last_seen": int(T0)}
line = k.mdb_stats_line(T0)
check("статистика базы: «изменений цены всего 1 (за сутки 1)» — карточка после выдачи изменением не считается",
      "изменений цены всего 1 (за сутки 1)" in line, line)
print("итого ошибок (база рынка):", bad)
sys.exit(1 if bad else 0)
