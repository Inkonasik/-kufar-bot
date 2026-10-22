"""Тесты разбора объявления по правилам: память, состояние, дефекты, батарея, торг, комплект."""
import os
import sys
import tempfile
from pathlib import Path

os.environ.update(TG_TOKEN="t", TG_CHAT_ID="1")
for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MODELS"):
    os.environ.pop(key, None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fresh_dir  # noqa: E402
tmp = fresh_dir()
sys.path.insert(0, str(tmp))
import kufar_bot as k  # noqa: E402

bad = 0


def check(name, cond, extra=""):
    global bad
    if not cond:
        print("FAIL", name, extra)
        bad += 1


def ad(subject, desc="", price="30000", cond="Б/у", **extra):
    d = {"ad_id": 5, "type": "sell", "company_ad": False, "price_byn": price, "price_usd": "10000",
         "subject": subject, "ad_link": "https://www.kufar.by/item/5",
         "ad_parameters": [{"p": "condition", "vl": cond}, {"p": "region", "vl": "Минск"}, {"p": "area", "vl": "Центральный"}]}
    if desc:
        d["body_short"] = desc
    d.update(extra)
    return d


# память
for text, want in {"iPhone 11 64gb": 64, "iphone 7 128 гб": 128, "Samsung S8 4/64gb": 64, "iPhone XR 256": 256,
                   "iPhone 8 plus 64GB space gray": 64, "iphone 11": 0, "iPhone 7 1tb": 1024, "iPhone 6 16g": 16}.items():
    check(f"память {text!r}", k.parse_memory(text) == want, k.parse_memory(text))

# батарея
check("акб 87%", k.parse_battery("акб 87%") == 87)
check("ёмкость аккумулятора 92 %", k.parse_battery("ёмкость аккумулятора 92 %") == 92)
check("100% акб", k.parse_battery("состояние 100% акб") == 100)
check("не батарея", k.parse_battery("скидка 20%") is None)

# дефекты и их отрицания
D = k.find_defects
check("разбит экран", "screen" in D("экран разбит, не включается") and "board" in D("экран разбит, не включается"))
check("трещина", "screen" in D("есть трещина на стекле"))
check("без трещин — не дефект", "screen" not in D("экран без трещин и царапин"))
check("без царапин — не косметика", "cosmetic" not in D("корпус без царапин"))
check("царапины — косметика", "cosmetic" in D("мелкие царапины на корпусе"))
check("icloud блокировка", "lock" in D("заблокирован на icloud"))
check("icloud чистый — не блок", "lock" not in D("icloud чистый, отвязан"))
check("без icloud — не блок", "lock" not in D("без icloud"))
check("не заблокирован", "lock" not in D("телефон не заблокирован"))
check("face id не работает", "biometric" in D("face id не работает"))
check("face id работает — ок", "biometric" not in D("face id работает отлично"))
check("вода", "water" in D("был в воде, после воды не включается"))
check("на запчасти", "parts" in D("продам на запчасти"))
check("замена экрана", "screen_replaced" in D("менялся экран, дисплей не оригинал"))
check("акб слабый", "battery" in D("акб слабый, быстро садится"))
check("зарядка не работает", "charging" in D("разъем зарядки не работает"))
check("всё хорошо — пусто", D("идеальное состояние, все работает, без дефектов") == {})

# rule_facts целиком
f = k.rule_facts(ad("iPhone 11 Pro 64gb", "Состояние идеал, акб 91%, полный комплект: коробка, зарядка. Торг уместен. Face ID работает."))
check("модель", f["label"] == "iPhone 11 Pro", f["label"])
check("память", f["mem"] == 64)
check("б/у", f["cond"] == "used")
check("нет дефектов", f["defects"] == {}, f["defects"])
check("акб 91", f["battery_pct"] == 91)
check("торг", f["bargain"] == "yes")
check("комплект", "полный комплект" in f["kit"] and "коробка" in f["kit"], f["kit"])
check("регион", f["region"] == "Минск" and f["area"] == "Центральный")
check("цена 300", f["price"] == 300)

f = k.rule_facts(ad("iPhone X", "Без торга. Разбит экран, акб 72%.", price="0"))
check("без торга", f["bargain"] == "no")
check("разбит экран + слабая акб", "screen" in f["defects"] and "battery" in f["defects"], f["defects"])
check("цены нет", f["price"] == 0)
check("серьёзность 2", k.max_severity(f["defects"]) == 2, k.max_severity(f["defects"]))

f = k.rule_facts(ad("Samsung Galaxy S9 на запчасти", "Не включается"))
check("запчасти -> критично", "parts" in f["defects"] and k.max_severity(f["defects"]) == 3)

f = k.rule_facts(ad("iPhone 8 новый запечатанный", cond="Новый"))
check("новый", f["cond"] == "new")
f = k.rule_facts(ad("iPhone 7 восстановленный 32gb", cond="Б/у"))
check("восстановленный", f["cond"] == "refurb")
f = k.rule_facts(ad("iPhone 7", cond="Б/у"))
check("серьёзность без дефектов = -1", k.max_severity(f["defects"]) == -1)
f = k.rule_facts(ad("iPhone SE 2020", "договорная"))
check("договорная", f["negotiable_price"] is True and f["label"] == "iPhone SE (2020)", f["label"])

print("итого ошибок (разбор):", bad)
sys.exit(1 if bad else 0)
