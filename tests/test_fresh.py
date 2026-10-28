"""Проверки по списку требований: свежесть публикаций, цена, характеристики, финансовая оценка, база рынка.
Всё на фиктивных данных и подменённых часах: ни одного запроса к Куфару, нейросети или Telegram.
Сквозные сценарии (несколько запусков подряд, сбои, очередь повторов, параллельный запуск) — в test_cycle.py."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fresh_dir  # noqa: E402

D = fresh_dir()
sys.path.insert(0, str(D))
sys.argv = ["kufar_bot.py"]
for _k in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MESSAGE_STYLE", "REPAIR_COSTS", "EXTRA_COSTS_BYN", "TARGET_PROFIT_BYN"):
    os.environ.pop(_k, None)
import kufar_bot as k  # noqa: E402

k.log = lambda *a: None
T0 = 1_793_196_000.0  # 28.10.2026 14:00:00 UTC
NOW = [T0]
time.time = lambda: NOW[0]
bad = 0


def check(name, cond, extra=""):
    global bad
    print(("OK  " if cond else "FAIL"), name, "" if cond else extra)
    bad += 0 if cond else 1


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def ad(title="iPhone X 64gb", price=100, desc="", ad_id=5001, age=60, params=None, carded=True, **extra):
    """carded=True — как в работе бота: объявление уже сверено с карточкой (цена страницы). False — карточку не получили."""
    a = {"ad_id": ad_id, "type": "sell", "subject": title, "price_byn": None if price is None else str(int(price * 100)),
         "price_usd": "0", "ad_link": f"https://www.kufar.by/item/{ad_id}", "body_short": desc or None, "list_time": iso(T0 - age),
         "ad_parameters": (params or []) + [{"p": "condition", "vl": "Б/у"}, {"p": "region", "vl": "Минск"}]}
    if carded:
        a["_price_src"] = k.PRICE_SRC_CARD
    a.update(extra)
    return a


def market(key, items, age=0):
    k.STATE["market"][key] = {"t": int(T0 - age), "items": items}


CLEAN_X = [[2000 + i, 180 + i * 5, 64, 0, 1, 0] for i in range(10)]  # исправные iPhone X 64: 180…225
SCREEN_X = [[3000 + i, 110 + i * 5, 64, k.F_DEF | k.F_KINDS["screen"], 1, 0] for i in range(5)]  # с разбитым экраном: 110…130
market("iPhone X", CLEAN_X + SCREEN_X)


def evaluate(a):
    f = k.rule_facts(a)
    ap = k.appraise(a, f)
    return f, ap, k.build_short_message(a, f, ap)


# =====================================================================================================================
# 1. Свежесть
# =====================================================================================================================
lt = T0 - 60
DATE_CASES = [("2026-10-28T13:59:00Z", lt), ("2026-10-28T16:59:00+03:00", lt), (int(lt), lt), (str(int(lt)), lt), (int(lt * 1000), lt),
              (str(int(lt * 1000)), lt), (float(lt), lt), ("2026-10-28T13:59:00", None), ("", None), (None, None), ("вчера", None),
              ("0", None), (True, None), (-5, None), ("99999999999999", None), ([1, 2], None)]
for v, want in DATE_CASES:
    got = k.parse_list_time(v)
    check(f"дата {v!r} → {'не принимается' if want is None else 'принимается'}", got == want, got)

for age, ok in ((60, True), (4 * 60 + 59, True), (300, True), (300.001, False), (301, False), (86400, False), (-30, False)):
    res = k.fresh_status(ad(age=age))
    check(f"свежесть: {age} с → {'подходит' if ok else 'не подходит'} (граница 300 с включительно)", res[0] == ok, res)
res = k.fresh_status(ad(age=-3600))
check("свежесть: дата на час в будущем — повреждена, не свежая", res[0] is False and res[1] == "future", res)
res = k.fresh_status(ad(age=-30))
check("свежесть: дата на 30 с в будущем — недостоверна (future), не свежая", res[:2] == (False, "future"), res)
check("свежесть: дата на 3 с впереди — в отборе кандидат (погрешность часов), но перед отправкой строго нельзя (ahead)",
      k.fresh_status(ad(age=-3))[0] is True and k.fresh_status(ad(age=-3), strict=True)[:2] == (False, "ahead"))
_sleeps = []
_real_sleep = k.time.sleep
k.time.sleep = lambda x: (_sleeps.append(x), NOW.__setitem__(0, NOW[0] + x))
res = k.fresh_before_send(ad(age=-3))
k.time.sleep = _real_sleep
NOW[0] = T0
check("перед отправкой: дата на 3 с впереди — бот ждёт ≈3 с, и только когда возраст ≥ 0, отправка разрешена",
      res[0] is True and res[2] >= 0 and len(_sleeps) == 1 and 3 <= _sleeps[0] < 3.1, (res, _sleeps))
check("потолок возраста: больше 300 с поставить нельзя", k._env_range("X_NOT_SET", 300, 30, 300) == 300 and k.FRESH_MAX_AGE_S <= 300)
for raw, reason in ((None, "no_date"), ("", "no_date"), ("мусор", "bad_date"), ("2026-10-28T13:59:00", "bad_date")):
    a = ad()
    a["list_time"] = raw
    res = k.fresh_status(a)
    check(f"свежесть: list_time={raw!r} → не свежее ({reason})", res[0] is False and res[1] == reason, res)
a = ad()
a.pop("list_time")
check("свежесть: поля list_time нет вообще → не свежее", k.fresh_status(a)[:2] == (False, "no_date"))

marks = {}
k.marks_add(marks, [{"ad_id": 1091000000, "list_time": iso(T0 - 2700)}, {"ad_id": "мусор", "list_time": iso(T0)},
                    {"ad_id": 5, "list_time": "не дата"}])
check("метки: мусорные номера и даты пропускаются", len(marks) == 1, marks)
check("поднятое: номер меньше, чем у опубликованного 45 мин назад → bumped", k.originality(1080000000, T0 - 60, marks) == (False, "bumped"))
check("новое: номер больше → подтверждено", k.originality(1091950000, T0 - 60, marks) == (True, ""))
check("нет опорных наблюдений → не подтверждено", k.originality(1091950000, T0 - 60, {}) == (False, "unconfirmed"))
far = {}
k.marks_add(far, [{"ad_id": 1080000000, "list_time": iso(T0 - 3 * 86400)}])
check("опорное наблюдение трёхдневной давности новизну не подтверждает", k.originality(1091950000, T0 - 60, far) == (False, "unconfirmed"))
near = {}
k.marks_add(near, [{"ad_id": 1091949000, "list_time": iso(T0 - 600)}])
check("наблюдение 10 минут назад с большим номером — ещё не граница (допуск 30 мин): не «поднятое», но и не подтверждение",
      k.originality(1091948000, T0 - 60, near) == (False, "unconfirmed"))

seen = k.Seen()
k.mdb_reset()
k.STATE["marks"] = dict(marks)
fresh_ad = ad(ad_id=1091950001, age=30)
check("кандидат: свежее, новое, не отправлялось → ''", k.candidate_reason(1091950001, fresh_ad, seen, None) == "")
seen.add(1091950001)
check("кандидат: уже в seen.json → notified", k.candidate_reason(1091950001, fresh_ad, seen, None) == "notified")
k.mdb_note(1091950002, "sent")
check("кандидат: в базе отмечено «отправлено» → notified", k.candidate_reason(1091950002, ad(ad_id=1091950002, age=30), k.Seen(), None) == "notified")
check("кандидат: база видела объявление с датой на час раньше → republished",
      k.candidate_reason(1091950003, ad(ad_id=1091950003, age=30), k.Seen(), T0 - 3600) == "republished")
check("кандидат: та же дата, что в базе (прошлый запуск не смог отправить) → можно",
      k.candidate_reason(1091950004, ad(ad_id=1091950004, age=30), k.Seen(), T0 - 30) == "")

# =====================================================================================================================
# 2. Цена
# =====================================================================================================================
check("цена: копейки → BYN (10000 → 100)", k.price_byn({"price_byn": "10000"}) == 100.0)
check("цена: живой ответ Куфара: price_byn 40000 → 400 BYN, price_usd 13580 → $135.8",
      k.price_byn({"price_byn": "40000"}) == 400.0 and k.price_usd({"price_usd": "13580"}) == 135.8)
for raw in (None, "", "0", 0, "abc", "-500", -500, "1e400", True, [1], "nan"):
    check(f"цена: {raw!r} → 0 (не указана / некорректна)", k.price_byn({"price_byn": raw}) == 0, k.price_byn({"price_byn": raw}))
check("цена: число, а не строка (15000) → 150", k.price_byn({"price_byn": 15000}) == 150.0)
a100 = ad(price=100, desc="Отдам за 300, если быстро. Новый стоил 900.", price_usd="3400")
f100 = k.rule_facts(a100)
f100 = k.merge_llm(f100, {"price": 300, "price_byn": 300, "photos": {"findings": [], "kit_visible": [], "mismatch": "", "quality": "хорошее"}})
ap100 = k.appraise(a100, f100)
m100 = k.build_short_message(a100, f100, ap100)
check("цена 100 BYN не превращается в 300: ни описание («отдам за 300»), ни ответ нейросети с price=300 её не меняют",
      f100["price"] == 100 and "Цена продавца: 100 BYN" in m100 and "300 BYN" not in m100.split("\n")[1], m100[:200])
k.mdb_reset()
k.mdb_observe(ad(price=100, ad_id=7001), now=T0)
k.mdb_observe(ad(price=120, ad_id=7001), now=T0 + 3600)
k.mdb_observe(ad(price=120, ad_id=7001), now=T0 + 7200)
rec = k._mdb_ads()["7001"]
check("цена между запусками: история цены [100, 120] без повторов, исходные поля API сохранены",
      [h[1] for h in rec["price_hist"]] == [100, 120] and rec["price_byn"] == 120 and rec["price_raw"]["card"]["price_byn"] == "12000"  # наблюдения карточки (ad() по умолчанию сверено с карточкой)
      and k.price_changes(rec["price_hist"]) == 1, rec)
f0, ap0, m0 = evaluate(ad(price=None))
check("цена не указана: «нужно уточнить», прибыль не считается, вердикт НЕДОСТАТОЧНО ДАННЫХ",
      "не указана — нужно уточнить" in m0 and "Прибыль: цену нужно уточнить" in m0 and "НЕДОСТАТОЧНО ДАННЫХ" in m0
      and "Прибыль после расходов" not in m0, m0)
f0b, ap0b, m0b = evaluate(ad(price=0))
check("цена 0: то же, что «не указана»", f0b["price"] == 0 and "не указана — нужно уточнить" in m0b)

# воспроизведение «на странице 100 BYN, бот пишет 300 BYN»: поиск отстал от страницы (продавец снизил цену)
k.mdb_reset()
s300 = ad(price=300, ad_id=7201, desc="", carded=False)
k.mdb_observe(s300, now=T0 - 600)  # прошлое наблюдение из выдачи: 300
k.apply_card(s300, {"body": "Всё работает", "price_byn": "10000", "price_usd": "3400", "currency": "BYR", "list_time": s300["list_time"]})
f300 = k.rule_facts(s300)
ap300 = k.appraise(s300, f300)
m300 = k.build_short_message(s300, f300, ap300)
diag = k.price_diag(s300, k._mdb_ads().get("7201"))
check("100 vs 300: цена страницы (карточка) 100 BYN, а не 300 из выдачи; минимум не «выбирается» — источник обоснован",
      f300["price"] == 100 and f300["price_src"] == k.PRICE_SRC_CARD and "Цена продавца: 100 BYN" in m300, m300[:150])
check("100 vs 300: расхождение видно в сообщении одной строкой и в журнале — с исходными значениями поиска, карточки и базы",
      "⚠️ Цена в поиске 300 BYN, на странице объявления — 100 BYN" in m300 and "выдача price_byn='30000'" in diag
      and "карточка price_byn='10000'" in diag and "в базе: 300 BYN" in diag and "РАСХОДЯТСЯ" in diag and "TG_TOKEN" not in diag, (m300, diag))
k.mdb_observe(s300, facts=f300, now=T0)
r300 = k._mdb_ads()["7201"]
check("100 vs 300: в базе по записи на источник (выдача 300, карточка 100) — не «изменение цены»; текущая — карточка; расхождение сохранено",
      [h[1:] for h in r300["price_hist"]] == [[300, "search"], [100, "card"]] and r300["price_src"] == "карточка"
      and r300["price_conflict"]["search"] == 300 and r300["price_conflict"]["card"] == 100, r300)
s_eq = ad(price=150, ad_id=7202, carded=False)
k.apply_card(s_eq, {"price_byn": "15000", "body": "Всё ок"})
check("цены поиска и карточки совпадают: расхождения нет, источник — карточка", "_price_conflict" not in s_eq and s_eq["_price_src"] == k.PRICE_SRC_CARD)
s_nc = ad(price=150, ad_id=7203, desc="Всё работает", carded=False, _price_unverified=True)
f_nc = k.rule_facts(s_nc)
m_nc = k.build_short_message(s_nc, f_nc, k.appraise(s_nc, f_nc))
check("карточка не получена: цена из выдачи, в сообщении честно «не сверено с карточкой», уверенность низкая, «ВЫГОДНО» не ставится",
      f_nc["price_src"] == k.PRICE_SRC_SEARCH and "не сверены с карточкой" in m_nc and "Уверенность: низкая" in m_nc
      and "<b>ВЫГОДНО</b>" not in m_nc, m_nc)
# ---- недействительная цена в карточке НЕ затирает действительную цену выдачи ----
for raw_card in ("0", 0, "-500", -500, "abc", None, "", "nan", "1e400", True):
    s_bad = ad(price=100, ad_id=7204, carded=False)
    k.apply_card(s_bad, {"price_byn": raw_card, "body": "Всё работает"})
    check(f"карточка price_byn={raw_card!r}, выдача 100 BYN: цена остаётся 100 (не 0), источник — выдача, неопределённость отмечена",
          k.price_byn(s_bad) == 100 and s_bad["_price_src"] == k.PRICE_SRC_SEARCH and "_price_card_invalid" in s_bad
          and s_bad["_price_raw_search"] == "10000" and s_bad["_price_raw_card"] == raw_card and "_price_conflict" not in s_bad,
          (k.price_byn(s_bad), s_bad.get("_price_src")))
s_bad = ad(price=100, ad_id=7206, carded=False)
k.mdb_observe(s_bad, now=T0 - 300)
k.apply_card(s_bad, {"price_byn": "0", "body": "Всё работает"})
s_bad["_price_unverified"] = True  # как делает process_ad, если цена не подтверждена карточкой
f_bad = k.rule_facts(s_bad)
m_bad = k.build_short_message(s_bad, f_bad, k.appraise(s_bad, f_bad))
diag_bad = k.price_diag(s_bad, k._mdb_ads().get("7206"))
check("недействительная цена карточки: в сообщении 100 BYN и одно предупреждение «не подтверждена», уверенного «ВЫГОДНО» нет",
      "Цена продавца: 100 BYN" in m_bad and m_bad.count("⚠️") == 1 and "нет действительной цены" in m_bad and "<b>ВЫГОДНО</b>" not in m_bad, m_bad)
check("недействительная цена карточки: диагностика — исходные значения выдачи и карточки и явная пометка неопределённости",
      "выдача price_byn='10000'" in diag_bad and "карточка price_byn='0'" in diag_bad and "В КАРТОЧКЕ НЕТ ДЕЙСТВИТЕЛЬНОЙ ЦЕНЫ" in diag_bad
      and "итог 100 BYN" in diag_bad, diag_bad)
k.mdb_observe(s_bad, facts=f_bad, now=T0)
r_bad = k._mdb_ads()["7206"]
check("недействительная цена карточки: в базе цена 100, история без ложного «0», исходное значение карточки сохранено",
      r_bad["price_byn"] == 100 and [h[1] for h in r_bad["price_hist"]] == [100] and r_bad["price_card_invalid"]["raw"] == "0"
      and r_bad["price_raw"]["card"]["price_byn"] == "0" and r_bad["price_raw"]["search"]["price_byn"] == "10000"
      and k.price_changes(r_bad["price_hist"]) == 0, r_bad)
s_none = ad(price=None, ad_id=7207, carded=False)
k.apply_card(s_none, {"price_byn": "0", "body": "Цена договорная"})
check("цены нет ни в выдаче, ни в карточке: согласованно «не указана», неопределённости нет",
      k.price_byn(s_none) == 0 and s_none["_price_src"] == k.PRICE_SRC_CARD and "_price_card_invalid" not in s_none)

# ---- расхождение источников не создаёт ложную историю изменения цены; настоящие изменения не теряются ----
k.mdb_reset()
h1 = ad(price=300, ad_id=7300, carded=False)
k.mdb_observe(h1, now=T0 - 900)                      # запуск 1: выдача 300 (индекс отстал)
k.apply_card(h1, {"price_byn": "10000", "body": "Всё работает"})
k.mdb_observe(h1, now=T0 - 899)                      # запуск 1: карточка 100 (как на странице)
for t_ in (T0 - 600, T0 - 300, T0):                   # запуски 2–4: выдача всё ещё 300
    k.mdb_observe(ad(price=300, ad_id=7300, carded=False), now=t_)
r = k._mdb_ads()["7300"]
k._mdb_status(r, T0)
check("расхождение выдачи (300) и карточки (100): в истории по одной записи на источник, изменением цены НЕ считается",
      [h[1:] for h in r["price_hist"]] == [[300, "search"], [100, "card"]] and k.price_changes(r["price_hist"]) == 0
      and "price_changed" not in r.get("flags", []) and "price_sources_differ" in r["flags"], (r["price_hist"], r.get("flags")))
check("…текущая цена и цена аналога — 100 (страница), отставшая выдача её не откатывает к 300",
      r["price_byn"] == 100 and r["price_src"] == "карточка" and r["comp"][0] == 100
      and {it[0]: it[1] for it in k.mdb_comps("iPhone X", T0)}.get(7300) == 100, (r["price_byn"], r.get("comp")))
k.mdb_observe(ad(price=150, ad_id=7300, carded=False), now=T0 + 300)  # продавец снова поменял цену — видно в выдаче
r = k._mdb_ads()["7300"]
k._mdb_status(r, T0 + 300)
check("настоящее изменение (выдача 300 → 150) записано с датой, флаг price_changed, текущая цена 150",
      r["price_hist"][-1] == [int(T0 + 300), 150, "search"] and k.price_changes(r["price_hist"]) == 1
      and "price_changed" in r["flags"] and r["price_byn"] == 150 and r["price_src"] == "выдача", r)
h2 = ad(price=150, ad_id=7300, carded=False)
k.apply_card(h2, {"price_byn": "14000", "body": "Всё работает"})
k.mdb_observe(h2, now=T0 + 301)
r = k._mdb_ads()["7300"]
check("и в карточке настоящее изменение 100 → 140 — второе изменение; ни одно прежнее не потеряно",
      [h[1:] for h in r["price_hist"]] == [[300, "search"], [100, "card"], [150, "search"], [140, "card"]]
      and k.price_changes(r["price_hist"]) == 2 and r["price_byn"] == 140, r["price_hist"])
k.mdb_reset()
k._mdb_ads()["7400"] = {"first_seen": int(T0) - 999, "last_seen": int(T0) - 10, "price_hist": [[int(T0) - 999, 200.0], [int(T0) - 500, 180.0]],
                        "price_byn": 180.0, "price_raw": {"price_byn": "18000"}, "url": "u"}
k.mdb_observe(ad(price=180, ad_id=7400, carded=False), now=T0)
r = k._mdb_ads()["7400"]
check("старый формат истории [время, цена] читается как выдача: прежнее изменение 200 → 180 сохранено, повтор 180 не добавлен",
      [h[1:] for h in r["price_hist"]] == [[200, "search"], [180, "search"]] and k.price_changes(r["price_hist"]) == 1
      and r["price_raw"]["search"]["price_byn"] == "18000", r)
k.mdb_observe(dict(ad(price=None, ad_id=7400, carded=False)), now=T0 + 60)
check("наблюдение без цены не затирает известную цену и не пишет «0» в историю",
      k._mdb_ads()["7400"]["price_byn"] == 180 and all(h[1] > 0 for h in k._mdb_ads()["7400"]["price_hist"]))
k.mdb_reset()
s_usd = ad(price=2150.29, ad_id=7205, price_usd="73000", currency="USD")
f_usd = k.rule_facts(s_usd)
m_usd = k.build_short_message(s_usd, f_usd, k.appraise(s_usd, f_usd))
check("цена в $ (живой формат Куфара: currency USD, price_usd 73000, price_byn 215029): считаем в BYN, как на странице, и пишем, что продавец указал $",
      f_usd["price"] == 2150.29 and "продавец указал цену в $: 730" in m_usd, m_usd[:200])
k.mdb_reset()

# =====================================================================================================================
# 3. Характеристики
# =====================================================================================================================
for desc, want in (("акб 100%", 100), ("Аккумулятор: 90 %", 90), ("ёмкость аккумулятора 87%", 87), ("всё работает", None),
                   ("скидка 10% при самовывозе", None), ("акб 100%, но через год будет 90%? нет: акб 90%", None)):
    check(f"аккумулятор: «{desc}» → {want}", k.rule_facts(ad(desc=desc))["battery_pct"] == want, k.rule_facts(ad(desc=desc))["battery_pct"])
fb = k.rule_facts(ad(desc="акб 100%. Хотя нет, акб 90%"))
check("аккумулятор: названо 100% и 90% — значение не выбираем, отмечено противоречие",
      fb["battery_pct"] is None and any("аккумулятор" in c for c in fb["conflicts"]), fb["conflicts"])
fm = k.rule_facts(ad("iPhone X 256gb", params=[{"p": "phablet_phones_memory", "vl": "64 ГБ"}]))
apm = k.appraise(ad("iPhone X 256gb", params=[{"p": "phablet_phones_memory", "vl": "64 ГБ"}]), fm)
check("противоречие: память в заголовке 256, в параметрах 64 — память не выбрана, уверенность низкая, противоречие в причинах",
      fm["mem"] == 0 and any("память" in c for c in fm["conflicts"]) and apm["conf"] == "низкая"
      and any("противоречие" in w for w in apm["conf_why"]), (fm["mem"], fm["conflicts"], apm.get("conf"), apm.get("conf_why")))
mm = k.build_short_message(ad("iPhone X 256gb"), fm, apm)
check("противоречие в коротком сообщении — одной строкой ⚠️", mm.count("⚠️ Противоречие") == 1, mm)
for title, params in (("iPhone X / iPhone 8 64gb", []), ("iPhone X 64gb", [{"p": "phones_model", "vl": "iPhone 8"}, {"p": "phones_brand", "vl": "Apple"}])):
    fc, apc, mc = evaluate(ad(title, params=params))
    check(f"модель не угадывается при противоречии ({title} / {params[:1]}): «НЕДОСТАТОЧНО ДАННЫХ — модель не подтверждена»",
          fc["label"] == "Другое" and fc["model_conflict"] and apc["status"] == "no_model" and "модель не подтверждена" in mc, (fc["label"], mc))
fs = k.rule_facts(ad("iPhone SE 64gb", params=[{"p": "phones_model", "vl": "iPhone SE (2nd generation)"}, {"p": "phones_brand", "vl": "Apple"}]))
check("уточнение — не противоречие: заголовок «iPhone SE», параметр «SE 2-го поколения» → iPhone SE (2020)",
      not fs["conflicts"] and fs["label"] == "iPhone SE (2020)", (fs["label"], fs["conflicts"]))
fok = k.rule_facts(ad("iPhone X 64gb", params=[{"p": "phones_model", "vl": "iPhone X"}, {"p": "phones_brand", "vl": "Apple"}]))
check("заголовок и параметры совпадают: уверенность в модели высокая", fok["model_conf"] == "высокая" and not fok["conflicts"])
fsc, apsc, msc = evaluate(ad(price=100, desc="Разбит экран, всё остальное работает"))
check("битый экран: дефект найден, оценка по аналогам с таким же дефектом (их 5), а не по исправным",
      "screen" in fsc["defects"] and apsc["basis"] == "defect" and "🔧 По описанию: проблемы с экраном" in msc
      and "📊 Перепродажа: 120" in msc, msc)
fh, aph, mh = evaluate(ad(price=120, desc="Продаю"))
unc = aph["plan"]["unconfirmed"]
check("скрытые функции не проверены: список непроверенного, резерв в расчёте, вердикт «если дефекты не обнаружатся»",
      unc and any("Face ID" in x for x in unc) and aph["plan"]["A"]["reserve"] > 0 and "если дефекты не обнаружатся" in mh, (unc, mh))
fk = k.rule_facts(ad(desc="Полный комплект, коробка, зарядка"))
k.mdb_reset()
k.mdb_observe(ad(ad_id=7100, desc="Полный комплект, коробка, зарядка"), facts=fk, now=T0)
check("комплект по описанию: источник «текст продавца», фото его не подтверждали",
      fk["kit_src"] == "текст продавца" and k._mdb_ads()["7100"]["kit"] == {"items": fk["kit"], "src": "текст продавца", "photo_confirmed": False},
      k._mdb_ads()["7100"].get("kit"))
fk["photo"].update(status="analyzed", n=2, kit=["коробка"], findings=[])
k.mdb_appraisal(7100, fk, {"decision": ("unknown", ""), "plan": {}, "stats": {}, "comps": []})
check("комплект виден на реально проанализированных фото → photo_confirmed, наблюдения фото отдельно с источником",
      k._mdb_ads()["7100"]["kit"]["photo_confirmed"] is True and k._mdb_ads()["7100"]["photo"]["src"].startswith("фото"))
fn = k.rule_facts(ad(desc="Полный комплект"))
k.mdb_appraisal(7100, dict(fn, photo={"status": "llm_off"}), {"decision": ("unknown", ""), "plan": {}, "stats": {}, "comps": []})
check("фото не анализировались (нейросеть недоступна) — в базе нет «наблюдений по фото» от этого запуска",
      k._mdb_ads()["7100"]["photo"]["n"] == 2)
for status in ("none", "no_llm", "llm_off", "no_time", "error", "no_download"):
    fp = k.rule_facts(ad(desc="Всё работает"))
    fp["photo"]["status"] = status
    mp = k.build_short_message(ad(desc="Всё работает"), fp, k.appraise(ad(desc="Всё работает"), fp))
    check(f"короткое сообщение не заявляет о проверке фото, если её не было ({status})", "фото" not in mp.lower(), mp)
fpm = k.rule_facts(ad(desc="Идеал"))
fpm["photo"].update(status="analyzed", n=3, mismatch="на фото трещина экрана, а в тексте «идеал»")
mpm = k.build_short_message(ad(desc="Идеал"), fpm, k.appraise(ad(desc="Идеал"), fpm))
check("расхождение фото с описанием — одна строка ⚠️, расчёт по фото не меняется", "⚠️ Фото расходится с описанием" in mpm
      and "screen" not in fpm["defects"], mpm)

# =====================================================================================================================
# 4. Финансовая оценка
# =====================================================================================================================
k.mdb_reset()  # финансы считаем на известном пуле аналогов (иначе в него честно попадут активные записи базы из разделов выше)
fg, apg, mg = evaluate(ad(price=120, desc="Всё работает, акб 90%"))
c = apg["plan"]["A"]
quick = k.floor5(k.percentile(sorted(it[1] for it in CLEAN_X), 0.25))  # быстрая продажа — вниз до 5 BYN
reserve = k.ceil5(k.RISK_RESERVE_PCT / 100 * quick)
target = k.ceil5(max(k.MIN_PROFIT_BYN, k.MIN_PROFIT_PCT / 100 * quick))
limit = k.floor5(quick - reserve - target)
profit = quick - 120 - reserve
check("формула: максимум покупки = быстрая продажа − ремонт − прочие расходы − резерв риска − целевая прибыль",
      c["quick"] == quick and c["reserve"] == reserve and c["target"] == target and c["limit"] == limit, (c["quick"], c["reserve"], c["target"], c["limit"]))
check("чистая прибыль и ROI посчитаны верно", abs(c["profit"] - profit) < 1e-9 and abs(c["roi"] - profit / (120 + reserve)) < 1e-9, (c["profit"], c["roi"]))
check("выгодная покупка: ВЫГОДНО, цифры из расчёта в сообщении",
      apg["decision"][0] == "buy" and "✅ <b>ВЫГОДНО</b>" in mg and f"💸 Максимум покупки: {limit} BYN" in mg
      and f"🎯 Желательно купить за: {c['desired']} BYN" in mg and "📈 Прибыль после расходов: около" in mg
      and f"⚡ Быстрая продажа: около {quick} BYN" in mg and "не сделок" in mg, mg)
check("рыночная цена и цена покупки различаются: перепродажа ≈ медиана, максимум покупки ниже быстрой продажи",
      c["limit"] < c["quick"] < c["list"] + 1)
fx_, apx, mx = evaluate(ad(price=300, desc="Всё работает"))
check("невыгодная покупка: «Продавец просит 300 BYN, максимальная покупка для перепродажи — N BYN»",
      apx["decision"][0] == "skip" and f"Продавец просит 300 BYN, максимальная покупка для перепродажи — {apx['plan']['A']['limit']} BYN" in mx, mx)
fz, apz, mz = evaluate(ad(price=quick - reserve, desc="Всё работает"))
check("нулевая ожидаемая прибыль: прибыль 0, не ВЫГОДНО", abs(apz["plan"]["A"]["profit"]) < 1e-9 and "<b>ВЫГОДНО</b>" not in mz, (apz["plan"]["A"]["profit"], mz))
fneg, apneg, mneg = evaluate(ad(price=quick + 40, desc="Всё работает"))
check("отрицательная прибыль: показана со знаком минус, НЕВЫГОДНО", apneg["plan"]["A"]["profit"] < 0 and "−" in mneg and "НЕВЫГОДНО" in mneg, mneg)
k.EXTRA_COSTS_BYN, k.TARGET_PROFIT_BYN = 30, 200
fl, apl, ml = evaluate(ad(price=50, desc="Всё работает"))
check("расходы и цель больше выручки: «не окупается ни при какой цене»",
      apl["plan"]["A"]["limit"] <= 0 and "не окупается" in ml and "НЕВЫГОДНО" in ml, ml)
k.EXTRA_COSTS_BYN, k.TARGET_PROFIT_BYN = 0, 0
fr, apr, mr = evaluate(ad(price=100, desc="Разбит экран"))
check("неизвестный ремонт: цена ремонта не придумана — показан бюджет, при котором ремонт имеет смысл",
      not k.REPAIR_COSTS and apr["plan"]["repair"]["unknown"] and "имеет смысл, если обойдётся не дороже" in mr, mr)
k.REPAIR_COSTS.update({"screen": [40, 60]})
fr2, apr2, mr2 = evaluate(ad(price=100, desc="Разбит экран"))
k.REPAIR_COSTS.clear()
check("известный ремонт (REPAIR_COSTS): вариант с ремонтом посчитан с ремонтом и запасом на удорожание",
      apr2["plan"]["B"] and apr2["plan"]["B"]["final"] and apr2["plan"]["B"]["rep_hi"] == 60 and apr2["plan"]["B"]["overrun"] == 9, apr2["plan"]["B"])
market("iPhone 11", [[4000, 600, 64, 0, 1, 0], [4001, 620, 64, 0, 1, 0]])
f2, ap2, m2 = evaluate(ad("iPhone 11 64gb", price=400, desc="Всё работает"))
check("мало аналогов (2): НЕДОСТАТОЧНО ДАННЫХ, причина — число аналогов, уверенного вердикта нет",
      "НЕДОСТАТОЧНО ДАННЫХ" in m2 and "недостаточно аналогов" in m2 and "<b>ВЫГОДНО</b>" not in m2, m2)
market("iPhone 11", [[4000 + i, 600 + i * 5, 64, 0, 1, 0] for i in range(4)])
f4, ap4, m4 = evaluate(ad("iPhone 11 64gb", price=300, desc="Всё работает"))
check("4 аналога (меньше 5): ориентиры есть, но вердикт не уверенный", ap4["thin"] and "НЕДОСТАТОЧНО ДАННЫХ" in m4, m4)
market("iPhone 7", [[4100 + i, 100 + i * 3, 32, 0, 1, 0] for i in range(6)] +
       [[4200, 95, 32, 0, 1, 0, "dup"], [4201, 95, 32, 0, 1, 0, "dup"], [4202, 95, 32, 0, 1, 0, "dup"]])
items, *_ = k.market_items("iPhone 7")
check("дубли (тот же заголовок, цена, память и регион под разными номерами) в аналоги не идут", sum(it[0] in (4200, 4201, 4202) for it in items) == 1)
check("«куплю» и аксессуары в аналоги не идут", k.comp_item(ad("Куплю iPhone X 64gb"), "iPhone X") is None
      and k.comp_item(ad("Чехол для iPhone X"), "iPhone X") is None and k.comp_item(ad("iPhone X 64gb"), "iPhone X") is not None)

# =====================================================================================================================
# 5. База рынка
# =====================================================================================================================
k.mdb_reset()
k.MARKET_DB_FILE = D / "market_history.json"
a1 = ad("iPhone X 64gb", price=200, ad_id=8001, desc="акб 88%")
k.mdb_observe(a1, now=T0)
a1b = dict(a1, list_time=iso(T0 + 600))
k.mdb_observe(a1b, now=T0 + 600)
rec = k._mdb_ads()["8001"]
check("одно объявление — одна запись: повторное наблюдение обновляет её; дата публикации и её прежнее значение сохранены",
      len(k._mdb_ads()) == 1 and rec["list_time"] == iso(T0 + 600) and rec["list_time_hist"] == [iso(T0 - 60)]
      and rec["first_seen"] == int(T0) and rec["last_seen"] == int(T0 + 600), rec)
check("в записи: модель с уверенностью, память с источником, аккумулятор только указанный, регион, продавец, исходные поля цены",
      rec["model"]["label"] == "iPhone X" and rec["model"]["conf"] == "высокая" and rec["mem_gb"] == 64 and rec["mem_src"] == "заголовок"
      and rec["battery"] == {"pct": 88, "src": "текст продавца"} and rec["region"] == "Минск" and rec["seller"] == "частник"
      and rec["price_raw"]["card"]["price_byn"] == "20000", rec)
k.mdb_observe(ad("iPhone X 64gb", price=200, ad_id=8001, desc=""), now=T0 + 700)
check("наблюдение без описания не стирает факты из описания", k._mdb_ads()["8001"]["battery"]["pct"] == 88)
k.mdb_observe(ad("iPhone X 64gb", price=190, ad_id=8002), now=T0 - 20 * 86400)
k.mdb_observe(ad("iPhone X 64gb", price=150, ad_id=8003), now=T0 - 70 * 86400)
k.mdb_note(8004, "sent", now=T0 - 70 * 86400)
k._mdb_ads()["8004"]["last_seen"] = int(T0 - 70 * 86400)
k.mdb_note(8005, "sent", now=T0 - 5 * 86400)
k._mdb_ads()["8005"]["last_seen"] = int(T0 - 70 * 86400)
check("аналоги из базы: только активные (видели не позже 3 дней назад) той же модели с ценой", sorted(it[0] for it in k.mdb_comps("iPhone X", T0)) == [8001], k.mdb_comps("iPhone X", T0))
ok = k.mdb_save(T0)
data = json.loads((D / "market_history.json").read_text())
check("сохранение: файл читается, старше 60 дней удалено, свежая отправка (против повторов) сохранена даже без появления в выдаче",
      ok and set(data["ads"]) == {"8001", "8002", "8005"}, sorted(data["ads"]))
check("статусы: активное / не видно в выдаче (а не «продано»), пометки",
      data["ads"]["8001"]["status"] == "active" and data["ads"]["8002"]["status"] == "not_seen"
      and "relisted" in data["ads"]["8001"]["flags"] and "sold" not in json.dumps(data), (data["ads"]["8001"], data["ads"]["8002"]))
# отбор аналогов: активные / давно не наблюдавшиеся / not_seen / смена цены / исчезнувшее / повтор номера в базе и выдаче
k.mdb_reset()
for i, (seen_ago, price_) in enumerate(((3600, 200), (2 * 86400, 210), (5 * 86400, 900), (20 * 86400, 90))):
    k.mdb_observe(ad("iPhone X 64gb", price=price_, ad_id=8100 + i, desc="Всё работает"), now=T0 - seen_ago)
k.mdb_observe(ad("iPhone X 64gb", price=300, ad_id=8110, desc="Всё работает"), now=T0 - 3 * 3600)
k.mdb_observe(ad("iPhone X 64gb", price=250, ad_id=8110, desc="Всё работает"), now=T0 - 3600)  # цена изменилась
k.mdb_observe(ad("iPhone X 64gb", price=500, ad_id=8111, desc="Всё работает"), now=T0 - 4 * 86400)  # исчезло из выдачи 4 дня назад
k.mdb_save(T0)
st_ = {k_: r["status"] for k_, r in json.loads((D / "market_history.json").read_text())["ads"].items()}
cur = {it[0]: it[1] for it in k.mdb_comps("iPhone X", T0)}
check("аналоги: активные (1 ч и 2 дня назад) — в текущей выборке", 8100 in cur and 8101 in cur, cur)
check("аналоги: давно не наблюдавшиеся (5 и 20 дней) и запись not_seen — НЕ в текущей выборке", not ({8102, 8103} & set(cur))
      and st_["8102"] == "not_seen" and st_["8103"] == "not_seen", (cur, st_))
check("аналоги: изменившаяся цена — берётся последняя (250, а не 300)", cur.get(8110) == 250, cur)
check("аналоги: исчезнувшее из выдачи — статус not_seen (не «продано»), в текущую оценку не идёт", st_["8111"] == "not_seen" and 8111 not in cur
      and "sold" not in json.dumps(st_), st_)
hist = k.mdb_history("iPhone X", 64, T0)
check("история: давно не наблюдавшиеся — отдельной сводкой (3 шт.: 900, 90, 500), в текущую выборку не подмешаны",
      hist and hist["n"] == 3 and hist["med"] == 500, hist)
market("iPhone X", [[8100, 200, 64, 0, 1, 0], [8101, 210, 64, 0, 1, 0], [9999, 205, 64, 0, 1, 0]])
items, *_ = k.market_items("iPhone X")
ids_ = [it[0] for it in items]
check("повтор одного номера в выдаче и базе: в аналогах один раз (выдача в приоритете), база добавила только своё",
      ids_.count(8100) == 1 and ids_.count(8101) == 1 and 8110 in ids_ and 8102 not in ids_ and k.RUN["db_comps"] == 1, (ids_, k.RUN["db_comps"]))
apx_ = k.appraise(ad("iPhone X 64gb", price=150, ad_id=9998, desc="Всё работает"), k.rule_facts(ad("iPhone X 64gb", price=150, ad_id=9998, desc="Всё работает")))
check("активных аналогов мало (4): уверенности нет — выборка НЕ раздута устаревшими записями",
      apx_["stats"]["n"] == 4 and ("НЕДОСТАТОЧНО ДАННЫХ" in k.build_short_message(ad(ad_id=9998), k.rule_facts(ad(ad_id=9998, desc="Всё работает")), apx_)), apx_.get("stats"))
k.STATE["market"]["iPhone X"]["t"] = int(T0 - 5 * 86400)
k.MARKET_MAX_REFRESH = 0
items2, age2, stale2, why2 = k.market_items("iPhone X")
k.MARKET_MAX_REFRESH = 6
check("кеш выдачи 5-дневной давности не подмешивается как текущий: только активные записи базы",
      {it[0] for it in items2} == {8100, 8101, 8110} and stale2, ({it[0] for it in items2}, stale2))
market("iPhone X", CLEAN_X + SCREEN_X)
k.mdb_reset()
k.mdb_observe(ad("iPhone X 64gb", price=200, ad_id=8001, desc="акб 88%"), now=T0)
k.mdb_observe(ad("iPhone X 64gb", price=190, ad_id=8002), now=T0 - 20 * 86400)
k.mdb_note(8005, "sent", now=T0 - 5 * 86400)
k._mdb_ads()["8005"]["last_seen"] = int(T0 - 70 * 86400)
k.mdb_save(T0)
lines = (D / "market_history.json").read_text().splitlines()
check("формат: одна запись на строку (маленькие коммиты в git)", sum(l.startswith('"80') for l in lines) == 3, lines[:3])
k.mdb_load()
check("загрузка: то же содержимое", set(k._mdb_ads()) == {"8001", "8002", "8005"} and k.MDB["loaded"] == 3)
for i in range(200):
    k.mdb_observe(ad("iPhone X 64gb", price=200, ad_id=9000 + i), now=T0)
k.mdb_save(T0)
k.mdb_load()
for key_ in list(k._mdb_ads())[:150]:
    del k._mdb_ads()[key_]
before = (D / "market_history.json").read_text()
check("защита от потери: в памяти вдвое меньше записей, чем загружено — файл не перезаписан",
      k.mdb_save(T0) is False and (D / "market_history.json").read_text() == before)
k.mdb_load()
k.MARKET_DB_MAX = 50
k.mdb_save(T0)
k.MARKET_DB_MAX = 6000
check("переполнение: удаляются те, кого дольше всего не видели; отправленные за 30 дней остаются",
      len(json.loads((D / "market_history.json").read_text())["ads"]) == 50 and "8005" in json.loads((D / "market_history.json").read_text())["ads"])
(D / "market_history.json").write_text('{"ads": [1, 2')
check("повреждённая база: загрузка честно не удаётся, сохранение отказывается, файл цел",
      k.mdb_load() is False and k.mdb_save(T0) is False and (D / "market_history.json").read_text() == '{"ads": [1, 2')
k.mdb_reset()

print("итого ошибок (свежесть, цена, характеристики, финансы, база):", bad)
sys.exit(1 if bad else 0)
