"""Тесты определения моделей (iPhone 7–11, SE, Galaxy S7–S9), защиты от ложных совпадений и аксессуаров."""
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


# текст -> ожидаемая метка модели (None = не наша новая модель)
CASES = {
    # iPhone 7 / 8
    "iPhone 7": "iPhone 7", "iphone7": "iPhone 7", "i phone 7": "iPhone 7", "Айфон 7": "iPhone 7",
    "айфон7": "iPhone 7", "айфон семь": "iPhone 7", "IPHONE 7 32GB BLACK": "iPhone 7",
    "iPhone 7 Plus": "iPhone 7 Plus", "iphone 7+": "iPhone 7 Plus", "айфон 7 плюс": "iPhone 7 Plus",
    "iPhone 7plus 128gb": "iPhone 7 Plus", "Apple iPhone 7 plus": "iPhone 7 Plus", "iphone 7 +": "iPhone 7 Plus",
    "iPhone 8": "iPhone 8", "айфон 8 64гб": "iPhone 8", "Айфон восемь": "iPhone 8",
    "iPhone 8 Plus": "iPhone 8 Plus", "iphone 8+": "iPhone 8 Plus", "iphone 8 плюс 256": "iPhone 8 Plus",
    # X / XR / XS / XS Max
    "iPhone X": "iPhone X", "iPhone 10": "iPhone X", "Айфон X": "iPhone X", "Айфон Икс": "iPhone X",
    "Айфон Х 64": "iPhone X", "iphone x 256gb space gray": "iPhone X", "айфон десять": "iPhone X",
    "iPhone XR": "iPhone XR", "айфон xr": "iPhone XR", "Айфон ХР": "iPhone XR", "iphone 10r": "iPhone XR",
    "Айфон Икс Эр": "iPhone XR", "iPhone XS": "iPhone XS", "iphone xs 64": "iPhone XS", "iphone 10s": "iPhone XS",
    "Айфон Икс Эс": "iPhone XS", "iPhone XS Max": "iPhone XS Max", "iphone xsmax": "iPhone XS Max",
    "айфон xs макс": "iPhone XS Max", "iphone 10s max": "iPhone XS Max", "Айфон Икс Эс Макс": "iPhone XS Max",
    "iphone x max": "iPhone XS Max",
    # 11
    "iPhone 11": "iPhone 11", "iphone11": "iPhone 11", "Айфон 11": "iPhone 11", "iphone одиннадцать": "iPhone 11",
    "iPhone 11 Pro": "iPhone 11 Pro", "iphone 11pro": "iPhone 11 Pro", "Айфон 11 про": "iPhone 11 Pro",
    "iPhone 11 Pro Max": "iPhone 11 Pro Max", "Айфон 11 про макс": "iPhone 11 Pro Max",
    "iphone 11 promax 256": "iPhone 11 Pro Max", "iphone 11pro max": "iPhone 11 Pro Max",
    "Apple iPhone 11 128gb": "iPhone 11", "apple 11 pro 256": "iPhone 11 Pro",
    # SE
    "iPhone SE": "iPhone SE", "iPhone SE 2016": "iPhone SE (2016)", "iphone se 1": "iPhone SE (2016)",
    "iPhone SE 2020": "iPhone SE (2020)", "iphone se 2": "iPhone SE (2020)", "iphone se2": "iPhone SE (2020)",
    "iPhone SE 2nd generation": "iPhone SE (2020)", "iPhone SE 2022": "iPhone SE (2022)",
    "iphone se 3": "iPhone SE (2022)", "iphone se 5g 64gb": "iPhone SE (2022)", "iPhone SE 64gb": "iPhone SE",
    "iphone se 128gb": "iPhone SE", "iphone se 32gb 2016": "iPhone SE (2016)", "Айфон SE 2020": "iPhone SE (2020)",
    # Samsung
    "Samsung Galaxy S7": "Galaxy S7", "Samsung S7": "Galaxy S7", "Galaxy S7 Edge": "Galaxy S7 Edge",
    "samsung s7 edge": "Galaxy S7 Edge", "Самсунг гэлакси S7": "Galaxy S7", "самсунг с7": "Galaxy S7",
    "Samsung Galaxy S7 Active": "Galaxy S7 Active", "SM-G935F": "Galaxy S7 Edge", "samsung sm-g930f": "Galaxy S7",
    "Samsung Galaxy S8": "Galaxy S8", "Samsung Galaxy S8+": "Galaxy S8+", "galaxy s8 plus": "Galaxy S8+",
    "самсунг s8 плюс": "Galaxy S8+", "samsung s 8": "Galaxy S8", "samsung s8 active": "Galaxy S8 Active",
    "Продам s8 64gb samsung": "Galaxy S8", "SM-G950F/DS": "Galaxy S8", "sm-g955f samsung": "Galaxy S8+",
    "Samsung Galaxy S9": "Galaxy S9", "Galaxy S9+": "Galaxy S9+", "samsung s9 plus 64gb": "Galaxy S9+",
    "самсунг гэлакси с9": "Galaxy S9", "Samsung Galaxy S9 Dual Sim": "Galaxy S9", "sm-g965f": "Galaxy S9+",
}
for text, want in CASES.items():
    got = k.identify_model(text)
    check(f"identify {text!r}", got == want, f"получили {got!r}, ждали {want!r}")

