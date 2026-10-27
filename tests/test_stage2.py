"""Тесты этапа 2 (без сети): категории состояния, оценка «как есть» и «с ремонтом», три уровня цены, фото (настоящие картинки в запросе
нейросети), комплектация и пять примеров из задания: исправный, разбитый экран, износ аккумулятора, неизвестное состояние,
хорошая комплектация. Ключ -v печатает сообщения целиком; --examples ФАЙЛ записывает пять примеров (вход → расчёт → рекомендация)."""
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.update(TG_TOKEN="t", TG_CHAT_ID="1")
for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MODELS", "REPAIR_COSTS", "HOME_REGION", "TARGET_PROFIT_BYN", "RISK_RESERVE_PCT",
            "REPAIR_OVERRUN_PCT", "PHOTOS_MAX", "MIN_PROFIT_BYN", "MIN_PROFIT_PCT", "EXTRA_COSTS_BYN"):
    os.environ.pop(key, None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fresh_dir  # noqa: E402
tmp = fresh_dir()
sys.path.insert(0, str(tmp))
VERBOSE = "-v" in sys.argv
EXAMPLES = sys.argv[sys.argv.index("--examples") + 1] if "--examples" in sys.argv else None
import kufar_bot as k  # noqa: E402

bad = 0


def check(name, cond, extra=""):
    global bad
    if not cond:
        print("FAIL", name, str(extra)[:900])
        bad += 1


def ad(subject, price=65000, desc="", cond="Б/у", ad_id=9001, region="Минск", images=None):
    d = {"ad_id": ad_id, "type": "sell", "company_ad": False, "price_byn": str(price), "price_usd": "8000",
         "subject": subject, "ad_link": f"https://www.kufar.by/item/{ad_id}",
         "ad_parameters": [{"p": "condition", "vl": cond}, {"p": "region", "vl": region}, {"p": "area", "vl": "Центральный"}]}
    if desc:
        d["body_short"] = desc
    if images is not None:
        d["images"] = images
    return d


def put_market(key, items, age=0):
    k.STATE["market"][key] = {"t": int(time.time() - age), "items": items}


def defaults():
    """Настройки по умолчанию (как в боте без переменных): цель = max(15, 12% от быстрой продажи), резерв 5%, запас на ремонт 15%."""
    k.MIN_PROFIT_BYN, k.MIN_PROFIT_PCT, k.EXTRA_COSTS_BYN = 15, 12, 0
    k.TARGET_PROFIT_BYN, k.RISK_RESERVE_PCT, k.REPAIR_OVERRUN_PCT = 0, 5, 15
    k.REPAIR_COSTS.clear()


K = k.F_KINDS
k._MARKET_REFRESHES["n"] = 99  # сеть не трогаем
defaults()

# =====================================================================================================================
# 1. Категории состояния: «исправен» только если это сказано словами; «дефектов нет в тексте» — отдельная категория
# =====================================================================================================================
def cat_of(desc, subject="iPhone XS 64gb"):
    return k.ad_cat(k.rule_facts(ad(subject, desc=desc)))


for text, want in (("Идеальное состояние, всё работает", "ok"), ("без царапин, без дефектов", "ok"), ("Продаю", "unk"), ("", "unk"),
                   ("Состояние хорошее", "unk"), ("Состояние хорошее, акб 74%", "minor"), ("есть царапины на корпусе", "minor"),
                   ("замена экрана, не оригинал", "minor"), ("был ремонт, вскрывали", "minor"), ("не идеал, есть царапины", "minor"),
                   ("разбит экран", "visible"), ("камера не работает", "visible"), ("идеал, но разбит экран", "visible"),
                   ("не заряжается", "faulty"), ("после воды", "faulty"), ("не включается", "faulty"), ("icloud заблокирован", "faulty"),
                   ("face id не работает", "faulty"), ("динамик хрипит", "faulty"), ("продаю на запчасти", "faulty")):
    check(f"категория: «{text}» -> {want}", cat_of(text) == want, cat_of(text))
check("нет дефектов в тексте ≠ исправен", cat_of("") != "ok" and cat_of("Продаю iPhone") != "ok")
check("старый кеш (флаг дефекта без вида) в категорию не попадает", k.comp_cat(k.F_DEF) is None)
check("флаг «идеал» у аналога -> исправные; без него -> не подтверждено", k.comp_cat(k.F_GOOD) == "ok" and k.comp_cat(0) == "unk")
check("«идеал» вместе с дефектом = дефект, а не «исправен»", k.comp_cat(k.defect_flags({"screen": "x"}, True)) == "visible")
check("is_good: «не идеал» — не подтверждение", not k.is_good("не идеал") and k.is_good("состояние идеал"))


def xs_market(box=True, extra=()):
    """52 синтетических аналога iPhone XS 64 ГБ: 6 «идеал», 30 без пометок, 5 мелких дефектов, 6 с экраном, 5 неисправных."""
    its, i = [], 1000

    def add(price, flags, region=1):
        nonlocal i
        i += 1
        its.append([i, price, 64, flags, region, 0])
    for p in (390, 400, 410, 420, 430, 440):
        add(p, k.F_GOOD | (k.F_BOX if box else 0))
    for j in range(30):
        add(320 + j * 5, (k.F_BOX if (box and j % 3 == 0) else 0), 1 if j % 2 == 0 else 5)
    for p in (285, 295, 300, 310, 320):
        add(p, K["battery"] | k.F_DEF if p % 10 == 5 else k.F_COSM)
    for p in (180, 200, 215, 230, 250, 260):
        add(p, K["screen"] | k.F_DEF)
    for p in (80, 110, 130, 150, 165):
        add(p, K["biometric"] | k.F_DEF)
    for p in extra:
        add(p, k.F_DEF)  # запись из старого кеша: дефект есть, а какой — неизвестно
    put_market("iPhone XS", its)


xs_market()
a0 = ad("iPhone XS 64gb", 30000, "Продаю.")
snap = k.market_snapshot(k.STATE["market"]["iPhone XS"]["items"], k.rule_facts(a0), 9001)
rows = {c: snap["rows"][c]["n"] for c in k.CATS}
check("снимок рынка: счётчики по категориям", rows == {"ok": 6, "unk": 30, "minor": 5, "visible": 6, "faulty": 5} and snap["total"] == 52, (rows, snap["total"]))
check("снимок: медианы категорий убывают от исправных к неисправным",
      [snap["rows"][c]["st"]["med"] for c in k.CATS][1:] == sorted([snap["rows"][c]["st"]["med"] for c in k.CATS][1:], reverse=True))
xs_market(extra=(111, 222, 333))
snap = k.market_snapshot(k.STATE["market"]["iPhone XS"]["items"], k.rule_facts(a0), 9001)
check("старый кеш: 3 записи вне категорий, все аналоги учтены", snap["undefined"] == 3 and snap["total"] == 55
      and sum(r["all"] for r in snap["rows"].values()) == 52, (snap["undefined"], snap["total"]))
xs_market()

# =====================================================================================================================
# 2. Пять примеров из задания (вход → расчёт → рекомендация), настройки по умолчанию
# =====================================================================================================================
CASES = [
    # (метка, описание, цена в копейках, цены ремонта REPAIR_COSTS)
    ("1. Исправный телефон", "Идеальное состояние, всё работает. Акб 91%. iCloud чистый, Face ID работает. Полный комплект: коробка, кабель, зарядка. Торг.", 38000, {}),
    ("2. Разбитый экран (цена ремонта не задана)", "Разбит экран, трещина. Остальное работает, акб 88%.", 24000, {}),
    ("2b. Разбитый экран, ремонт 70–100 BYN задан", "Разбит экран, трещина. Остальное работает, акб 88%.", 24000, {"screen": [70, 100]}),
    ("3. Износ аккумулятора 74% (цена замены не задана)", "Состояние хорошее, акб 74%.", 25000, {}),
    ("3b. Износ аккумулятора, замена 40–60 BYN", "Состояние хорошее, акб 74%.", 25000, {"battery": [40, 60]}),
    ("3c. Износ аккумулятора, замена дешёвая: 10 BYN", "Состояние хорошее, акб 74%.", 25000, {"battery": 10}),
    ("4. Неизвестное состояние", "Продаю iPhone XS 64.", 33000, {}),
    ("5. Хорошая комплектация, состояние не подтверждено", "Продаю iPhone XS 64. Есть коробка, чек, наушники, кабель, зарядка.", 34000, {}),
]
RUNS = {}
for n, (title, desc, price, repair) in enumerate(CASES):
    defaults()
    k.REPAIR_COSTS.update(repair)
    xs_market()
    a = ad("iPhone XS 64gb", price, desc, ad_id=9200 + n)
    f = k.rule_facts(a)
    ap = k.appraise(a, f)
    msg = k.build_message(a, f, ap)
    RUNS[title.split(".")[0]] = (title, desc, price, repair, a, f, ap, msg)
    if VERBOSE:
        print("=" * 90, "\n", title, "\n", msg)
    check(f"{title}: статус ok, сообщение в пределах лимита, одна итоговая рекомендация",
          ap["status"] == "ok" and len(msg) <= 3990 and msg.count("✅ <b>Итоговая рекомендация:</b>") == 1, (ap["status"], len(msg)))
    pos = [msg.find(x) for x in ("📱", "💰 Цена продавца", "🔍 <b>Состояние</b>", "📊 <b>Рынок</b>", "💵 <b>Вариант 1", "🔧 <b>Вариант 2", "⚠️ <b>Риски</b>",
                                "✅ <b>Итоговая рекомендация:</b>")]
    check(f"{title}: разделы идут в порядке 📱 💰 🔍 📊 💵 🔧 ⚠️ ✅", all(p >= 0 for p in pos) and pos == sorted(pos), pos)
    check(f"{title}: вывод — одна из четырёх фраз", ap["decision"][1].startswith(
        ("Покупать по текущей цене", "Покупать только после торга до", "Не покупать для перепродажи", "Пока недостаточно данных для решения")), ap["decision"])
    check(f"{title}: рынок назван «цены объявлений, не сделок»; завершённых продаж нет", "Это цены объявлений, не сделок." in msg
          and "завершённ" not in msg.lower() and "проданные" not in msg.lower(), msg[:600])
    check(f"{title}: в тексте нет шаблонных X/Y и фигурных скобок", "{" not in msg and " X BYN" not in msg and " Y BYN" not in msg)
    check(f"{title}: три уровня цены покупки (желаемая, максимум, отказ)", msg.count("Цена покупки: желательно ≤") >= 1 and "максимум <b>" in msg and "отказ выше" in msg)
    check(f"{title}: нет голых отказов от расчёта", all(x not in msg for x in ("стоимость ремонта неизвестна", "прибыль не считаю", "НЕДОСТАТОЧНО ДАННЫХ")))
    check(f"{title}: про фото сказано честно", "По фото: не анализировались — анализ не запускался." in msg)

# --- пример 1: исправный телефон ---
t, d_, p_, rc, a, f, ap, msg = RUNS["1"]
A = ap["plan"]["A"]
check("1: категория «исправные», источник цены — аналоги с подтверждённой исправностью (6 шт.)",
      k.ad_cat(f) == "ok" and ap["plan"]["asis"]["src"] == "ok" and ap["plan"]["asis"]["n"] == 6, ap["plan"]["asis"])
check("1: быстрая 400, выставлять 415; цель 50 (12% от 400); резерва нет — все ключевые функции названы продавцом",
      (A["quick"], A["list"], A["target"], A["reserve"]) == (400, 415, 50, 0) and ap["plan"]["unconfirmed"] == [], (A, ap["plan"]["unconfirmed"]))
check("1: уровни: желательно 325, максимум 350, отказ выше 415", (A["desired"], A["limit"], A["walk"]) == (325, 350, 415), A)
check("1: прибыль при 380 BYN: +20 (быстро) … +35 (по выставлению), ROI ≈ 5%", A["profit"] == 20 and A["profit_opt"] == 35 and abs(A["roi"] - 20 / 380) < 1e-9, A)
check("1: ремонт не нужен — вариант 2 так и сказан", ap["plan"]["B"] is None and "Ремонт не нужен" in msg)
check("1: решение — торг до 350", ap["decision"][0] == "bargain" and ap["decision"][1].startswith("Покупать только после торга до 350 BYN"), ap["decision"])
check("1: формула в сообщении с числами", "Расчёт: 400 (быстрая продажа) − 50 (целевая прибыль) = 350" in msg, msg)
check("1: коробка — только справка по аналогам (+15 BYN), «в расчёт не включено»", "Коробка ≈ +15 BYN к медиане аналогов (11 с коробкой в заголовке и 10 без; в расчёт не включено)" in msg, msg)

# --- пример 2: разбитый экран, цена ремонта не задана ---
t, d_, p_, rc, a, f, ap, msg = RUNS["2"]
pl = ap["plan"]
A, B = pl["A"], pl["B"]
check("2: категория «заметные дефекты», оценка «как есть» по 6 аналогам с экраном в тексте",
      k.ad_cat(f) == "visible" and pl["asis"]["src"] == "same" and pl["asis"]["n"] == 6 and pl["asis"]["found"], pl["asis"])
check("2: вариант 1: быстро 205 / выставлять 220, резерв 15, цель 25 -> максимум 165, желательно 150, отказ 205",
      (A["quick"], A["list"], A["reserve"], A["target"], A["limit"], A["desired"], A["walk"]) == (205, 220, 15, 25, 165, 150, 205), A)
check("2: вариант 1 без ремонта (ремонт не вычитается из цены аналогов с таким же дефектом)", A["rep_hi"] == 0 and A["rep_unknown"] == [], A)
check("2: вариант 2 по исправным аналогам (370/400), цена ремонта не известна -> расчёт предварительный",
      (B["quick"], B["list"], B["final"], B["rep_unknown"]) == (370, 400, False, ["проблемы с экраном"]) and B["limit"] == 305, B)
check("2: безубыточность ремонта 120 BYN и «что если» 60/120/180 -> 235/165/95",
      pl["breakeven"] == 120 and pl["sens"] == [(60, 235), (120, 165), (180, 95)], (pl["breakeven"], pl["sens"]))
check("2: вывод — не покупать (240 выше цены отказа 205) + порог ремонта для варианта 2",
      ap["decision"][0] == "skip" and "выше цены отказа 205 BYN" in ap["decision"][1] and "обойдётся не дороже ≈ 55 BYN" in ap["decision"][1], ap["decision"])
check("2: сообщение: ремонт не придуман, «до вычета ремонта», чувствительность подписана",
      "бот её не придумывает" in msg and "(до вычета ремонта)" in msg and "Что если (не цены ремонта, а чувствительность)" in msg
      and "Ремонт выгоднее варианта 1, только если запчасти + работа не дороже ≈ 120 BYN" in msg, msg)

# --- пример 2b: то же с заданной ценой ремонта ---
t, d_, p_, rc, a, f, ap, msg = RUNS["2b"]
pl = ap["plan"]
A, B = pl["A"], pl["B"]
check("2b: вариант 2 финальный, ремонт 70–100, запас 15%: расходы = 100 + 15 + резерв 20 = 135 (ремонт один раз)",
      B["final"] and (B["rep_lo"], B["rep_hi"], B["overrun"], B["reserve"], B["costs"]) == (70, 100, 15, 20, 135), B)
check("2b: максимум 190 = 370 − 135 − 45; желательно 165; отказ 310 (оптимистично: ремонт 70)", (B["raw"], B["limit"], B["desired"], B["walk"]) == (190, 190, 165, 310), B)
check("2b: вариант 2 лучше варианта 1 (выигрыш 45 ≥ половины цели) — выбран B", pl["best"] == "B" and ap["calc"] is B, (pl["best"], A["profit"], B["profit"]))
check("2b: вывод — не покупать (240 > 190 на 21%), оба максимума названы",
      ap["decision"][0] == "skip" and "выше максимума 190 BYN на 50 BYN (21% цены)" in ap["decision"][1]
      and "Максимум покупки: вариант 1 — 165 BYN, вариант 2 — 190 BYN" in ap["decision"][1], ap["decision"])
check("2b: формула в сообщении без дублирования ремонта", "370 (быстрая продажа) − 115 (ремонт 100 + запас 15%) − 20 (резерв 5% на непроверенные функции) − 45 (целевая прибыль) = 190" in msg
      and msg.count("(ремонт 100") == 1, msg)
check("2b: примеры аналогов — из исправных, а не с экраном", "Примеры аналогов без названных дефектов" in msg and "дефект в заголовке: экран" not in msg, msg)

# --- пример 3: износ аккумулятора ---
t, d_, p_, rc, a, f, ap, msg = RUNS["3"]
pl = ap["plan"]
A = pl["A"]
check("3: категория «небольшие дефекты»; цена «как есть» — по 5 аналогам этой категории (дефекты могут отличаться)",
      k.ad_cat(f) == "minor" and pl["asis"]["src"] == "cat" and pl["asis"]["n"] == 5, pl["asis"])
check("3: быстро 295 / выставлять 300, резерв 15, цель 40 -> максимум 240, желательно 220, отказ 285",
      (A["quick"], A["list"], A["reserve"], A["target"], A["limit"], A["desired"], A["walk"]) == (295, 300, 15, 40, 240, 220, 285), A)
check("3: вывод — торг до 240 (250 выше на 10); уверенность средняя", ap["decision"][0] == "bargain" and ap["decision"][1].startswith("Покупать только после торга до 240 BYN")
      and ap["conf"] == "средняя", (ap["decision"], ap["conf"]))
check("3: примеры аналогов названы по категории «небольшие дефекты», а не «без названных дефектов»",
      "Примеры аналогов категории «небольшие дефекты»" in msg and "Примеры аналогов без названных дефектов" not in msg, msg[-700:])
check("3: предупреждение про общий рынок относится к варианту 2", "цена продажи после ремонта (вариант 2) основана на общем рынке" in msg, msg)
check("3: рейтинг цены не выдан за решение («для перепродажи решают расчёты ниже»)", "для перепродажи решают расчёты ниже" in msg)

# --- пример 3b: ремонт 40–60 -> вариант 2 не лучше ---
t, d_, p_, rc, a, f, ap, msg = RUNS["3b"]
pl = ap["plan"]
check("3b: вариант 2: ремонт 60 + запас 9 + резерв 20 + цель 45 -> максимум 235 (ремонт вычтен один раз)",
      pl["B"]["final"] and (pl["B"]["costs"], pl["B"]["raw"], pl["B"]["limit"]) == (89, 236, 235), pl["B"])
check("3b: выигрыш варианта 2 меньше порога -> лучший вариант 1; решение — торг до 240",
      pl["best"] == "A" and ap["decision"][0] == "bargain" and "Максимум покупки: вариант 1 — 240 BYN, вариант 2 — 235 BYN" in ap["decision"][1], (pl["best"], ap["decision"]))

# --- пример 3c: дешёвая замена -> вариант 2 заметно лучше ---
t, d_, p_, rc, a, f, ap, msg = RUNS["3c"]
pl = ap["plan"]
check("3c: ремонт 10 BYN -> вариант 2 заметно выгоднее и выбирается; максимум 290",
      pl["best"] == "B" and pl["B"]["limit"] == 290 and pl["B"]["profit"] - pl["A"]["profit"] >= max(pl["A"]["target"] / 2, 10), (pl["best"], pl["B"], pl["A"]["profit"]))
check("3c: цена не выше желаемой (270) -> покупать, но уверенность низкая (аналоги не подтверждены) — об этом сказано",
      ap["decision"][0] == "buy" and "вариант 2" in ap["decision"][1] and "Уверенность оценки низкая" in msg, (ap["decision"], ap["conf"]))

# --- пример 4: неизвестное состояние ---
t, d_, p_, rc, a, f, ap, msg = RUNS["4"]
pl = ap["plan"]
A = pl["A"]
check("4: категория «состояние не подтверждено» (не «исправен»); цена «как есть» — по 21 аналогу без названных дефектов",
      k.ad_cat(f) == "unk" and pl["asis"]["src"] == "clean" and pl["asis"]["n"] == 21, pl["asis"])
check("4: быстро 370 / выставлять 400, резерв 20, цель 45 -> максимум 305, желательно 280, отказ 380",
      (A["quick"], A["list"], A["reserve"], A["target"], A["limit"], A["desired"], A["walk"]) == (370, 400, 20, 45, 305, 280, 380), A)
check("4: перечень непроверенного, включая износ аккумулятора",
      "износ аккумулятора" in pl["unconfirmed"] and "Не проверено:" in msg and "Возможны скрытые дефекты" in msg, pl["unconfirmed"])
check("4: торг до 305 и «только после проверки» блокировки и Face ID",
      ap["decision"][1].startswith("Покупать только после торга до 305 BYN") and "Покупать только после проверки при осмотре" in msg, ap["decision"])
check("4: «дефектов в описании нет» не названо исправностью", "это не значит, что телефон исправен" in msg)

# --- пример 5: хорошая комплектация ---
t5, d5, p5, rc5, a5, f5, ap5, msg5 = RUNS["5"]
t4, d4, p4, rc4, a4, f4, ap4, msg4 = RUNS["4"]
check("5: комплект назван по тексту, оригинальность не подтверждена",
      "по тексту — коробка, зарядка/кабель, наушники, документы/чек. Оригинальность аксессуаров не подтверждена" in msg5, msg5)
check("5: цена за комплект НЕ добавлена в расчёт: числа варианта 1 те же, что без комплекта (кроме цены продавца)",
      all(ap5["plan"]["A"][x] == ap4["plan"]["A"][x] for x in ("quick", "list", "target", "reserve", "limit", "desired", "walk")), (ap5["plan"]["A"], ap4["plan"]["A"]))
check("5: влияние коробки — из аналогов: разница медиан +15 BYN, 11 с коробкой / 10 без", k.kit_effect(ap5) == (15, 11, 10), k.kit_effect(ap5))
check("5: вывод — торг до 305 (комплект не повышает максимум)", ap5["decision"][1].startswith("Покупать только после торга до 305 BYN"), ap5["decision"])
# аналогов с коробкой мало — влияния нет, и бот так и пишет (ничего не придумывает)
xs_market()
its = k.STATE["market"]["iPhone XS"]["items"]
for it in its:
    it[3] &= ~k.F_BOX
its[10][3] |= k.F_BOX  # одна коробка среди аналогов без названных дефектов
fk = k.rule_facts(ad("iPhone XS 64gb", 34000, "коробка, чек", ad_id=9300))
apk = k.appraise(ad("iPhone XS 64gb", 34000, "коробка, чек", ad_id=9300), fk)
mk = k.build_message(ad("iPhone XS 64gb", 34000, "коробка, чек", ad_id=9300), fk, apk)
check("5: аналогов с коробкой мало -> «влияние не оценить», цифры не выдуманы",
      k.kit_effect(apk)[0] is None and "Влияние коробки на цену не оценить: аналогов с коробкой 1, без неё 20 (нужно ≥ 3 в каждой группе)" in mk, mk)
xs_market()

# =====================================================================================================================
# 3. Цены ремонта: три формы записи REPAIR_COSTS и честное «не задано»
# =====================================================================================================================
defaults()
k.REPAIR_COSTS.update({"screen": 80, "battery": [30, 50], "camera": {"parts": [40, 60], "labor": 30}, "charging": {"parts": 25, "labor": [10, 20]},
                       "comms": "дорого", "biometric": [100], "board": -5})
check("ремонт: число", k.repair_range("screen") == (80, 80, "REPAIR_COSTS"), k.repair_range("screen"))
check("ремонт: диапазон", k.repair_range("battery") == (30, 50, "REPAIR_COSTS"), k.repair_range("battery"))
check("ремонт: запчасти + работа", k.repair_range("camera") == (70, 90, "REPAIR_COSTS: запчасти + работа") and
      k.repair_range("charging") == (35, 45, "REPAIR_COSTS: запчасти + работа"), (k.repair_range("camera"), k.repair_range("charging")))
check("ремонт: мусор и отрицательные числа не принимаются (цена не выдумывается)",
      k.repair_range("comms") is None and k.repair_range("biometric") is None and k.repair_range("board") is None and k.repair_range("water") is None)
fr = k.rule_facts(ad("iPhone XS 64gb", desc="разбит экран, акб слабый, камера не работает"))
rp = k.repair_plan(fr)
check("ремонт: несколько дефектов — суммы по диапазонам", rp["unknown"] == [] and (rp["lo"], rp["hi"]) == (80 + 30 + 70, 80 + 50 + 90), rp)
fr = k.rule_facts(ad("iPhone XS 64gb", desc="разбит экран, динамик хрипит"))
rp = k.repair_plan(fr)
check("ремонт: у одного дефекта цена известна, у другого нет — неизвестный назван отдельно",
      [i["code"] for i in rp["items"]] == ["screen"] and rp["unknown"] == ["проблемы со связью/звуком"] and k.known_repair_cost(fr) is None, rp)
fr = k.rule_facts(ad("iPhone XS 64gb", desc="разбит экран"))
fr["repair_cost"] = 55.0  # продавец сам назвал цену ремонта
k.REPAIR_COSTS.clear()
rp = k.repair_plan(fr)
check("ремонт: цена из слов продавца помечена как таковая и берётся только для одного дефекта",
      rp["items"] and rp["items"][0]["src"] == "по словам продавца" and rp["hi"] == 55, rp)
defaults()

# =====================================================================================================================
# 4. Формулы сделки: ремонт вычитается один раз; максимум = продажа − все расходы кроме покупки − целевая прибыль
# =====================================================================================================================
k.EXTRA_COSTS_BYN, k.TARGET_PROFIT_BYN, k.RISK_RESERVE_PCT, k.REPAIR_OVERRUN_PCT = 10, 40, 5, 15
c = k.deal_calc(400, 450, 300, (50, 80), (), True)
check("deal_calc: расходы = прочие 10 + ремонт 80 + запас 12 + резерв 20 = 122", (c["costs"], c["overrun"], c["reserve"]) == (122, 12, 20), c)
check("deal_calc: максимум = 400 − 122 − 40 = 238 -> 235; желательно = 400 − 122 − 60 -> 215; отказ = 450 − (10 + 50 + 20) = 370",
      (c["raw"], c["limit"], c["desired"], c["walk"]) == (238, 235, 215, 370), c)
check("deal_calc: прибыль при 300 BYN = 400 − 300 − 122 = −22; по выставлению = 450 − 300 − 80 = +70; запас до максимума −65",
      (c["profit"], c["profit_opt"], c["gap"]) == (-22, 70, -65) and abs(c["roi"] - (-22 / 422)) < 1e-9, c)
c = k.deal_calc(400, 450, 300, None, (), False)
check("deal_calc: без ремонта и без резерва: максимум = 400 − 10 − 40 = 350", (c["costs"], c["limit"], c["reserve"]) == (10, 350, 0) and c["final"], c)
c = k.deal_calc(400, 450, 300, None, ("экран",), True)
check("deal_calc: ремонт не известен -> final=False, лимит «до вычета ремонта» = 400 − 10 − 20 − 40 = 330", not c["final"] and c["limit"] == 330 and c["rep_unknown"] == ["экран"], c)
c = k.deal_calc(400, 450, 0, (50, 80), (), True)
check("deal_calc: без цены прибыль не считается, уровни считаются", "profit" not in c and c["limit"] > 0, c)
k.TARGET_PROFIT_BYN = 0
check("целевая прибыль по умолчанию: max(15, 12% от быстрой), кратно 5", k.target_profit(100) == 15 and k.target_profit(400) == 50 and k.target_profit(1000) == 120, (k.target_profit(100), k.target_profit(400)))
k.TARGET_PROFIT_BYN = 33
check("целевая прибыль: TARGET_PROFIT_BYN применяется как есть", k.target_profit(400) == 33 and k.deal_calc(400, 450, 0)["target"] == 33)
defaults()
check("округление: floor5/ceil5", (k.floor5(238), k.floor5(4), k.floor5(-3), k.ceil5(18.5), k.ceil5(20)) == (235, 0, 0, 20, 20))

# =====================================================================================================================
# 5. Нет данных по состоянию: расчёт между категориями — допущение; иначе честное «не из чего» (но не отказ от расчётов)
# =====================================================================================================================
def interp_market():
    its = [[2000 + i, 400 + i * 5, 64, 0, 1, 0] for i in range(20)]                       # 20 без пометок: 400–495
    its += [[2100 + i, 280 + i * 10, 64, K["battery"] | k.F_DEF, 1, 0] for i in range(4)]  # 4 «небольшие»: 280–310
    its += [[2200 + i, 100 + i * 10, 64, K["biometric"] | k.F_DEF, 1, 0] for i in range(4)]  # 4 неисправных: 100–130
    put_market("iPhone XS", its)                                                           # «заметных» нет совсем


interp_market()
ai = ad("iPhone XS 64gb", 20000, "Разбит экран, остальное работает.", ad_id=9400)
fi = k.rule_facts(ai)
api = k.appraise(ai, fi)
asis = api["plan"]["asis"]
q_minor = k.price_stats([280, 290, 300, 310])["q1"]
q_fault = k.price_stats([100, 110, 120, 130])["q1"]
check("между категориями: источник «расчёт», не «найдено»; 0 объявлений в основе",
      asis["src"] == "interp" and asis["found"] is False and asis["n"] == 0 and asis["st"] is None, asis)
check("между категориями: цена — середина между «небольшими» и «неисправными» (глубина 2 из 1…3)",
      asis["quick"] == k.rnd5((q_minor + q_fault) / 2) and asis["between"] == (1, 3), (asis, q_minor, q_fault))
mi = k.build_message(ai, fi, api)
check("между категориями: в сообщении подписано «расчёт (допущение)», строка категории — «объявлений нет»",
      "расчёт (допущение): между категориями «небольшие дефекты» и «неисправные»" in mi and "заметные дефекты: объявлений нет ◀ этот телефон" in mi, mi)
check("между категориями: сравнение с «такими же» не делается (нет вердикта по рынку)", api["verdict"] is None and not api["like_for_like"] and "По рынку:" not in mi, api["verdict"])
check("между категориями: уверенность низкая, причина названа", api["conf"] == "низкая" and any("допущение" in w for w in api["conf_why"]), (api["conf"], api["conf_why"]))
A = api["plan"]["A"]
for price, want in ((A["desired"], "buy"), (A["limit"], "bargain")):  # желаемая цена — можно; между желаемой и максимумом при слабой оценке — только с запасом
    ap2 = k.appraise(ad("iPhone XS 64gb", price * 100, "Разбит экран, остальное работает.", ad_id=9401), fi | {"price": float(price)})
    check(f"между категориями: цена {price} -> {want} (слабая оценка требует запаса)", ap2["decision"][0] == want, ap2["decision"])
    if want == "bargain":
        check("между категориями: торг до желаемой цены, оценка названа ненадёжной", f"Покупать только после торга до {A['desired']} BYN" in ap2["decision"][1] and "ненадёжна" in ap2["decision"][1], ap2["decision"])

# только исправные аналоги: телефон с экраном оценить «как есть» не из чего, но расчёты не отменяются
put_market("iPhone XS", [[2000 + i, 400 + i * 5, 64, 0, 1, 0] for i in range(20)])
an = ad("iPhone XS 64gb", 20000, "Разбит экран.", ad_id=9402)
fn = k.rule_facts(an)
apn = k.appraise(an, fn)
mn = k.build_message(an, fn, apn)
check("нет аналогов категории: вариант 1 честно «не из чего», вариант 2 посчитан до вычета ремонта",
      apn["plan"]["A"] is None and apn["plan"]["B"] and not apn["plan"]["B"]["final"] and "Оценить продажу «как есть» не из чего" in mn
      and "найдено 0, нужно ≥ 3" in mn and "(до вычета ремонта)" in mn, mn)
check("нет аналогов категории: вывод — одна из фраз и с конкретикой", apn["decision"][1].startswith(("Покупать только после торга", "Не покупать", "Пока недостаточно")), apn["decision"])
aw = ad("iPhone XS 64gb", 20000, "Телефон после воды.", ad_id=9403)
fw = k.rule_facts(aw)
apw = k.appraise(aw, fw)
mw = k.build_message(aw, fw, apw)
check("критичный дефект (вода): не покупать, вариант 2 не рассматривается, расходы на ремонт не выдуманы",
      apw["decision"][0] == "skip" and "Не рассматриваю" in mw and apw["plan"]["B"] is None and "ремонт 0" not in mw, apw["decision"])

# =====================================================================================================================
# 6. «Прибыль > 0» ещё не повод покупать: мало аналогов, подозрительно низкая цена, нет цены
# =====================================================================================================================
put_market("iPhone XS", [[2000 + i, 400 + i * 10, 64, 0, 1, 0] for i in range(4)])  # 4 аналога: ориентир есть, но < 5
at = ad("iPhone XS 64gb", 25000, "Продаю.", ad_id=9500)
ft = k.rule_facts(at)
apt = k.appraise(at, ft)
mt = k.build_message(at, ft, apt)
check("мало аналогов (4 < 5): прибыль положительная, но вывод — «пока недостаточно данных», уровни цены всё равно посчитаны",
      apt["thin"] and apt["plan"]["A"]["profit"] > 0 and apt["decision"][0] == "unknown" and "аналогов мало (4, нужно ≥ 5)" in apt["decision"][1]
      and "Цена покупки: желательно ≤" in mt, (apt["decision"], apt["plan"]["A"]))
xs_market()
asu = ad("iPhone XS 64gb", 15000, "Продаю.", ad_id=9501)
fsu = k.rule_facts(asu)
apsu = k.appraise(asu, fsu)
check("цена вдвое ниже рынка: не «покупать», а проверить блокировку и обман", apsu["decision"][0] == "unknown" and "вдвое ниже рынка" in apsu["decision"][1], apsu["decision"])
check("цена вдвое ниже рынка: объявление не попадает в статистику недельного отчёта", k.is_suspicious(fsu, apsu))
anp = ad("iPhone XS 64gb", 0, "Цена договорная.", ad_id=9502)
fnp = k.rule_facts(anp)
apnp = k.appraise(anp, fnp)
mnp = k.build_message(anp, fnp, apnp)
check("нет цены: вывод «недостаточно данных» со ссылкой на отсутствие цены; максимум покупки всё равно назван",
      apnp["decision"][0] == "unknown" and "нет цены" in apnp["decision"][1] and "Цена покупки: желательно ≤" in mnp and "Прибыль при цене" not in mnp, apnp["decision"])
defaults()

# =====================================================================================================================
# 7. Фото: в нейросеть уходят сами картинки (base64), а не ссылки; честные статусы; только видимое
# =====================================================================================================================
class FakeResp:
    def __init__(self, status=200, ctype="image/jpeg", content=b"", headers=None):
        self.status_code, self.content = status, content
        self.headers = headers or {"Content-Type": ctype}


served = []
JPEG = {}
real_get = k.http_get


def fake_get(url, params=None, timeout=20, tries=3):
    served.append(url)
    if "bad" in url:
        return FakeResp(404)
    if "html" in url or ("flaky" in url and "/gallery/" in url):  # «flaky»: первый адрес отдаёт не картинку, второй — картинку
        return FakeResp(200, "text/html", b"<html>")
    if "huge" in url:
        return FakeResp(200, "image/jpeg", b"x" * (k.MAX_IMG_BYTES + 1))
    data = JPEG.setdefault(url, b"\xff\xd8" + url.encode() + b"\xff\xd9")
    return FakeResp(200, "image/png" if ".png" in url else "image/jpeg", data)


k.http_get = fake_get
imgs = [{"path": "adim1/a.jpg", "yams_storage": False}, {"path": "/adim1/b.png", "media_storage": "yams"}, {"nopath": 1}, "adim1/c.jpg", 5,
        {"path": "adim1/d.jpg"}, {"path": "adim1/e.jpg"}]
check("фото: пути берутся из images (словари и строки), мусор пропускается, «/» в начале убирается",
      [p for p, _y in k.image_refs({"images": imgs})] == ["adim1/a.jpg", "adim1/b.png", "adim1/c.jpg", "adim1/d.jpg", "adim1/e.jpg"], k.image_refs({"images": imgs}))
check("фото: yams-картинка запрашивается с yams-адреса, обычная — с rms",
      k.image_urls("adim1/b.png", True)[0].startswith("https://yams.kufar.by/") and k.image_urls("adim1/a.jpg", False)[0].startswith("https://rms.kufar.by/"))
k.RUN.update(deadline=0.0, img_fails=0)
k.PHOTOS_MAX = 3
served.clear()
got, why = k.fetch_photos({"images": imgs})
check("фото: качается не больше PHOTOS_MAX (3), типы определены по Content-Type", len(got) == 3 and why == "" and [m for m, _b in got] == ["image/jpeg", "image/png", "image/jpeg"]
      and len(served) == 3, (len(got), why, served))
k.PHOTOS_MAX = 0
check("фото: PHOTOS_MAX=0 — не анализируем", k.fetch_photos({"images": imgs}) == ([], "off"))
k.PHOTOS_MAX = 4
check("фото: объявление без картинок", k.fetch_photos({"images": []}) == ([], "no_photos") and k.fetch_photos({}) == ([], "no_photos"))
served.clear()
bad_ad = {"images": [{"path": "adim1/bad1.jpg"}]}
for _ in range(3):
    got, why = k.fetch_photos(bad_ad)
check("фото: не скачались -> no_download; после 3 неудач подряд остаток запуска фото не качаем", got == [] and why == "no_download" and k.RUN["img_fails"] == 3, (why, k.RUN["img_fails"]))
n_before = len(served)
check("фото: после 3 неудач новых запросов к CDN нет", k.fetch_photos({"images": imgs}) == ([], "no_download") and len(served) == n_before)
k.RUN["img_fails"] = 0
served.clear()
got, why = k.fetch_photos({"images": [{"path": "adim1/flaky1.jpg"}]})
check("фото: ответ не-картинка (text/html) отбрасывается, пробуется следующий адрес и берётся картинка",
      len(got) == 1 and got[0][0] == "image/jpeg" and why == "" and len(served) == 2 and "/gallery/" in served[0] and "list_thumbs_2x" in served[1], (served, why))
got, why = k.fetch_photos({"images": [{"path": "adim1/html1.jpg"}]})
check("фото: если ни один адрес не отдал картинку — no_download", got == [] and why == "no_download", (got, why))
k.RUN["img_fails"] = 0
got, why = k.fetch_photos({"images": [{"path": "adim1/huge1.jpg"}]})
check("фото: слишком большой файл не берём", got == [] and why == "no_download", (len(got), why))
k.RUN["img_fails"] = 0

# --- запрос к Gemini: картинки в base64 внутри inline_data ---
posts = []
REPLY = {"is_phone": True, "memory_gb": 64, "condition": "б/у", "defects": [], "summary": "Продают iPhone XS.", "risks": [], "kit": [],
         "photos": {"findings": [
             {"part": "экран", "kind": "screen", "what": "трещина в углу экрана", "confidence": "высокая", "check": "тач по всей площади"},
             {"part": "камера", "kind": "camera", "what": "возможное пятно на линзе", "confidence": "средняя", "check": "снимок при ярком свете"},
             {"part": "другое", "kind": "battery", "what": "аккумулятор изношен", "confidence": "высокая", "check": ""},
             {"part": "корпус", "kind": "cosmetic", "what": "", "confidence": "высокая", "check": ""}],
             "kit_visible": ["коробка", "золотой кейс", "наушники"], "mismatch": "в тексте «идеал», а на экране трещина", "quality": "хорошее"}}


class FakeAPI:
    def __init__(self, payload, status=200):
        self.payload, self.status_code, self.headers = payload, status, {}

    def raise_for_status(self):
        if self.status_code >= 400:
            e = k.requests.HTTPError(str(self.status_code))
            e.response = self
            raise e

    def json(self):
        return self.payload


def reset_llm():
    """Новый «запуск»: нейросеть включена, кеш разборов пуст (иначе то же объявление второй раз не дойдёт до поддельной сети)."""
    k._LLM.update(fails=0, off=False, n429=0, last=None, why="")
    k.AI_CACHE.clear()


def make_post(reply, fail_with_images=False):
    def fake_post(url, headers=None, json=None, timeout=None, **kw):
        posts.append({"url": url, "headers": headers or {}, "json": json, "timeout": timeout})
        parts = (json or {}).get("contents", [{}])[0].get("parts", [])
        if fail_with_images and any("inline_data" in p for p in parts):
            return FakeAPI({"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "картинка не принята"}}, 400)
        text = reply if isinstance(reply, str) else globals()["json"].dumps(reply, ensure_ascii=False)
        if "generativelanguage" in url:
            return FakeAPI({"candidates": [{"content": {"parts": [{"text": text}]}}]})
        return FakeAPI({"content": [{"text": text}]})
    return fake_post


real_post = k.requests.post
k.GEMINI_KEY, k.ANTHROPIC_KEY = "fake-key", ""
reset_llm()
k.requests.post = make_post(REPLY)
k.RUN.update(deadline=0.0, img_fails=0)
served.clear()
JPEG.clear()
phone_ad = ad("iPhone XS 64gb", 30000, "Идеальное состояние, всё работает. Продаю.", ad_id=9600,
              images=[{"path": f"adim1/p{i}.jpg"} for i in range(5)])
k.PHOTOS_MAX = 4
fp = k.analyze_ad(phone_ad)
req = posts[0]
parts = req["json"]["contents"][0]["parts"]
imgs_sent = [p["inline_data"] for p in parts if "inline_data" in p]
want_b64 = [base64.b64encode(JPEG[u]).decode() for u in served]
check("Gemini: в запросе 4 картинки (PHOTOS_MAX), текст — первым", len(imgs_sent) == 4 and "text" in parts[0] and len(parts) == 5, (len(imgs_sent), len(parts)))
check("Gemini: картинки — настоящие байты в base64 (inline_data), в том же порядке, mime_type верный",
      [i["data"] for i in imgs_sent] == want_b64 and all(i["mime_type"] == "image/jpeg" for i in imgs_sent), (want_b64[:1], [i["data"] for i in imgs_sent][:1]))
check("Gemini: ссылки на картинки в запрос не передаются", "rms.kufar.by" not in parts[0]["text"] and "yams.kufar.by" not in parts[0]["text"])
check("Gemini: в запросе правила «только видимое» и запрет судить о функциях по фото",
      "описывай ТОЛЬКО то, что действительно видно" in parts[0]["text"] and "НЕЛЬЗЯ определить исправность функций" in parts[0]["text"], parts[0]["text"][-900:])
check("Gemini: ключ в заголовке, увеличенный таймаут для запроса с фото, один запрос", req["headers"].get("x-goog-api-key") == "fake-key" and req["timeout"] == 60 and len(posts) == 1, (req["headers"], req["timeout"], len(posts)))
ph = fp["photo"]
check("фото: статус analyzed, просмотрено 4 из 5", ph["status"] == "analyzed" and ph["n"] == 4 and ph["total"] == 5, ph)
check("фото: находки разобраны, пустая и без текста отброшена, неизвестный вид -> other", [f["kind"] for f in ph["findings"]] == ["screen", "camera", "other"], ph["findings"])
check("фото: в дефекты попал только экран (уверенность «высокая», вид screen/cosmetic/camera); «средняя» и чужой вид — нет",
      fp["defects"].get("screen") == "по фото: трещина в углу экрана" and "camera" not in fp["defects"] and "battery" not in fp["defects"], fp["defects"])
check("фото: комплектация — только из списка допустимых (выдуманный «золотой кейс» убран)", ph["kit"] == ["коробка", "наушники"], ph["kit"])
check("фото: расхождение с описанием сохранено", "на экране трещина" in ph["mismatch"], ph["mismatch"])
check("фото: после «трещина на фото» категория стала «заметные дефекты» (слова продавца — «идеал»)", k.ad_cat(fp) == "visible", (k.ad_cat(fp), fp["defects"]))
xs_market()
apf = k.appraise(phone_ad, fp)
mf = k.build_message(phone_ad, fp, apf)
check("фото в сообщении: что видно, уверенность, что проверить, расхождение с текстом",
      "По фото (4 из 5) видно:" in mf and "трещина в углу экрана (уверенность: высокая)" in mf and "Проверить: тач по всей площади" in mf
      and "⚠ Расхождение с описанием: в тексте «идеал», а на экране трещина" in mf, mf)
check("фото в сообщении: влияние на цену — по аналогам с таким же дефектом (экран), а не выдумано",
      "Аналоги с таким дефектом дешевле исправных на ≈" in mf and "(по 6)" in mf, mf)
check("фото в сообщении: комплект «на фото видно» отдельно от текста, оригинальность не подтверждена",
      "на фото видно — коробка, наушники" in mf and "Оригинальность аксессуаров не подтверждена" in mf, mf)
check("фото в сообщении: по фото функции не объявляются исправными/неисправными",
      all(x not in mf.lower() for x in ("face id работает по фото", "по фото работает", "по фото исправ")), mf)

# плохое качество: дефекты по фото в расчёт не берём, но показываем
posts.clear()
reset_llm()
bad_q = json.loads(json.dumps(REPLY))
bad_q["photos"]["quality"] = "плохое"
k.requests.post = make_post(bad_q)
k.RUN.update(img_fails=0)
fq = k.analyze_ad(phone_ad)
mq = k.build_message(phone_ad, fq, k.appraise(phone_ad, fq))
check("плохое качество фото: дефекты по фото в расчёт не идут, в сообщении предупреждение",
      "screen" not in fq["defects"] and k.ad_cat(fq) == "ok" and "качество фото плохое" in mq, (fq["defects"], mq[:200]))
# нет видимых дефектов
posts.clear()
reset_llm()
clean_r = json.loads(json.dumps(REPLY))
clean_r["photos"] = {"findings": [], "kit_visible": [], "mismatch": "", "quality": "хорошее"}
k.requests.post = make_post(clean_r)
k.RUN.update(img_fails=0)
fc = k.analyze_ad(phone_ad)
mc = k.build_message(phone_ad, fc, k.appraise(phone_ad, fc))
check("на фото дефектов нет: сказано «это не проверка работы телефона»", "видимых дефектов не найдено; это не проверка работы телефона" in mc, mc)
# нейросеть не приняла запрос с фото -> статус error, текст всё равно разобран вторым запросом без картинок
posts.clear()
reset_llm()
k.requests.post = make_post(REPLY | {"summary": "Только текст."}, fail_with_images=True)
k.RUN.update(img_fails=0)
fe = k.analyze_ad(phone_ad)
me = k.build_message(phone_ad, fe, k.appraise(phone_ad, fe))
second = posts[-1]["json"]["contents"][0]["parts"]
check("запрос с фото не прошёл: статус error, второй запрос — только текст, объявление не потеряно",
      fe["photo"]["status"] == "error" and len(posts) == 2 and all("inline_data" not in p for p in second) and fe["llm"] and "нейросеть не приняла запрос с фото" in me,
      (fe["photo"]["status"], len(posts), fe["llm"]))
# нет ключа / нет фото / не скачались
k.GEMINI_KEY = ""
reset_llm()
fnk = k.analyze_ad(phone_ad)
check("нет ключа нейросети: «не анализировались», сообщение собирается", fnk["photo"]["status"] == "no_llm" and "не подключена нейросеть" in k.build_message(phone_ad, fnk, k.appraise(phone_ad, fnk)))
k.GEMINI_KEY = "fake-key"
k.requests.post = make_post(REPLY)
reset_llm()
fnp2 = k.analyze_ad(ad("iPhone XS 64gb", 30000, "Продаю.", ad_id=9601))
check("в объявлении нет фото: статус no_photos, разбор текста идёт (один запрос без картинок)", fnp2["photo"]["status"] == "no_photos" and fnp2["llm"], fnp2["photo"])
reset_llm()
k.RUN.update(img_fails=0)
posts.clear()
fnd = k.analyze_ad(ad("iPhone XS 64gb", 30000, "Продаю.", ad_id=9602, images=[{"path": "adim1/bad9.jpg"}]))
check("картинки не скачались: статус no_download, разбор текста всё равно идёт без картинок",
      fnd["photo"]["status"] == "no_download" and fnd["llm"] and len(posts) == 1 and all("inline_data" not in p for p in posts[0]["json"]["contents"][0]["parts"]), (fnd["photo"], len(posts)))
# --- Claude (запасной путь): картинки как base64-блоки ---
k.GEMINI_KEY, k.ANTHROPIC_KEY = "", "ak"
reset_llm()
k.RUN.update(img_fails=0)
posts.clear()
JPEG.clear()
served.clear()
fa = k.analyze_ad(ad("iPhone XS 64gb", 30000, "Продаю.", ad_id=9603, images=[{"path": "adim1/q1.jpg"}, {"path": "adim1/q2.jpg"}]))
content = posts[0]["json"]["messages"][0]["content"]
blocks = [b for b in content if b["type"] == "image"]
check("Claude: картинки — блоки image/base64 с настоящими байтами, текст последним",
      len(blocks) == 2 and content[-1]["type"] == "text" and [b["source"]["data"] for b in blocks] == [base64.b64encode(JPEG[u]).decode() for u in served]
      and blocks[0]["source"]["type"] == "base64" and blocks[0]["source"]["media_type"] == "image/jpeg" and fa["photo"]["status"] == "analyzed", (len(blocks), fa["photo"]))
k.requests.post = real_post
k.http_get = real_get
k.GEMINI_KEY, k.ANTHROPIC_KEY = "", ""

# --- повторная отправка не теряет фото ---
k.STATE["pending"].clear()
k.PHOTOS_MAX = 2
k.stash(9700, phone_ad)
saved = k.STATE["pending"]["9700"]["ad"]
check("повтор отправки: в очереди сохранены картинки (не больше PHOTOS_MAX), цена и ссылки на месте",
      [im["path"] for im in saved["images"]] == ["adim1/p0.jpg", "adim1/p1.jpg"] and saved["price_byn"] == "30000", saved.get("images"))
k.STATE["pending"].clear()
k.PHOTOS_MAX = 4

# =====================================================================================================================
# 8. Настройки из окружения: значения по умолчанию, пустые переменные (так передаёт GitHub Actions) и мусор
# =====================================================================================================================
def child(env):
    full = {x: v for x, v in os.environ.items() if x not in ("TARGET_PROFIT_BYN", "RISK_RESERVE_PCT", "REPAIR_OVERRUN_PCT", "PHOTOS_MAX", "REPAIR_COSTS")}
    full.update(TG_TOKEN="t", TG_CHAT_ID="1", **env)
    code = ("import sys; sys.argv=['kufar_bot.py']; sys.path.insert(0, %r); import kufar_bot as k; "
            "print(k.TARGET_PROFIT_BYN, k.RISK_RESERVE_PCT, k.REPAIR_OVERRUN_PCT, k.PHOTOS_MAX, json.dumps(k.REPAIR_COSTS))") % str(tmp)
    p = subprocess.run([sys.executable, "-I", "-c", "import json; " + code], env=full, capture_output=True, text=True)
    return (p.stdout.strip().splitlines() or [p.stderr[-300:]])[-1]


check("настройки по умолчанию: цель по формуле, резерв 5%, запас 15%, 4 фото, цен ремонта нет", child({}) == "0.0 5.0 15.0 4 {}", child({}))
check("настройки: пустые переменные из Actions (vars.X не создана) = значения по умолчанию",
      child({"TARGET_PROFIT_BYN": "", "RISK_RESERVE_PCT": "", "REPAIR_OVERRUN_PCT": "", "PHOTOS_MAX": "", "REPAIR_COSTS": ""}) == "0.0 5.0 15.0 4 {}",
      child({"TARGET_PROFIT_BYN": "", "RISK_RESERVE_PCT": "", "REPAIR_OVERRUN_PCT": "", "PHOTOS_MAX": "", "REPAIR_COSTS": ""}))
check("настройки: заданные значения читаются, REPAIR_COSTS — JSON",
      child({"TARGET_PROFIT_BYN": "60", "RISK_RESERVE_PCT": "8", "REPAIR_OVERRUN_PCT": "20", "PHOTOS_MAX": "2", "REPAIR_COSTS": '{"screen":[70,100]}'})
      == '60.0 8.0 20.0 2 {"screen": [70, 100]}', child({"TARGET_PROFIT_BYN": "60", "RISK_RESERVE_PCT": "8", "REPAIR_OVERRUN_PCT": "20", "PHOTOS_MAX": "2", "REPAIR_COSTS": '{"screen":[70,100]}'}))
check("настройки: мусор не роняет бота, берётся значение по умолчанию",
      child({"TARGET_PROFIT_BYN": "много", "PHOTOS_MAX": "x", "REPAIR_COSTS": "не json"}) == "0.0 5.0 15.0 4 {}", child({"TARGET_PROFIT_BYN": "много", "PHOTOS_MAX": "x", "REPAIR_COSTS": "не json"}))

# =====================================================================================================================
if EXAMPLES:
    out = []
    for key_, (title, desc, price, repair, a, f, ap, msg) in RUNS.items():
        out += ["=" * 100, title, "=" * 100, "ВХОД:", f"  заголовок: {a['subject']}", f"  цена продавца: {price / 100:.0f} BYN", f"  описание: {desc}",
                f"  REPAIR_COSTS: {json.dumps(repair, ensure_ascii=False) if repair else 'не задано'}", "",
                "РАСЧЁТ:"]
        pl = ap["plan"]
        for nm in ("A", "B"):
            c = pl[nm]
            if not c:
                continue
            out.append(f"  Вариант {'1 (как есть)' if nm == 'A' else '2 (ремонт)'}: продажа быстро {c['quick']:.0f} / выставлять {c['list']:.0f}; цель {c['target']:.0f}; "
                       f"ремонт {c['rep_lo']:.0f}–{c['rep_hi']:.0f} (+запас {c['overrun']:.0f}); резерв {c['reserve']:.0f}; прочее {c['extra']:.0f}")
            out.append(f"    максимум = {c['quick']:.0f} − {c['costs']:.0f} − {c['target']:.0f} = {c['raw']:.0f} → {c['limit']}; желательно {c['desired']}; отказ выше {c['walk']}"
                       + ("" if c["final"] else "  (предварительно: ремонт не известен)"))
            if "profit" in c:
                out.append(f"    при цене {price / 100:.0f}: прибыль {c['profit']:+.0f} (быстро) … {c['profit_opt']:+.0f} (по выставлению), ROI {c['roi'] * 100:+.0f}%")
        out += ["", "РЕКОМЕНДАЦИЯ: " + ap["decision"][1], "", "СООБЩЕНИЕ В TELEGRAM (как придёт; теги <b> убраны):", k._plain(msg), ""]
    Path(EXAMPLES).write_text("\n".join(out), encoding="utf-8")

print("итого ошибок (этап 2):", bad)
sys.exit(1 if bad else 0)
