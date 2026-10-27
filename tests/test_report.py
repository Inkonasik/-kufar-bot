import json
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
import kufar_bot as k

bad = 0


def check(name, cond, extra=""):
    global bad
    print(("OK  " if cond else "FAIL"), name, "" if cond else extra)
    bad += 0 if cond else 1


# ---- названия моделей ----
labels = {
    "iphone 5s gold 16gb": "iPhone 5s", "apple iphone 4 8gb": "iPhone 4", "iphone 4s": "iPhone 4S".replace("S", "s"),
    "iphone 6 plus 64gb": "iPhone 6 Plus", "iphone 6s plus": "iPhone 6s Plus", "iphone 6+": "iPhone 6 Plus",
    "iphone 6s": "iPhone 6s", "iphone 5c blue": "iPhone 5c", "айфон 5s": "iPhone 5s", "iphone 3gs": "iPhone 3GS",
    "iphone 3g": "iPhone 3G", "iphone 2g": "iPhone 2G", "iphone6": "iPhone 6",
    "ipod touch 4 8gb": "iPod touch 4", "ipod touch 32gb": "iPod touch", "айпод тач 5": "iPod touch 5",
    "samsung galaxy s5": "Galaxy S5", "samsung galaxy s5 mini": "Galaxy S5 Mini", "samsung galaxy s6 edge": "Galaxy S6 Edge",
    "samsung galaxy s6 edge+": "Galaxy S6 Edge+", "samsung galaxy s6 edge plus": "Galaxy S6 Edge+",
    "samsung galaxy s7": "Galaxy S7", "samsung galaxy s ii": "Galaxy S2", "samsung galaxy s iii": "Galaxy S3",
    "samsung galaxy s4 active": "Galaxy S4 Active", "samsung galaxy s": "Galaxy S", "samsung galaxy s plus": "Galaxy S Plus",
    "самсунг галакси s4": "Galaxy S4", "samsung gt-i9300": "Другое", "телефон": "Другое",
}
for text, want in labels.items():
    got = k.model_label(text)
    check(f"label {text!r} -> {want}", got == want, got)

# ---- запись истории ----
ad = {"ad_id": 7, "subject": "iPhone 5s 16gb", "price_byn": "15000", "ad_link": "https://x/7",
      "ad_parameters": [{"p": "condition", "vl": "Б/у"}, {"p": "phones_brand", "vl": "Apple"}]}
k.record_ad(ad, True)
r = k.HISTORY["7"]
check("record_ad: модель, цена, состояние", r["m"] == "iPhone 5s" and r["p"] == 150 and r["c"] == "Б/у" and r["ok"], r)
k.HISTORY.clear()

# ---- отчёт ----
NOW = 1_800_000_000
DAY = 86400
def add(i, label, price, cond, days_ago, ok=True):
    k.HISTORY[str(i)] = {"t": NOW - int(days_ago * DAY), "m": label, "p": price, "c": cond,
                         "s": f"{label} <test>", "l": f"https://x/{i}", "ok": ok}

n = 0
for price in (130, 135, 140, 140, 145, 150, 150, 155, 90):   # 9 б/у на этой неделе, одна дешёвая
    n += 1; add(n, "iPhone 5s", price, "Б/у", 2)
for price in (230, 240):
    n += 1; add(n, "iPhone 5s", price, "Новое", 3)
for price in (150, 150, 155, 160):                              # прошлая неделя (медиана выше)
    n += 1; add(n, "iPhone 5s", price, "Б/у", 10)
n += 1; add(n, "iPhone 5s", 5, "Б/у", 1, ok=False)              # мусор по мнению нейросети
n += 1; add(n, "iPhone 5s", 140, "Б/у", 40)                    # слишком старое
n += 1; add(n, "iPhone 5s", 0, "Б/у", 1)                       # без цены: считается объявлением, но не в цены
for price in (40, 50, 60):
    n += 1; add(n, "Galaxy S5", price, "Б/у", 1)

