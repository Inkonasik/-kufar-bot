"""Тесты разбора нейросетью на заглушке (сеть не используется)."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.update(TG_TOKEN="t", TG_CHAT_ID="1", GEMINI_API_KEY="fake-key")
for key in ("ANTHROPIC_API_KEY", "MODELS"):
    os.environ.pop(key, None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fresh_dir  # noqa: E402
tmp = fresh_dir()
sys.path.insert(0, str(tmp))
import requests  # noqa: E402
import kufar_bot as k  # noqa: E402

bad = 0


def check(name, cond, extra=""):
    global bad
    print(("OK  " if cond else "FAIL"), name, "" if cond else extra)
    bad += 0 if cond else 1


def ad(subject, price=30000, desc="", ad_id=1):
    d = {"ad_id": ad_id, "type": "sell", "company_ad": False, "price_byn": str(price), "price_usd": "9000", "subject": subject,
         "ad_link": f"https://www.kufar.by/item/{ad_id}",
         "ad_parameters": [{"p": "condition", "vl": "Б/у"}, {"p": "region", "vl": "Минск"}]}
    if desc:
        d["body_short"] = desc
    return d


calls = []


def stub(reply):
    def _call(prompt, max_tokens=400, json_mode=False):
        calls.append(prompt)
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
    return _call


def reset():
    k._LLM.update(fails=0, off=False, n429=0, last=None, why="")
    k.AI_CACHE.clear()  # тесты независимы друг от друга: разбор из кеша не подменяет вызов заглушки
    calls.clear()


# 1. нормальный ответ: факты дополняются, правила не затираются
reset()
k._llm_call = stub({"is_phone": True, "memory_gb": 128, "condition": "б/у",
                    "defects": [{"type": "screen", "note": "трещина в углу"}, {"type": "выдуманный", "note": "x"}],
                    "battery_pct": 20, "bargain": "торг", "repair_cost_byn": 90, "kit": ["коробка"],
                    "summary": "Продают iPhone 11, трещина в углу экрана.", "risks": ["нет фото"], "face_touch_id": "работает", "lock": "нет"})
f = k.analyze_ad(ad("iPhone 11 64gb", desc="Состояние хорошее"))
check("1 llm-флаг и сводка", f["llm"] and f["summary"].startswith("Продают"), f)
check("1 правила не затёрты: память 64 (а не 128 от нейросети)", f["mem"] == 64, f["mem"])
check("1 дефект от нейросети добавлен, выдуманный тип отброшен", "screen" in f["defects"] and "выдуманный" not in f["defects"], f["defects"])
check("1 батарея 20% (вне 40–100) отброшена", f["battery_pct"] is None and "battery" not in f["defects"], f["battery_pct"])
check("1 торг и цена ремонта", f["bargain"] == "yes" and f["repair_cost"] == 90.0, (f["bargain"], f["repair_cost"]))
check("1 один экранный дефект + цена ремонта продавца -> ремонт известен", k.known_repair_cost(f) == 90.0, k.known_repair_cost(f))
check("1 lock/face из нейросети", k.lock_status(f, "iPhone 11") == "нет" and k.bio_status(f, "iPhone 11") == "работает")
check("1 один вызов нейросети", len(calls) == 1)

# 2. «не телефон»
reset()
k._llm_call = stub({"is_phone": False, "summary": "Продают чехол"})
f = k.analyze_ad(ad("iPhone 11 64gb"))
check("2 is_phone=False учтён", f["is_phone"] is False)
text, ok = k.process_ad(ad("iPhone 11 64gb"))
check("2 process_ad: не телефон -> None", text is None and ok is False)

# 3. мусор в ответе: откат на правила, после двух подряд ошибок нейросеть отключается до конца запуска
reset()
k._llm_call = stub("это не JSON")
f1 = k.analyze_ad(ad("iPhone 8 64gb", desc="разбит экран"))
check("3 мусор: правила работают", f1["llm"] is False and "screen" in f1["defects"], f1)
k.analyze_ad(ad("iPhone 8 64gb"))
check("3 после 2 ошибок нейросеть отключена", k._LLM["off"] is True)
n = len(calls)
k.analyze_ad(ad("iPhone 8 64gb"))
check("3 отключённая нейросеть больше не вызывается", len(calls) == n)

# 4. лимит 429 отключает сразу
reset()
resp = requests.Response()
resp.status_code = 429
k._llm_call = stub(requests.HTTPError("429", response=resp))
k.analyze_ad(ad("iPhone 8 64gb"))
check("4 429: отключено после первой ошибки", k._LLM["off"] is True)

# 5. сообщение целиком с нейросетью (экранирование сводки), без ключей — без вызовов
reset()
k._llm_call = stub({"is_phone": True, "summary": "<b>жир</b> & текст", "risks": ["<i>риск</i>"]})
k._MARKET_REFRESHES["n"] = 99
text, ok = k.process_ad(ad("iPhone 8 64gb"))
check("5 сводка экранирована", text and "&lt;b&gt;жир&lt;/b&gt;" in text and "<i>" not in text, text)
check("5 сообщение в пределах лимита Telegram", text and len(text) <= 4096)

# 6. ошибка внутри оценки не теряет объявление
reset()
k._llm_call = stub({"is_phone": True})
orig = k.appraise
k.appraise = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("сбой"))
text, ok = k.process_ad(ad("iPhone 8 64gb"))
k.appraise = orig
check("6 сбой оценки: уходит обычное сообщение", text and text.startswith("📱") and "iPhone 8" in text and ok is True, text)

print("итого ошибок (нейросеть):", bad)
sys.exit(1 if bad else 0)
