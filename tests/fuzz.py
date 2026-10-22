import os, random, re, sys, tempfile, time, math
from pathlib import Path
os.environ.update(TG_TOKEN="t", TG_CHAT_ID="1")
for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MODELS", "REPAIR_COSTS", "HOME_REGION"):
    os.environ.pop(key, None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fresh_dir  # noqa: E402
tmp = fresh_dir()
sys.path.insert(0, str(tmp))
import kufar_bot as k

random.seed(int(os.environ.get("FUZZ_SEED", "7")))
LABELS = ["iPhone 11", "iPhone X", "iPhone XS Max", "iPhone 7 Plus", "iPhone 8", "Galaxy S9+", "Galaxy S7 Edge", "iPhone 6s", "iPod touch 5", "iPhone SE (2020)", "iPhone SE"]
DESCS = ["", "разбит экран", "акб 70%", "на запчасти", "не включается", "icloud заблокирован", "идеал, акб 95%, полный комплект", "торг", "без торга",
         "после воды", "face id не работает", "договорная"]
REGS = ["Минск", "Минская область", "Брестская область", "Гомельская область", "", "Витебская", "Могилёвская область", "Гродно"]
bad = 0
def fail(msg, *a):
    global bad
    bad += 1
    if bad <= 15: print("FAIL", msg, *a)

k._MARKET_REFRESHES["n"] = 99
N = int(os.environ.get("FUZZ_N", "1500"))
stat = {}
for i in range(N):
    label = random.choice(LABELS)
    key = k.market_key(label)
    n = random.choice([0, 1, 2, 3, 4, 5, 6, 8, 12, 25, 60])
    base_price = random.choice([50, 120, 300, 600, 1500])
    mode = random.choice(["normal", "equal", "wide", "outliers"])
    items = []
    for j in range(n):
        if mode == "equal": p = base_price
        elif mode == "wide": p = base_price * random.uniform(0.2, 3)
        elif mode == "outliers": p = base_price * random.choice([0.001, 1, 1, 1.1, 0.9, 40])
        else: p = base_price * random.uniform(0.85, 1.2)
        flags = random.choice([0, 0, 0, 0, k.F_DEF, k.F_DEF | k.F_PARTS | k.F_CRIT, k.F_NEW, k.F_REFURB, k.F_SHOP, k.F_DEF | k.F_SHOP,
                               k.F_DEF | k.F_KINDS["screen"], k.F_DEF | k.F_KINDS["battery"], k.F_DEF | k.F_KINDS["battery"] | k.F_KINDS["screen"]])
        gen = random.choice([2016, 2020, 2022]) if key == "iPhone SE" else 0
        items.append([1000 + j, max(1, int(p)), random.choice([0, 16, 32, 64, 64, 128, 256]), flags, random.randint(0, 7), gen])
    k.STATE["market"][key] = {"t": int(time.time() - random.choice([0, 3600, 40 * 3600])), "items": items}
    k.REPAIR_COSTS.clear()
    k.REPAIR_COSTS.update(random.choice([{}, {}, {"screen": 80}, {"battery": 40}, {"screen": 80, "battery": 40, "camera": 60, "charging": 30, "comms": 30, "biometric": 90}]))
    k.EXTRA_COSTS_BYN = random.choice([0, 0, 7, 20])
    price = random.choice([0, 0, 1, 10, int(base_price * random.uniform(0.3, 1.8)), int(base_price)])
    mem = random.choice(["", "64gb", "128 гб", "256", "1tb"])
    desc = " ".join(random.sample(DESCS, random.randint(0, 3)))
    title = f"{label.replace(' (2020)', ' 2020')} {mem} {random.choice(['', 'торг', 'срочно'])}".strip()
    ad = {"ad_id": random.choice([9999, 1000 + random.randint(0, 60)]), "type": "sell", "company_ad": random.random() < 0.2,
          "price_byn": str(price * 100), "price_usd": str(price * 30), "subject": title, "ad_link": "https://www.kufar.by/item/9999",
          "ad_parameters": [{"p": "condition", "vl": random.choice(["Б/у", "Новый", "б/у"])}, {"p": "region", "vl": random.choice(REGS)}]}
    if desc: ad["body_short"] = desc
    try:
        facts = k.rule_facts(ad)
        ap = k.appraise(ad, facts)
        msg = k.build_message(ad, facts, ap)
    except Exception as e:
        fail("исключение", repr(e), title, n, mode); continue
    stat[ap["status"]] = stat.get(ap["status"], 0) + 1
    if ap["status"] == "error": fail("status=error", title, n, mode)
    if len(msg) > 4096: fail("длина", len(msg))
    if re.search(r"nan|inf\b", msg): fail("nan/inf в тексте", msg[:200])
    if "<" in re.sub(r"</?b>", "", msg): fail("сырой <", msg[:200])
    if msg.count("<b>") != msg.count("</b>"): fail("теги")
    FOUR = ("Покупать по текущей цене", "Покупать только после торга", "Не покупать для перепродажи", "Пока недостаточно данных для решения")
    code, text = ap["decision"]
    if not text.startswith(FOUR): fail("вывод не из четырёх фраз", text)
    if msg.count("✅ <b>Вывод для перепродажи:</b>") != 1: fail("вывод не один", msg[-300:])
    if "НЕДОСТАТОЧНО ДАННЫХ" in msg: fail("общая фраза НЕДОСТАТОЧНО ДАННЫХ")
    sev = k.max_severity(facts["defects"])
    if sev >= 3 and code != "skip": fail("критичный дефект без отказа", code, facts["defects"])
    if ap["status"] != "ok" and ap["verdict"] is not None: fail("вердикт без данных", ap["status"], ap["verdict"])
    if ap["status"] != "ok" and code not in ("unknown", "skip"): fail("вывод без данных", ap["status"], code)
    if ap["status"] in ("few", "se_gen", "no_market", "no_model") and any(v in msg for v in ("ОЧЕНЬ ВЫГОДНО", "<b>ВЫГОДНО", "<b>ДОРОГО", "<b>НЕВЫГОДНО", "<b>СРЕДНИЙ")):
        fail("вердикт в сообщении без данных", ap["status"])
    if ap["status"] == "ok":
        st = ap["stats"]
        if st["n"] < (ap["need"] if ap["basis"] == "defect" else k.REF_MIN): fail("слишком мало аналогов для оценки", st["n"], ap["basis"], ap["need"])
        t = ap.get("target")
        if ap["like_for_like"] != (t is not None): fail("target и like_for_like не согласованы", t, ap["like_for_like"])
        if t is not None and t[0] > t[1]: fail("target перевёрнут", t)
        if not (st["min"] <= st["q1"] <= st["med"] <= st["q3"] <= st["max"]): fail("квартили не по порядку", st)
        if any(c[0] == ad["ad_id"] for c in ap["comps"]): fail("объявление среди собственных аналогов")
        if len(ap["comps"]) > 3: fail("слишком много аналогов")
        if ap["found"] < st["n"]: fail("в расчёте больше аналогов, чем найдено", ap["found"], st["n"])
        if ap["basis"] == "general" and ap["like_n"] is not None and ap["conf"] != "низкая": fail("общий рынок при дефекте: уверенность не низкая", ap["conf"])
        if ap["verdict"] is not None and not ap["like_for_like"]: fail("вердикт цены при сравнении не с такими же")
        if facts["price"] and ap["verdict"] is not None:
            pct_msg = ap["pct"]
            if ap["verdict"] in ("ОЧЕНЬ ВЫГОДНО", "ВЫГОДНО") and pct_msg > 0: fail("«выгодно», но дороже медианы", pct_msg, ap["verdict"])
            if ap["verdict"] in ("ДОРОГО", "НЕВЫГОДНО") and pct_msg < 0: fail("«дорого», но дешевле медианы", pct_msg, ap["verdict"])
        c = ap["calc"]
        stat[f"{ap['basis']}/{code}"] = stat.get(f"{ap['basis']}/{code}", 0) + 1
        if c is None: fail("нет расчёта при status=ok")
        else:
            price, rep, ext = facts["price"], c["repair"], c["extra"]
            if c["quick"] > c["list"]: fail("быстрая > выставления", c)
            if abs(c["raw"] - (c["quick"] - ext - rep - c["target_profit"])) > 1e-6: fail("лимит: формула не сходится", c)
            if c["limit"] < 0 or c["limit"] % 5 or c["limit"] > max(0, c["raw"]): fail("лимит: округление/знак", c)
            if c["target_profit"] % 5 or c["target_profit"] < k.MIN_PROFIT_BYN: fail("целевая прибыль", c["target_profit"])
            if c["final"] == bool(c["repair_unknown"]): fail("final и repair_unknown не согласованы", c)
            if ap["basis"] == "defect" and (rep or c["repair_unknown"] or c["repair_parts"]): fail("ремонт вычтен по аналогам с таким же дефектом (двойной учёт)", c)
            if ap["basis"] == "general" and sev < 1 and (rep or c["repair_unknown"]): fail("ремонт у объявления без дефектов", c)
            if price:
                if abs(c["profit_quick"] - (c["quick"] - price - ext - rep)) > 1e-6: fail("прибыль не сходится", c)
                if abs(c["profit_list"] - (c["list"] - price - ext - rep)) > 1e-6: fail("прибыль по выставлению не сходится", c)
                if c["reserve"] != c["limit"] - price: fail("запас не сходится", c)
            else:
                if "profit_quick" in c: fail("прибыль без цены")
                if code != "unknown" and sev < 3: fail("вывод без цены не «недостаточно данных»", code)
            if code == "buy":
                if not (price and price <= c["limit"] and c["final"] and not ap["thin"]): fail("«покупать» при цене выше лимита/неизвестном ремонте/малой выборке", code, c, price)
            if c["repair_unknown"] and code == "buy": fail("«покупать» при неизвестном ремонте")
            if code == "buy" and sev < 2 and price < 0.5 * st["med"]: fail("«покупать» при подозрительно низкой цене", price, st["med"])
            if code == "bargain" and not (price and price > c["limit"] - (0 if c["final"] else 1)): fail("«торг» при цене не выше лимита", c, price)
            if code == "skip" and sev < 3 and price and c["final"] and price <= c["limit"] and c["limit"] > 0: fail("«не покупать» при цене в пределах лимита", c, price)
print("прогонов:", N, "| статусы:", stat, "| ошибок:", bad)
sys.exit(1 if bad else 0)
