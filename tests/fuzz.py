"""Стресс-тест оценки: тысячи случайных объявлений и наборов аналогов. Проверяются инварианты (формулы, согласованность решений,
формат сообщения), а не конкретные числа. Запуск: python tests/fuzz.py (FUZZ_N — число прогонов, FUZZ_SEED — зерно)."""
import html
import os
import random
import re
import sys
import time
from pathlib import Path
os.environ.update(TG_TOKEN="t", TG_CHAT_ID="1")
for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MODELS", "REPAIR_COSTS", "HOME_REGION", "TARGET_PROFIT_BYN",
            "RISK_RESERVE_PCT", "REPAIR_OVERRUN_PCT", "PHOTOS_MAX"):
    os.environ.pop(key, None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fresh_dir  # noqa: E402
tmp = fresh_dir()
sys.path.insert(0, str(tmp))
import kufar_bot as k  # noqa: E402

random.seed(int(os.environ.get("FUZZ_SEED", "7")))
LABELS = ["iPhone 11", "iPhone X", "iPhone XS Max", "iPhone 7 Plus", "iPhone 8", "Galaxy S9+", "Galaxy S7 Edge", "iPhone 6s", "iPod touch 5",
          "iPhone SE (2020)", "iPhone SE", "iPhone XS"]
DESCS = ["", "разбит экран", "акб 70%", "акб 92%", "на запчасти", "не включается", "icloud заблокирован", "идеал, акб 95%, полный комплект", "торг",
         "без торга", "после воды", "face id не работает", "договорная", "всё работает", "царапины на корпусе", "замена экрана", "камера не работает",
         "не заряжается", "коробка, зарядка, чехол", "только телефон", "динамик хрипит", "был ремонт", "icloud чистый, face id работает"]
REGS = ["Минск", "Минская область", "Брестская область", "Гомельская область", "", "Витебская", "Могилёвская область", "Гродно"]
REPAIR_FORMS = [{}, {}, {"screen": 80}, {"battery": 40}, {"screen": [70, 110]}, {"screen": {"parts": [40, 60], "labor": 30}},
                {"screen": 80, "battery": 40, "camera": 60, "charging": 30, "comms": 30, "biometric": 90},
                {"battery": {"parts": 25, "labor": [10, 20]}, "camera": [50, 90]}]
PHOTO_BITS = [
    {"status": "none"}, {"status": "no_llm"}, {"status": "no_photos"}, {"status": "no_download"}, {"status": "error"}, {"status": "off"},
    {"status": "analyzed", "n": 3, "total": 5, "findings": [], "kit": [], "mismatch": "", "quality": "хорошее"},
    {"status": "analyzed", "n": 2, "total": 2, "quality": "плохое", "kit": ["коробка"], "mismatch": "",
     "findings": [{"part": "экран", "kind": "screen", "what": "трещина <b>в углу</b> & скол", "conf": "высокая", "check": "тач по всей площади"}]},
    {"status": "analyzed", "n": 4, "total": 9, "quality": "среднее", "kit": ["коробка", "наушники", "чехол"], "mismatch": "в тексте «идеал», а на экране трещина",
     "findings": [{"part": "камера", "kind": "camera", "what": "пятно на линзе", "conf": "средняя", "check": "снимок при ярком свете"},
                  {"part": "рамка/корпус", "kind": "cosmetic", "what": "царапины", "conf": "высокая", "check": ""},
                  {"part": "другое", "kind": "other", "what": "вмятина", "conf": "низкая", "check": "осмотр"}]},
]
FOUR = ("Покупать по текущей цене", "Покупать только после торга", "Не покупать для перепродажи", "Пока недостаточно данных для решения")
bad = 0


def fail(msg, *a):
    global bad
    bad += 1
    if bad <= 15:
        print("FAIL", msg, *[str(x)[:400] for x in a])


def near(a, b, eps=1e-6):
    return abs(a - b) <= eps


def check_calc(c, name, price, ctx):
    """Арифметика одного расчёта сделки (deal_calc)."""
    if c["quick"] > c["list"]:
        fail(name, "быстрая > выставления", c, ctx)
    if not near(c["costs"], c["extra"] + c["rep_hi"] + c["overrun"] + c["reserve"]):
        fail(name, "расходы не сходятся", c, ctx)
    if not near(c["costs_opt"], c["extra"] + c["rep_lo"] + c["reserve"]):
        fail(name, "оптимистичные расходы не сходятся", c, ctx)
    if not near(c["overrun"], c["rep_hi"] * k.REPAIR_OVERRUN_PCT / 100):
        fail(name, "запас на удорожание не сходится", c, ctx)
    if not near(c["raw"], c["quick"] - c["costs"] - c["target"]):
        fail(name, "максимум: формула «продажа − расходы − цель» не сходится", c, ctx)
    if c["limit"] != k.floor5(c["raw"]) or c["limit"] % 5 or c["limit"] < 0 or c["limit"] > max(0, c["raw"]):
        fail(name, "максимум: округление/знак", c, ctx)
    if c["desired"] != k.floor5(c["quick"] - c["costs"] - k.DESIRED_MARGIN * c["target"]):
        fail(name, "желаемая цена не сходится", c, ctx)
    if not (0 <= c["desired"] <= c["limit"] <= c["walk"]):
        fail(name, "порядок уровней цены: желаемая ≤ максимум ≤ отказ", c, ctx)
    if c["walk"] != k.floor5(c["list"] - c["costs_opt"]):
        fail(name, "цена отказа не сходится", c, ctx)
    if k.TARGET_PROFIT_BYN > 0:
        if c["target"] != k.TARGET_PROFIT_BYN:
            fail(name, "целевая прибыль из TARGET_PROFIT_BYN не применена", c, ctx)
    elif c["target"] % 5 or c["target"] < k.MIN_PROFIT_BYN:
        fail(name, "целевая прибыль по умолчанию", c, ctx)
    if c["reserve"] and (not k.RISK_RESERVE_PCT or c["reserve"] != k.ceil5(k.RISK_RESERVE_PCT / 100 * c["quick"])):
        fail(name, "резерв не по формуле", c, ctx)
    if c["final"] != (not c["rep_unknown"]):
        fail(name, "final и rep_unknown не согласованы", c, ctx)
    if price:
        if not near(c["profit"], c["quick"] - price - c["costs"]):
            fail(name, "прибыль (быстрая продажа) не сходится", c, price, ctx)
        if not near(c["profit_opt"], c["list"] - price - c["costs_opt"]):
            fail(name, "прибыль (по выставлению) не сходится", c, price, ctx)
        if c["gap"] != c["limit"] - price:
            fail(name, "запас до максимума не сходится", c, price, ctx)
        if c.get("roi") is not None and not near(c["roi"], c["profit"] / (price + c["costs"])):
            fail(name, "ROI не сходится", c, price, ctx)
    elif "profit" in c:
        fail(name, "прибыль посчитана без цены", c, ctx)


k._MARKET_REFRESHES["n"] = 99
N = int(os.environ.get("FUZZ_N", "1500"))
stat = {}
for i in range(N):
    label = random.choice(LABELS)
    key = k.market_key(label)
    n = random.choice([0, 1, 2, 3, 4, 5, 6, 8, 12, 12, 25, 25, 40, 60])
    base_price = random.choice([50, 120, 300, 600, 1500])
    mode = random.choice(["normal", "equal", "wide", "outliers"])
    items = []
    for j in range(n):
        if mode == "equal":
            p = base_price
        elif mode == "wide":
            p = base_price * random.uniform(0.2, 3)
        elif mode == "outliers":
            p = base_price * random.choice([0.001, 1, 1, 1.1, 0.9, 40])
        else:
            p = base_price * random.uniform(0.85, 1.2)
        flags = random.choice([0, 0, 0, 0, k.F_DEF, k.F_DEF | k.F_PARTS | k.F_CRIT, k.F_NEW, k.F_REFURB, k.F_SHOP, k.F_DEF | k.F_SHOP,
                               k.F_DEF | k.F_KINDS["screen"], k.F_DEF | k.F_KINDS["battery"], k.F_DEF | k.F_KINDS["battery"] | k.F_KINDS["screen"],
                               k.F_GOOD, k.F_GOOD | k.F_BOX, k.F_BOX, k.F_COSM, k.F_KINDS["battery"], k.F_KINDS["camera"] | k.F_DEF,
                               k.F_KINDS["charging"] | k.F_DEF, k.F_KINDS["lock"] | k.F_DEF | k.F_CRIT, k.F_KINDS["biometric"] | k.F_DEF])
        gen = random.choice([2016, 2020, 2022]) if key == "iPhone SE" else 0
        items.append([1000 + j, max(1, int(p)), random.choice([0, 16, 32, 64, 64, 128, 256]), flags, random.randint(0, 7), gen])
    k.STATE["market"][key] = {"t": int(time.time() - random.choice([0, 3600, 40 * 3600])), "items": items}
    k.REPAIR_COSTS.clear()
    k.REPAIR_COSTS.update(random.choice(REPAIR_FORMS))
    k.EXTRA_COSTS_BYN = random.choice([0, 0, 7, 20])
    k.TARGET_PROFIT_BYN = random.choice([0, 0, 0, 30, 100])
    k.RISK_RESERVE_PCT = random.choice([0, 5, 5, 10])
    k.REPAIR_OVERRUN_PCT = random.choice([0, 15, 15, 30])
    price = random.choice([0, 0, 1, 10, int(base_price * random.uniform(0.3, 1.8)), int(base_price)])
    mem = random.choice(["", "64gb", "128 гб", "256", "1tb"])
    desc = " ".join(random.sample(DESCS, random.randint(0, 3)))
    title = f"{label.replace(' (2020)', ' 2020')} {mem} {random.choice(['', 'торг', 'срочно'])}".strip()
    ad = {"ad_id": random.choice([9999, 1000 + random.randint(0, 60)]), "type": "sell", "company_ad": random.random() < 0.2,
          "price_byn": str(price * 100), "price_usd": str(price * 30), "subject": title, "ad_link": "https://www.kufar.by/item/9999",
          "ad_parameters": [{"p": "condition", "vl": random.choice(["Б/у", "Новый", "б/у"])}, {"p": "region", "vl": random.choice(REGS)}]}
    if desc:
        ad["body_short"] = desc
    ctx = (title, desc, n, mode)
    try:
        facts = k.rule_facts(ad)
        if random.random() < 0.35:  # результаты анализа фото (как после merge_photos), в том числе с HTML-символами в тексте
            facts["photo"] = dict(random.choice(PHOTO_BITS), **{})
            for f in facts["photo"].get("findings", []):
                if f["conf"] == "высокая" and f["kind"] in ("screen", "cosmetic", "camera") and facts["photo"].get("quality") != "плохое":
                    facts["defects"].setdefault(f["kind"], "по фото: " + f["what"])
        ap = k.appraise(ad, facts)
        msg = k.build_full_message(ad, facts, ap)
    except Exception as e:
        fail("исключение", repr(e), ctx)
        continue
    stat[ap["status"]] = stat.get(ap["status"], 0) + 1
    if ap["status"] == "error":
        fail("status=error", ctx)
    sev = k.max_severity(facts["defects"])
    code, text = ap["decision"]
    plan = ap.get("plan") or {}
    # ---- сообщение ----
    if len(msg) > 3990:
        fail("длина", len(msg))
    cut = "\n…\n" in msg  # крайний случай: середина сообщения обрезана ради итога и ссылки
    if re.search(r"\bnan\b|\binf\b|\bNone\b|[{}]", msg):
        fail("nan/inf/None/фигурные скобки в тексте", msg[:300])
    if "<" in re.sub(r"</?b>", "", msg) or re.search(r"&(?!amp;|lt;|gt;|quot;|#)", msg):
        fail("сырой < или & в тексте", msg[:300])
    if msg.count("<b>") != msg.count("</b>"):
        fail("теги не парные")
    if html.escape(ad["ad_link"]) not in msg:
        fail("ссылка потеряна")
    if msg.count("✅ <b>Итоговая рекомендация:</b>") != 1:
        fail("итог не один", msg[-300:])
    if not text.startswith(FOUR):
        fail("вывод не из четырёх фраз", text)
    for bad_phrase in ("НЕДОСТАТОЧНО ДАННЫХ", "прибыль не считаю", "стоимость ремонта неизвестна", "Вывод для перепродажи"):
        if bad_phrase in msg:
            fail("запрещённая формулировка", bad_phrase)
    if re.search(r"(?<![\w.])[XY]\s*(?:BYN|%)", msg.replace(html.escape(title), "")):
        fail("в сообщении остались заглушки X/Y из шаблона", msg[:300])
    if not cut and not re.search(r"По фото", msg):
        fail("нет строки про фото", msg[:300])
    if ap["status"] == "ok" and "не сделок" not in msg:
        fail("нет оговорки «цены объявлений, не сделок»")
    if not cut and "Комплект:" not in msg:
        fail("нет строки про комплект")
    # ---- короткое сообщение (то, что уходит в Telegram по умолчанию) ----
    sm = k.build_short_message(ad, facts, ap)
    verdicts = len(re.findall(r"<b>(?:ВЫГОДНО|НЕВЫГОДНО(?: по текущей цене)?|НЕДОСТАТОЧНО ДАННЫХ)</b>", sm))
    if verdicts != 1:
        fail("короткое: вердикт не один", sm)
    if len(sm) > 1100:
        fail("короткое: слишком длинное", len(sm), sm)
    if sm.count("<b>") != sm.count("</b>") or re.search(r"\bnan\b|\binf\b|\bNone\b|[{}]", sm):
        fail("короткое: теги/nan/None", sm[:300])
    if html.escape(ad["ad_link"]) not in sm:
        fail("короткое: ссылка потеряна")
    if desc and len(desc) > 40 and desc[:40] in sm:
        fail("короткое: пересказ описания продавца", sm)
    shown_price = re.search(r"Цена продавца: ([\d ]+) BYN", sm)
    if facts["price"] and (not shown_price or int(shown_price.group(1).replace(" ", "")) != round(facts["price"])):
        fail("короткое: цена продавца не та", facts["price"], sm[:120])
    if not facts["price"] and "не указана — нужно уточнить" not in sm:
        fail("короткое: нет «цену нужно уточнить»", sm[:120])
    if code == "buy" and ap.get("conf") != "низкая" and "✅ <b>ВЫГОДНО</b>" not in sm:
        fail("короткое: buy без ВЫГОДНО", sm)
    if (code == "skip" or sev >= 3) and "<b>НЕВЫГОДНО" not in sm:
        fail("короткое: skip без НЕВЫГОДНО", code, sm)
    if code == "unknown" and "НЕДОСТАТОЧНО ДАННЫХ" not in sm:
        fail("короткое: unknown без НЕДОСТАТОЧНО ДАННЫХ", sm)
    if "Уверенность:" in sm and "не сделок" not in sm:
        fail("короткое: нет оговорки «цены объявлений, не сделок»", sm)
    num = lambda m_: int(m_.group(1).replace(" ", "").replace("−", "-"))  # noqa: E731
    m_lim = re.search(r"Максимальная цена покупки: ([\d ]+) BYN", sm)
    m_q = re.search(r"Цена для быстрой продажи: ([\d ]+) BYN", sm)
    if m_lim and m_q and num(m_lim) > num(m_q):
        fail("короткое: максимум покупки выше быстрой продажи", sm)
    stat["short:limit"] = stat.get("short:limit", 0) + bool(m_lim and m_q)
    if not all(h_ in sm for h_ in ("<b>РЫНОК</b>", "<b>ПОКУПКА</b>", "<b>ИТОГ</b>")):
        fail("короткое: нет одного из разделов РЫНОК / ПОКУПКА / ИТОГ", sm)
    if any(x_ in sm for x_ in ("ROI", "По описанию", "По фото", "⚡", "💸", "📈")):
        fail("короткое: старые подписи или отдельный раздел описания/фото", sm)
    _b, c_ = k._shown_variant(ap)
    m_pr = re.search(r"Предполагаемая прибыль после расходов: ([+−\-]?[\d ]+) BYN", sm)
    m_roi = re.search(r"Доходность на вложенные деньги: ([+−\-]?\d+)%", sm)
    if m_roi:
        stat["short:roi"] = stat.get("short:roi", 0) + 1
        # один сценарий: покупка по цене продавца, продажа по цене для быстрой продажи; доходность = прибыль / вложено
        exp_profit = c_["quick"] - facts["price"] - c_["costs"]
        exp_roi = round(exp_profit / (facts["price"] + c_["costs"]) * 100)
        if not m_pr or abs(num(m_pr) - round(exp_profit)) > 1 or abs(num(m_roi) - exp_roi) > 1 or not c_["final"]:
            fail("короткое: прибыль и доходность не из одного сценария / формула не та", exp_profit, exp_roi, sm)
        if m_q and num(m_q) != c_["quick"]:
            fail("короткое: доходность посчитана не для показанной цены быстрой продажи", sm)
    if c_ and not c_["final"] and m_roi:
        fail("короткое: процент доходности при неизвестной цене ремонта (выдуман)", sm)
    # ---- решение ----
    if sev >= 3 and code != "skip":
        fail("критичный дефект без отказа", code, facts["defects"])
    if ap["status"] != "ok" and sev < 3 and code != "unknown":
        fail("вывод без данных", ap["status"], code)
    if ap["status"] != "ok" and ap["verdict"] is not None:
        fail("вердикт без данных", ap["status"], ap["verdict"])
    if ap["status"] in ("few", "se_gen", "no_market", "no_model") and any(v in msg for v in ("ОЧЕНЬ ВЫГОДНО", "<b>ВЫГОДНО", "<b>ДОРОГО", "<b>НЕВЫГОДНО", "<b>СРЕДНИЙ")):
        fail("вердикт в сообщении без данных", ap["status"])
    if ap["status"] != "ok":
        continue
    # ---- оценка (status ok) ----
    snap, clean, asis = ap["snap"], ap["clean"], plan.get("asis")
    A, B, up, best = plan.get("A"), plan.get("B"), plan.get("upper"), plan.get("best")
    if sum(r["all"] for r in snap["rows"].values()) + snap["undefined"] != snap["total"]:
        fail("категории не покрывают все аналоги", snap["total"], snap["undefined"], {c: r["all"] for c, r in snap["rows"].items()})
    for c_, r in snap["rows"].items():
        if r["n"] > r["all"] or (r["st"] and r["st"]["n"] != r["n"]):
            fail("строка категории: счётчики", c_, r["n"], r["all"])
    cat = k.ad_cat(facts)
    if cat is None:
        fail("у объявления не определена категория", facts["defects"])
    if sev >= 3 and cat != "faulty":
        fail("критичный дефект не в «неисправных»", cat, facts["defects"])
    if asis:
        if asis["src"] not in ("ok", "clean", "same", "cat", "interp"):
            fail("неизвестный источник оценки", asis["src"])
        if (cat in ("ok", "unk")) != (asis["src"] in ("ok", "clean")):
            fail("источник оценки не соответствует категории", cat, asis["src"])
        if asis["src"] == "interp":
            if asis["found"] or asis["n"] or asis["st"] is not None or not asis["between"][0] < asis["between"][1]:
                fail("расчёт между категориями выдан за найденное", asis)
        elif not asis["found"] or asis["n"] < k.REF_MIN or asis["st"]["n"] != asis["n"]:
            fail("найденная оценка без аналогов", asis)
        if asis["quick"] > asis["list"] or asis["quick"] < 0:  # 0 возможен, если все аналоги стоят ~1 BYN (приманка): тогда решение «не покупать»
            fail("оценка «как есть»: быстрая/выставления", asis)
    if bool(A) != bool(asis):
        fail("вариант 1 и оценка «как есть» не согласованы", bool(A), bool(asis))
    if A:
        check_calc(A, "A", facts["price"], ctx)
        if A["rep_hi"] or A["rep_lo"] or A["rep_unknown"] or A["overrun"]:
            fail("ремонт вычтен в варианте «как есть» (двойной учёт)", A)
        if (A["quick"], A["list"]) != (asis["quick"], asis["list"]):
            fail("вариант 1 считан не по оценке «как есть»", A, asis)
        if A["reserve"] and not plan["unconfirmed"]:
            fail("резерв при полностью подтверждённых функциях", A)
    if B:
        check_calc(B, "B", facts["price"], ctx)
        rp = plan["repair"]
        if sev >= 3 or not rp["needs"]:
            fail("вариант 2 при критичном дефекте или без ремонта", rp, facts["defects"])
        if not near(B["rep_hi"], rp["hi"]) or not near(B["rep_lo"], rp["lo"]) or B["rep_unknown"] != rp["unknown"]:
            fail("ремонт в варианте 2 не равен плану ремонта (один раз)", B, rp)
        if not clean["st"] or (B["quick"], B["list"]) != (k.floor5(clean["st"]["q1"]), k.rnd5(clean["st"]["med"])):
            fail("вариант 2 считан не по исправным аналогам", B)
        if not B["reserve"] and k.RISK_RESERVE_PCT and B["quick"] > 0:
            fail("в варианте 2 нет резерва", B)
        for it in rp["items"]:
            if not (0 <= it["lo"] <= it["hi"]):
                fail("диапазон ремонта перевёрнут", it)
            if it["src"] == "REPAIR_COSTS" and it["code"] not in k.REPAIR_COSTS:
                fail("цена ремонта выдумана", it)
        if B["final"] != (not rp["unknown"]):
            fail("final не согласован с неизвестным ремонтом", B, rp)
        if not B["final"] and not msg.count("до вычета ремонта") and not cut:
            fail("ремонт не задан, а расчёт не помечен «до вычета ремонта»", rp)
        if plan["breakeven"] is not None and A and plan["breakeven"] % 5:
            fail("точка безубыточности ремонта", plan["breakeven"])
    elif plan["breakeven"] is not None or plan["sens"]:
        fail("безубыточность ремонта без варианта 2")
    if not B and plan["repair"]["needs"] and sev < 3 and clean["st"]:
        fail("ремонт нужен, исправные аналоги есть, а варианта 2 нет", plan["repair"])
    if sev >= 3 and (B or best == "B"):
        fail("вариант 2 при критичном дефекте")
    if best == "B" and A and B["final"]:
        gain = B["profit"] - A["profit"] if facts["price"] else B["limit"] - A["limit"]
        if gain < max(A["target"] / 2, 10):
            fail("вариант 2 выбран без заметного выигрыша", gain, A["target"])
    if best == "A" and A and B and B["final"]:
        gain = B["profit"] - A["profit"] if facts["price"] else B["limit"] - A["limit"]
        if gain >= max(A["target"] / 2, 10):
            fail("вариант 2 заметно выгоднее, а выбран вариант 1", gain, A["target"])
    if (best == "A" and not A) or (best == "B" and not B) or (best is None and (A or B)) or (best == "B" and not B["final"] and A):
        fail("лучший вариант не согласован с расчётами", best, bool(A), bool(B))
    if up and (A or B):
        fail("верхняя граница при наличии вариантов")
    if (ap["calc"] is not None) != bool(best) or (best and ap["calc"] is not plan[best]):
        fail("calc не равен лучшему варианту")
    if ap["like_for_like"] != bool(asis and asis["found"]):
        fail("like_for_like не согласован с оценкой", ap["like_for_like"], asis)
    # статистика, вердикт
    st = ap["stats"]
    if st and not (st["min"] <= st["q1"] <= st["med"] <= st["q3"] <= st["max"]):
        fail("квартили не по порядку", st)
    if any(c[0] == ad["ad_id"] for c in ap["comps"]):
        fail("объявление среди собственных аналогов")
    if len(ap["comps"]) > 3:
        fail("слишком много аналогов")
    if ap["verdict"] is not None and not ap["like_for_like"]:
        fail("вердикт цены при сравнении не с такими же")
    if facts["price"] and ap["verdict"] is not None:
        if ap["verdict"] in ("ОЧЕНЬ ВЫГОДНО", "ВЫГОДНО") and ap["pct"] > 0:
            fail("«выгодно», но дороже медианы", ap["pct"], ap["verdict"])
        if ap["verdict"] in ("ДОРОГО", "НЕВЫГОДНО") and ap["pct"] < 0:
            fail("«дорого», но дешевле медианы", ap["pct"], ap["verdict"])
    # сообщение и расчёты согласованы
    if not cut:
        for c_, nm in ((A, "A"), (B, "B")):
            if c_ and k.levels_line(c_) not in msg:
                fail("в сообщении нет трёх уровней цены", nm, k.levels_line(c_))
        if A and k.calc_line(A, "быстрая продажа") not in msg:
            fail("в сообщении нет формулы варианта 1")
        if best and ("Цена покупки" not in msg or "отказ выше" not in msg):
            fail("нет уровней цены")
        if facts["price"] and A and "ROI" not in msg:
            fail("прибыль варианта 1 показана без ROI")
    # ---- решение по цене ----
    c = plan.get(best) if best else up
    price = facts["price"]
    weak = ap.get("conf") == "низкая" or bool(asis and asis["src"] == "interp")
    suspicious = bool(sev < 2 and clean["st"] and price and price < 0.5 * clean["st"]["med"])
    stat[f"{best}/{code}"] = stat.get(f"{best}/{code}", 0) + 1
    for tag in ((f"src:{asis['src']}",) if asis else ()) + (("B-final" if B["final"] else "B-нужна-цена-ремонта",) if B else ()) + (("sens",) if plan["sens"] else ()):
        stat[tag] = stat.get(tag, 0) + 1
    if code == "buy":
        if not (c and price and best and price <= c["limit"] and c["final"] and not ap["thin"] and sev < 3):
            fail("«покупать» при цене выше максимума / неизвестном ремонте / малой выборке", code, c, price)
        if weak and price > c["desired"]:
            fail("«покупать» при ненадёжной оценке без запаса", c, price)
        if suspicious:
            fail("«покупать» при подозрительно низкой цене", price, clean["st"]["med"])
    if code == "bargain":
        if not (c and price and best and (price > c["limit"] or (c["final"] and weak and price > c["desired"]))):
            fail("«торг» без причины", c, price)
        if facts["bargain"] == "no" and price > c["limit"]:
            fail("«торг» при «без торга» у продавца", facts["bargain"], price, c["limit"])
    if code == "skip" and sev < 3:
        if not (c and (c["limit"] <= 0 or (price and price > c["limit"]))):
            fail("«не покупать» при цене в пределах максимума", c, price)
    if best and c and c["final"] and price and not ap["thin"] and price <= c["desired"] and not suspicious and sev < 3 and code != "buy":
        fail("цена не выше желаемой, оценка надёжна, а вывод не «покупать»", code, text, c, price)
    if c and not price and code != "unknown" and sev < 3:
        fail("вывод без цены не «недостаточно данных»", code)
    if best and c and not c["final"] and code == "buy":
        fail("«покупать» при неизвестной цене ремонта")
    if not best and not up and code != "unknown" and sev < 3:
        fail("вывод без оценки состояния", code)
    if up and not best and code == "buy":
        fail("«покупать» по одной верхней границе")
    if ap["thin"] and code in ("buy", "bargain"):
        fail("рекомендация на малой выборке", ap["thin"], code)

print("прогонов:", N, "| статусы:", stat, "| ошибок:", bad)
sys.exit(1 if bad else 0)
