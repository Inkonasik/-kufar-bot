"""Тесты оценки цены и перепродажи на синтетических аналогах (без сети)."""
import os
import sys
import time
from pathlib import Path

os.environ.update(TG_TOKEN="t", TG_CHAT_ID="1")
for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MODELS", "REPAIR_COSTS", "HOME_REGION"):
    os.environ.pop(key, None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fresh_dir  # noqa: E402
tmp = fresh_dir()
sys.path.insert(0, str(tmp))
import kufar_bot as k  # noqa: E402

# Проверки этого файла — про формулы и счётчики, поэтому резерв на непроверенные функции и запас на удорожание ремонта выключены
# (их работа проверяется отдельно, в test_stage2.py)
k.RISK_RESERVE_PCT = 0
k.REPAIR_OVERRUN_PCT = 0

bad = 0
VERBOSE = "-v" in sys.argv


def check(name, cond, extra=""):
    global bad
    if not cond:
        print("FAIL", name, extra)
        bad += 1


def ad(subject, price=65000, desc="", cond="Б/у", ad_id=9001, region="Минск"):
    d = {"ad_id": ad_id, "type": "sell", "company_ad": False, "price_byn": str(price), "price_usd": "20000",
         "subject": subject, "ad_link": f"https://www.kufar.by/item/{ad_id}",
         "ad_parameters": [{"p": "condition", "vl": cond}, {"p": "region", "vl": region}, {"p": "area", "vl": "Центральный"}]}
    if desc:
        d["body_short"] = desc
    return d


def put_market(key, items, age=0):
    k.STATE["market"][key] = {"t": int(time.time() - age), "items": items}


# 20 исправных iPhone 11 64 ГБ, цены 600..790 (шаг 10), Минск (код 1) и регионы
items = [[100 + i, 600 + i * 10, 64, 0, 1 if i % 2 == 0 else 3, 0] for i in range(20)]
# + дефектные (разбитый экран) — их 4 шт., + «запчасти» — 1 шт., новые — 2 шт.
items += [[200 + i, 330 + i * 15, 64, k.F_DEF, 1, 0] for i in range(4)]
items += [[300, 120, 64, k.F_DEF | k.F_PARTS | k.F_CRIT, 1, 0]]
items += [[400, 1100, 64, k.F_NEW, 1, 0], [401, 1150, 64, k.F_NEW, 1, 0]]
put_market("iPhone 11", items)

# --- статистика и выбросы ---
st = k.price_stats([600, 610, 620, 630, 640, 1, 99999])
check("выбросы отброшены", st["n"] == 5 and st["dropped"] == 2, st)
check("медиана", st["med"] == 620, st["med"])
check("пустая статистика", k.price_stats([]) is None and k.price_stats([0, -1]) is None)

# --- вердикты по положению цены ---
st = k.price_stats(list(range(600, 800, 10)))  # 20 цен
check("очень выгодно", k.rank_verdict(560, st)[0] == "ОЧЕНЬ ВЫГОДНО", k.rank_verdict(560, st))
check("выгодно", k.rank_verdict(630, st)[0] == "ВЫГОДНО", k.rank_verdict(630, st))
check("средний", k.rank_verdict(690, st)[0] == "СРЕДНИЙ ВАРИАНТ", k.rank_verdict(690, st))
check("дорого", k.rank_verdict(760, st)[0] == "ДОРОГО", k.rank_verdict(760, st))
check("невыгодно", k.rank_verdict(900, st)[0] == "НЕВЫГОДНО", k.rank_verdict(900, st))

# --- объявление по хорошей цене ---
a = ad("iPhone 11 64gb", 62000, "Состояние хорошее, акб 88%, полный комплект. Торг.")
f = k.rule_facts(a)
r = k.appraise(a, f)
if VERBOSE:
    print(r)
check("статус ok", r["status"] == "ok", r["status"])
check("вердикт выгодно", r["verdict"] in ("ВЫГОДНО", "ОЧЕНЬ ВЫГОДНО"), r["verdict"])
check("пул: исправные из своего региона, без дефектных/запчастей/новых", r["found"] == 10 and r["tier"] == "T1", (r.get("found"), r.get("tier")))
check("процент ниже медианы", r["pct"] < 0, r.get("pct"))
check("аналоги реальные", all(c[0] in {i[0] for i in items} for c in r["comps"]) and 1 <= len(r["comps"]) <= 3, r["comps"])
check("свой id не в аналогах", all(c[0] != 9001 for c in r["comps"]))
c = r["calc"]
check("перепродажа посчитана", c and c["list"] and c["quick"] and c["limit"] is not None and c["final"], c)
check("список = медиана (округл. до 5)", c["list"] == k.rnd5(r["stats"]["med"]), c)
check("быстрая <= список", c["quick"] <= c["list"], c)
check("прибыль = быстрая - цена - расходы", abs(c["profit"] - (c["quick"] - 620 - c["extra"] - c["rep_hi"])) < 1e-6, c)
check("лимит <= быстрая", c["limit"] <= c["quick"], c)
check("порог прибыли", c["target"] >= k.MIN_PROFIT_BYN and c["target"] % 5 == 0, c["target"])
check("лимит = быстрая − ремонт − расходы − целевая прибыль (вниз до 5)",
      c["limit"] == k.floor5(c["quick"] - c["extra"] - c["rep_hi"] - c["target"]), c)
check("исправный без ремонта: ремонт 0 и не «неизвестен»", c["rep_hi"] == 0 and c["rep_unknown"] == [], c)
check("три уровня цены: желаемая <= максимум <= отказ", c["desired"] <= c["limit"] <= c["walk"], c)

# --- дорогое объявление ---
a2 = ad("iPhone 11 64gb", 90000, "Идеал")
r2 = k.appraise(a2, k.rule_facts(a2))
check("дорого/невыгодно", r2["verdict"] in ("ДОРОГО", "НЕВЫГОДНО"), r2["verdict"])
check("максимум покупки ниже цены продавца", r2["plan"]["A"]["limit"] < 900, r2["plan"]["A"])
check("перепродажа невыгодна: не «покупать по текущей цене»", r2["decision"][0] in ("skip", "bargain"), r2["decision"])

# --- цена не указана / договорная ---
a3 = ad("iPhone 11 64gb", 0, "Цена договорная")
r3 = k.appraise(a3, k.rule_facts(a3))
check("без цены: вердикта по цене нет", r3["verdict"] is None, r3["verdict"])
check("без цены: уровни цены покупки есть, прибыли нет", r3["calc"]["limit"] > 0 and "profit" not in r3["calc"], r3["calc"])
check("без цены: вывод «недостаточно данных» с причиной", r3["decision"][0] == "unknown" and "нет цены" in r3["decision"][1], r3["decision"])

# --- мало аналогов ---
put_market("iPhone 8", [[500 + i, 300 + i * 10, 64, 0, 1, 0] for i in range(3)])
a4 = ad("iPhone 8 64gb", 28000)
r4 = k.appraise(a4, k.rule_facts(a4))
check("3 аналога: ориентир есть, но помечен как приблизительный", r4["status"] == "ok" and r4["thin"] and r4["conf"] == "низкая", (r4["status"], r4["thin"], r4["conf"]))
check("3 аналога: вывод «недостаточно данных»", r4["decision"][0] == "unknown" and "аналогов мало" in r4["decision"][1], r4["decision"])
put_market("iPhone 8", [[500 + i, 300 + i * 10, 64, 0, 1, 0] for i in range(2)])
r4b = k.appraise(a4, k.rule_facts(a4))
check("2 аналога -> few, вердикта по цене нет", r4b["status"] == "few" and r4b["verdict"] is None and r4b["calc"] is None, (r4b["status"], r4b["verdict"]))
check("few: ссылки на то, что есть", len(r4b["comps"]) == 2)
check("few: вывод называет, чего не хватает", r4b["decision"][0] == "unknown" and "найдено только 2" in r4b["decision"][1], r4b["decision"])

# --- дефектное объявление: «такой же дефект» подтверждается только заголовками аналогов ---
a5 = ad("iPhone 11 64gb", 40000, "Разбит экран, остальное работает")
f5 = k.rule_facts(a5)
clean = [i for i in items if not (i[3] & k.F_DEF and not i[3] & k.F_PARTS)]
put_market("iPhone 11", clean + [[210, 300, 64, k.F_DEF | k.F_KINDS["screen"], 1, 0], [211, 340, 64, k.F_DEF | k.F_KINDS["screen"], 1, 0]])
r5 = k.appraise(a5, f5)
check("дефект: 2 аналога с таким же дефектом (<3) -> оценка по общему рынку", r5["status"] == "ok" and r5["basis"] == "general", (r5["status"], r5["basis"]))
check("дефект: счётчики раздельно: всего аналогов и с таким же дефектом", r5["found"] == 10 and r5["like_n"] == 2 and r5["like_need"] == 3, (r5["found"], r5["like_n"]))
check("дефект: уверенность низкая, вердикта «выгодно/дорого» нет", r5["conf"] == "низкая" and r5["verdict"] is None, (r5["conf"], r5["verdict"]))
check("дефект: аналоги для показа без дефектов (общий рынок)", all(not c[3] & k.F_DEF for c in r5["comps"]), r5["comps"])
check("дефект: ремонт неизвестен -> лимит предварительный, прибыль «до ремонта»", r5["calc"]["rep_unknown"] and not r5["calc"]["final"], r5["calc"])
put_market("iPhone 11", clean + [[210 + i, 300 + i * 20, 64, k.F_DEF | k.F_KINDS["screen"], 1, 0] for i in range(4)])
r5 = k.appraise(a5, f5)
check("дефект: 4 аналога с таким же дефектом -> оценка по ним", r5["status"] == "ok" and r5["basis"] == "defect" and r5["found"] == 4 and r5["like_n"] == 4, (r5["status"], r5.get("basis"), r5.get("found")))
check("дефект: пул — аналоги с дефектом", all(c[3] & k.F_DEF for c in r5["comps"]), r5["comps"])
check("дефект по дефектным: ремонт не вычитается (дефект уже в цене аналогов)", r5["plan"]["A"]["rep_hi"] == 0 and r5["plan"]["A"]["rep_unknown"] == [] and r5["plan"]["A"]["final"], r5["plan"]["A"])
check("дефект: вердикт по дефектным", r5["verdict"] in ("ОЧЕНЬ ВЫГОДНО", "ВЫГОДНО", "СРЕДНИЙ ВАРИАНТ", "ДОРОГО", "НЕВЫГОДНО"), r5["verdict"])
# аналоги с ДРУГИМ дефектом «таким же» не считаются
put_market("iPhone 11", clean + [[220 + i, 300 + i * 20, 64, k.F_DEF | k.F_KINDS["battery"], 1, 0] for i in range(5)])
r5c = k.appraise(a5, f5)
check("другой вид дефекта не считается таким же", r5c["like_n"] == 0 and r5c["basis"] == "general", (r5c["like_n"], r5c["basis"]))
# аналоги из старого кеша (дефект без вида) тоже не считаются подтверждёнными
put_market("iPhone 11", clean + [[230 + i, 300 + i * 20, 64, k.F_DEF, 1, 0] for i in range(5)])
r5d = k.appraise(a5, f5)
check("старый кеш: дефект без вида не подтверждает «такой же»", r5d["like_n"] == 0 and r5d["basis"] == "general", (r5d["like_n"], r5d["basis"]))

# --- известные цены ремонта: ремонт вычитается ОДИН раз ---
put_market("iPhone 11", clean + [[210, 300, 64, k.F_DEF | k.F_KINDS["screen"], 1, 0], [211, 340, 64, k.F_DEF | k.F_KINDS["screen"], 1, 0]])
k.REPAIR_COSTS.clear()
k.REPAIR_COSTS.update({"screen": 80})
check("известный ремонт", k.known_repair_cost(f5) == 80, k.known_repair_cost(f5))
r5b = k.appraise(a5, f5)
c5 = r5b["calc"]
check("ремонт известен: учтён один раз", r5b["basis"] == "general" and c5["rep_hi"] == 80 and c5["final"] and c5["rep_unknown"] == [], c5)
check("лимит = быстрая − 80 − расходы − цель", c5["limit"] == k.floor5(c5["quick"] - 80 - c5["extra"] - c5["target"]), c5)
check("прибыль = быстрая − цена − ремонт − расходы", abs(c5["profit"] - (c5["quick"] - 400 - 80 - c5["extra"])) < 1e-6, c5)
put_market("iPhone 11", clean + [[210 + i, 300 + i * 20, 64, k.F_DEF | k.F_KINDS["screen"], 1, 0] for i in range(4)])
r5e = k.appraise(a5, f5)
check("вариант 1 (по аналогам с таким же дефектом): ремонт НЕ вычитается, даже если цена ремонта задана; вариант 2 — вычитает один раз",
      r5e["basis"] == "defect" and r5e["plan"]["A"]["rep_hi"] == 0 and r5e["plan"]["B"]["rep_hi"] == 80, (r5e["plan"]["A"], r5e["plan"]["B"]))
k.REPAIR_COSTS.clear()

# --- запчасти / критичное ---
a6 = ad("iPhone 11 на запчасти", 12000, "Не включается")
r6 = k.appraise(a6, k.rule_facts(a6))
check("запчасти: «не покупать для перепродажи»", r6["decision"][0] == "skip" and r6["decision"][1].startswith("Не покупать для перепродажи"), r6["decision"])
check("запчасти: не «выгодно»", r6["verdict"] not in ("ВЫГОДНО", "ОЧЕНЬ ВЫГОДНО") or r6["warnings"], (r6["verdict"], r6["warnings"]))

# --- нет модели / нет данных рынка ---
r7 = k.appraise(ad("Телефон"), dict(k.rule_facts(ad("Телефон"))))
check("нет модели", r7["status"] == "no_model" and r7["decision"][0] == "unknown", (r7["status"], r7["decision"]))
k.STATE["market"].pop("iPhone 7", None)
k._MARKET_REFRESHES["n"] = 99  # обновление запрещено
a8 = ad("iPhone 7 32gb", 15000)
r8 = k.appraise(a8, k.rule_facts(a8))
check("нет рынка -> no_market", r8["status"] == "no_market" and r8["verdict"] is None and r8["decision"][0] == "unknown", r8["status"])
k._MARKET_REFRESHES["n"] = 0

# --- устаревший кеш (обновить нельзя) ---
put_market("iPhone 11", items, age=30 * 3600)
k._MARKET_REFRESHES["n"] = 99
r9 = k.appraise(a, k.rule_facts(a))
check("устаревший кеш помечается", r9["status"] == "ok" and r9["stale"] is True and r9["age_h"] > 24, (r9["status"], r9.get("stale")))
k._MARKET_REFRESHES["n"] = 0

# --- iPhone SE без поколения ---
se = [[600 + i, 300 + i * 10, 64, 0, 1, 2020] for i in range(6)] + [[700 + i, 450 + i * 10, 64, 0, 1, 2022] for i in range(6)]
put_market("iPhone SE", se)
a10 = ad("iPhone SE 64gb", 30000)
f10 = k.rule_facts(a10)
r10 = k.appraise(a10, f10)
check("SE без поколения -> se_gen", r10["status"] == "se_gen" and r10["verdict"] is None and r10["decision"][0] == "unknown", r10["status"])
check("SE: цены по поколениям", set(r10["se_gens"]) == {2020, 2022}, r10.get("se_gens"))
a11 = ad("iPhone SE 2020 64gb", 30000)
r11 = k.appraise(a11, k.rule_facts(a11))
check("SE 2020: сравнение только с 2020", r11["status"] in ("ok", "few") and all(c[5] == 2020 for c in r11["comps"]), r11["status"])

# --- регион: приоритет своего региона (T1), потом шире ---
put_market("iPhone 11", items)
r12 = k.appraise(a, k.rule_facts(a))
check("свой регион при достатке аналогов (T1)", r12["tier"] == "T1", r12.get("tier"))
a13 = ad("iPhone 11 64gb", 62000, region="Гомельская область", ad_id=9002)
r13 = k.appraise(a13, k.rule_facts(a13))
check("в регионе мало аналогов -> вся Беларусь (T2), n=20", r13["tier"] == "T2" and r13["found"] == 20, (r13.get("tier"), r13.get("found")))
a14 = ad("iPhone 11", 62000, ad_id=9003)  # память не указана
r14 = k.appraise(a14, k.rule_facts(a14))
check("память не указана: пометка и сниженная уверенность", any("памят" in n for n in r14["notes"]) and r14["conf"] != "высокая", (r14["notes"], r14.get("conf")))

# --- HOME_REGION: аналоги из региона продажи в приоритете; без него берётся регион самого объявления ---
k.HOME_REGION = "минск"
put_market("iPhone 11", items)
a15 = ad("iPhone 11 64gb", 62000, region="Гомельская область", ad_id=9004)
r15 = k.appraise(a15, k.rule_facts(a15))
check("HOME_REGION=минск: пул из Минска даже для объявления из другого региона", r15["tier"] == "T1" and "Минск" in r15["place"], (r15.get("tier"), r15.get("place")))
k.HOME_REGION = ""
r15b = k.appraise(a15, k.rule_facts(a15))
check("без HOME_REGION: регион объявления (мало аналогов -> вся Беларусь)", r15b["tier"] == "T2", r15b.get("tier"))

# --- уверенность ---
check("уверенность — строка", r["conf"] in ("высокая", "средняя", "низкая"), r["conf"])

# =====================================================================================================
# Пример из задачи: iPhone XS 64 ГБ, цена 250 BYN, аккумулятор 74%; 34 аналога, ни у одного не подтверждён такой же дефект
# =====================================================================================================
def xs_market(extra=(), n=34):
    its = [[500 + i, 330 + i * 7, 64, 0, 1 if i < 16 else 5 if i < 22 else 3 if i < 28 else 4, 0] for i in range(n)]  # 330..561 BYN
    put_market("iPhone XS", its + list(extra))


FOUR = ("Покупать по текущей цене", "Покупать только после торга", "Не покупать для перепродажи", "Пока недостаточно данных для решения")


def xs(price_kop=25000, desc="Состояние хорошее, акб 74%.", repair=None, extra=(), n=34):
    k.REPAIR_COSTS.clear()
    k.REPAIR_COSTS.update(repair or {})
    xs_market(extra, n)
    a_ = ad("iPhone XS 64gb", price_kop, desc, region="Гомельская область", ad_id=9100)
    f_ = k.rule_facts(a_)
    return a_, f_, k.appraise(a_, f_)


axs, fxs, rxs = xs()
check("XS: дефект «аккумулятор 74%» найден", "battery" in fxs["defects"] and fxs["battery_pct"] == 74, fxs["defects"])
check("XS: 34 найденных аналога и 0 с подтверждённым дефектом — раздельно", rxs["found"] == 34 and rxs["like_n"] == 0, (rxs["found"], rxs["like_n"]))
check("XS: основа — общий рынок, уверенность низкая, вердикта «выгодно/дорого» нет", rxs["basis"] == "general" and rxs["conf"] == "низкая" and rxs["verdict"] is None, (rxs["basis"], rxs["conf"], rxs["verdict"]))
cx, stx = rxs["calc"], rxs["stats"]
check("XS: вариант 2 (ремонт) — основной: вариант 1 оценить не из чего (аналогов с слабым акб нет)", rxs["plan"]["best"] == "B" and rxs["plan"]["A"] is None, rxs["plan"]["best"])
check("XS: цена выставления = медиана 34 объявлений (445)", cx["list"] == k.rnd5(stx["med"]) == 445, cx)
check("XS: быстрая продажа = нижняя четверть, округлено ВНИЗ до 5 (q1 387,5 → 385)", cx["quick"] == k.floor5(stx["q1"]) == 385, cx)
check("XS: целевая прибыль = 12% от быстрой, вверх до 5 (50)", cx["target"] == 50, cx["target"])
check("XS: лимит до ремонта = 385 − 0 − 50 = 335", cx["raw"] == 335 and cx["limit"] == 335, cx)
check("XS: ремонт не известен — не выдуман, лимит предварительный", cx["rep_unknown"] and cx["rep_hi"] == 0 and not cx["final"], cx)
check("XS: запас на ремонт 335 − 250 = 85; прибыль до ремонта 135 / 195", cx["gap"] == 85 and cx["profit"] == 135 and cx["profit_opt"] == 195, cx)
check("XS: вывод «недостаточно данных» с конкретикой (ремонт ≤ 85 BYN)", rxs["decision"][0] == "unknown" and rxs["decision"][1].startswith(FOUR[3]) and "85 BYN" in rxs["decision"][1], rxs["decision"])

# известная цена замены аккумулятора: ремонт вычитается один раз, вывод однозначный
for repair, price_kop, code, limit in ((60, 25000, "buy", 275), (120, 25000, "bargain", 215), (200, 25000, "skip", 135), (340, 25000, "skip", 0)):
    _a, _f, _r = xs(price_kop, repair={"battery": repair})
    c_ = _r["calc"]
    check(f"XS ремонт {repair}: лимит = 385 − {repair} − 0 − 50, ремонт один раз", c_["final"] and c_["rep_hi"] == repair and c_["limit"] == limit, c_)
    check(f"XS ремонт {repair}: прибыль = 385 − 250 − {repair}", c_["profit"] == 385 - 250 - repair and c_["profit_opt"] == 445 - 250 - repair, c_)
    check(f"XS ремонт {repair}: вывод {code}", _r["decision"][0] == code, _r["decision"])
_a, _f, _r = xs(25000, repair={"battery": 120})
check("XS ремонт 120: «только после торга до 215 BYN»", _r["decision"][1].startswith("Покупать только после торга до 215 BYN"), _r["decision"])
_a, _f, _r = xs(25000, "Состояние хорошее, акб 74%. Без торга.", repair={"battery": 120})
check("XS ремонт 120 и «без торга»: не покупать", _r["decision"][0] == "skip" and "без торга" in _r["decision"][1], _r["decision"])
# прочие расходы вычитаются один раз
k.EXTRA_COSTS_BYN = 10
_a, _f, _r = xs(25000, repair={"battery": 60})
c_ = _r["calc"]
check("прочие расходы: лимит 265 (−10 один раз), прибыль 65", c_["limit"] == 265 and c_["profit"] == 385 - 250 - 60 - 10, c_)
k.EXTRA_COSTS_BYN = 0
# цена выше лимита при неизвестном ремонте
_a, _f, _r = xs(38000)
check("XS 380 при лимите 335 и неизвестном ремонте: торг до «335 минус ремонт»", _r["decision"][0] == "bargain" and _r["decision"][1].startswith("Покупать только после торга до 335 BYN минус ремонт"), _r["decision"])
_a, _f, _r = xs(45000)
check("XS 450: не покупать (выше лимита на 24%)", _r["decision"][0] == "skip" and _r["decision"][1].startswith(FOUR[2]), _r["decision"])
# аналоги с таким же дефектом (аккумулятор в заголовке) — оценка по ним, ремонт не вычитается
same = [[800 + i, 280 + i * 10, 64, k.F_DEF | k.F_KINDS["battery"], 1, 0] for i in range(4)]
_a, _f, _r = xs(25000, repair={"battery": 60}, extra=same)
c_ = _r["calc"]
check("XS: 4 аналога с акб в заголовке -> оценка по ним", _r["basis"] == "defect" and _r["found"] == 4 and _r["like_n"] == 4, (_r["basis"], _r["found"]))
ca = _r["plan"]["A"]
check("XS вариант 1 по аналогам с дефектом: ремонт НЕ вычитается (даже при известной цене)", ca["rep_hi"] == 0 and ca["final"] and ca["raw"] == ca["quick"] - ca["target"], ca)
check("XS вариант 2: ремонт вычтен один раз", _r["plan"]["B"]["rep_hi"] == 60 and _r["plan"]["B"]["raw"] == _r["plan"]["B"]["quick"] - 60 - _r["plan"]["B"]["target"], _r["plan"]["B"])
# подозрительно низкая цена (вдвое ниже рынка, дефектов нет): «покупать» не говорим
_a, _f, _r = xs(10000, "Состояние хорошее, акб 90%.")
check("XS 100 BYN (вдвое ниже рынка): не «покупать», а проверить iCloud/обман", _r["decision"][0] == "unknown" and "вдвое ниже рынка" in _r["decision"][1], _r["decision"])
# мало аналогов
_a, _f, _r = xs(25000, n=2)
check("XS: 2 аналога -> few, конкретная причина", _r["status"] == "few" and "найдено только 2" in _r["decision"][1], (_r["status"], _r["decision"]))
_a, _f, _r = xs(25000, n=4)
check("XS: 4 аналога -> ориентиры есть, но вывод «недостаточно данных»", _r["status"] == "ok" and _r["calc"] and _r["decision"][0] == "unknown" and "аналогов мало" in _r["decision"][1], _r["decision"])
# любой вывод начинается с одной из четырёх фраз
for repair in (None, {"battery": 60}, {"battery": 400}):
    for price_kop in (0, 5000, 25000, 38000, 60000):
        _a, _f, _r = xs(price_kop, repair=repair)
        check(f"вывод — одна из четырёх фраз ({repair}, {price_kop})", _r["decision"][1].startswith(FOUR), _r["decision"])
k.REPAIR_COSTS.clear()

print("итого ошибок (оценка):", bad)
sys.exit(1 if bad else 0)