# --- не наши модели: ничего не должно определиться как новая модель ---
NOT_NEW = [
    "iPhone 6", "iphone 6s", "iPhone 6 Plus", "iphone 5", "iphone 5s", "iphone 4s", "iphone 3gs", "iPhone 2G",
    "iPhone 12", "iphone 12 pro max", "iPhone 12 mini", "iphone 13", "iPhone 14 Pro", "iphone 15 pro max",
    "iphone 4 8gb", "iPhone 8gb", "iPhone 6 обмен на iphone 7", "Apple Watch 7", "iPad 8", "AirPods Pro",
    "Samsung Galaxy S10", "Galaxy S10+", "Samsung S20", "Galaxy S21 Ultra", "Samsung S23 FE", "samsung galaxy s6",
    "Samsung S6 edge", "Samsung Galaxy S5", "Galaxy Tab S7", "Samsung Galaxy Tab S8 Ultra", "Samsung Galaxy A8",
    "Samsung Note 9", "Samsung A52 с 8 гб", "Samsung Galaxy A7 2018", "Xiaomi Redmi Note 9S", "Honor 9",
    "iPod touch 5", "ipod touch 6",
]
for text in NOT_NEW:
    got = k.identify_model(text)
    check(f"не новая {text!r}", got is None, f"получили {got!r}")

# --- model_label: старые метки не изменились, новые есть ---
OLD = {
    "iphone 5s gold 16gb": "iPhone 5s", "apple iphone 4 8gb": "iPhone 4", "iphone 6 plus 64gb": "iPhone 6 Plus",
    "iphone 6s plus": "iPhone 6s Plus", "iphone 6+": "iPhone 6 Plus", "айфон 5s": "iPhone 5s",
    "iphone 3gs": "iPhone 3GS", "ipod touch 4 8gb": "iPod touch 4", "samsung galaxy s5": "Galaxy S5",
    "samsung galaxy s6 edge plus": "Galaxy S6 Edge+", "samsung galaxy s ii": "Galaxy S2", "телефон": "Другое",
    "iphone 4 8gb": "iPhone 4", "iPhone 6 обмен на iphone 7": "iPhone 6",
}
for text, want in OLD.items():
    check(f"model_label старая {text!r}", k.model_label(text.lower()) == want, k.model_label(text.lower()))
check("model_label новая", k.model_label("iphone 11 pro max 256") == "iPhone 11 Pro Max")
check("model_label S9+", k.model_label("samsung galaxy s9+") == "Galaxy S9+")

# --- basic_filter: объявления целиком ---
def ad(subject, **extra):
    d = {"ad_id": 1, "type": "sell", "company_ad": False, "price_byn": "30000", "subject": subject,
         "ad_link": "https://www.kufar.by/item/1", "ad_parameters": []}
    d.update(extra)
    return d


PASS = ["iPhone 11 64gb", "Айфон 7 plus 128", "iPhone SE 2020", "Samsung Galaxy S8+", "самсунг s9", "iPhone X",
        "iPhone XS Max 256", "iPhone 8 на запчасти", "iphone 5s", "Samsung Galaxy S5", "iPod touch 5",
        "Айфон 11 pro max, торг"]
REJECT = ["iPhone 12", "iPhone 13 Pro", "Samsung Galaxy S10", "Galaxy S20", "Galaxy Tab S7", "Чехол для iPhone 11",
          "Стекло iPhone 7", "Дисплей iPhone 8", "Коробка от iPhone 11", "Зарядка для iPhone", "Запчасти iPhone 7",
          "Замена экрана iPhone X", "Куплю iPhone 11", "Скупка iPhone 7", "Муляж iPhone 8", "Samsung A52", "Xiaomi 11",
          "Аккумулятор для Samsung Galaxy S8"]
for s in PASS:
    check(f"фильтр пропускает {s!r}", k.basic_filter(ad(s)))
for s in REJECT:
    check(f"фильтр отбрасывает {s!r}", not k.basic_filter(ad(s)))
check("не sell отбрасываем", not k.basic_filter(ad("iPhone 11", type="buy")))
check("параметры: модель в phones_model",
      k.basic_filter(ad("Продам телефон", ad_parameters=[{"p": "phones_model", "vl": "iPhone 11 Pro"},
                                                         {"p": "phones_brand", "vl": "Apple"}])))

# --- аксессуары ---
for s in ["Чехол iPhone 11", "защитное стекло на iphone 7", "Дисплей для Samsung S8", "Ремонт iPhone", "Коробка iPhone X"]:
    check(f"аксессуар {s!r}", k.looks_like_accessory(s))
for s in ["iPhone 11 64gb", "Apple iPhone 7 на запчасти", "Новый iPhone 11 в плёнке", "Samsung Galaxy S8 разбит экран"]:
    check(f"не аксессуар {s!r}", not k.looks_like_accessory(s))

print("итого ошибок (модели):", bad)
sys.exit(1 if bad else 0)