res = k.build_report(NOW)
check("отчёт построен", res is not None)
text, facts = res
print("-----\n" + text + "\n-----\n" + facts + "\n-----")
check("5s: 11 шт с ценой (9 б/у + 2 новых)", "iPhone 5s</b>: 11 шт" in text, text)
check("медиана 5s = 145", "медиана 145" in text, text)
check("есть стрелка вниз к прошлой неделе", "▼" in text, text)
check("состояние: Б/у 9 шт, Новое 2 шт", "Б/у: 9 шт" in text and "Новое: 2 шт" in text, text)
check("мусор (ok=False), старое и цена 0 не в ценах", "от 90 до 240" in text, text)
check("Galaxy S5: 3 шт, меньше 4 — выгодных не ищем для него", "Galaxy S5</b>: 3 шт" in text, text)
check("выгодное найдено (90 ≤ 0.7·145)", "🔥" in text and "90 BYN" in text, text)
check("HTML в названии экранирован", "&lt;test&gt;" in text and "<test>" not in text, text)
check("для нейросети есть цифры", "iPhone 5s: 11 шт" in facts and "прошлая неделя" in facts, facts)

# ---- отправка отчёта ----
sent = []
k.tg_send = lambda t: sent.append(t)
k.build_report = lambda now=None, _orig=k.build_report: _orig(NOW)
k.send_report()
check("без ключа: отчёт ушёл, без выводов нейросети", len(sent) == 1 and "Выводы нейросети" not in sent[0], sent)

sent.clear()
k.GEMINI_KEY = "x"
k._llm_call = lambda prompt, max_tokens=400, json_mode=False: " - вывод <b>раз</b> "
k.send_report()
check("с ключом: выводы добавлены и экранированы", "Выводы нейросети" in sent[-1] and "&lt;b&gt;раз" in sent[-1], sent[-1][-200:])

sent.clear()
def boom(*a, **kw): raise RuntimeError("429")
k._llm_call = boom
k.send_report()
check("ошибка нейросети: отчёт всё равно ушёл", len(sent) == 1 and "Выводы нейросети" not in sent[0], sent)
k.GEMINI_KEY = ""

sent.clear()
k.HISTORY.clear()
k.send_report()
check("пустая история: сообщение «данных пока нет»", len(sent) == 1 and "данных пока нет" in sent[0], sent)

# ---- длинные сообщения ----
sent.clear()
long_text = "\n".join(f"строка {i} " + "я" * 90 for i in range(200))
k.tg_send_long(long_text)
check("длинный текст режется на куски ≤ 4096", len(sent) > 1 and all(len(s) <= 4096 for s in sent), [len(s) for s in sent])
check("ничего не потеряно", "".join(sent).replace("\n", "") == long_text.replace("\n", ""))

# ---- seen.json: форматы и чистка ----
k.SEEN_FILE = tmp / "seen.json"
k.HISTORY.clear()
k.SEEN_FILE.write_text(json.dumps([1, 2, 3]))
check("старый формат (список) читается", k.load_seen() == {1, 2, 3} and k.HISTORY == {})

import time as _t
k.HISTORY["a"] = {"t": int(_t.time()), "m": "iPhone 5s", "p": 100, "c": "Б/у", "s": "s", "l": "l", "ok": True}
k.HISTORY["old"] = {"t": int(_t.time()) - 40 * DAY, "m": "iPhone 5s", "p": 100, "c": "Б/у", "s": "s", "l": "l", "ok": True}
k.save_seen(k.Seen({1, 2, 3, 4}))
data = json.loads(k.SEEN_FILE.read_text())
check("новый формат: seen с отметками времени + history, старое (40 дн.) вычищено",
      {int(x) for x in data["seen"]} == {1, 2, 3, 4}
      and all(isinstance(t, int) for t in data["seen"].values())
      and list(data["history"]) == ["a"], data)
k.HISTORY.clear()
check("круг: сохранили и прочитали", k.load_seen() == {1, 2, 3, 4} and "a" in k.HISTORY)

print("итого ошибок:", bad)
sys.exit(1 if bad else 0)
