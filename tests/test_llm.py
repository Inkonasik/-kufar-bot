"""Тесты: нейросеть не может переопределять цену и текстовые характеристики; используется только для фото."""
import json
import os
import sys
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


def ad(subject="iPhone 11 64gb", price=10000, desc="Состояние хорошее, акб 100%", ad_id=1, images=True):
    d = {"ad_id": ad_id, "type": "sell", "company_ad": False, "price_byn": str(price), "price_usd": "3500", "subject": subject,
         "ad_link": f"https://www.kufar.by/item/{ad_id}",
         "ad_parameters": [{"p": "condition", "vl": "Б/у"}, {"p": "region", "vl": "Минск"}]}
    if desc:
        d["body_short"] = desc
    if images:
        d["images"] = [{"path": f"adim1/test-{ad_id}.jpg"}]
    return d

calls = []
reply = {"is_phone": True, "memory_gb": 256, "condition": "новый",
         "defects": [{"type": "screen", "note": "экран разбит"}], "battery_pct": 90,
         "bargain": "торг", "repair_cost_byn": 99, "kit": ["коробка"],
         "summary": "ВЫДУМАННЫЙ ТЕКСТ", "risks": ["ВЫДУМАННЫЙ РИСК"],
         "face_touch_id": "работает", "lock": "нет",
         "photos": {"findings": [], "kit_visible": [], "mismatch": "", "quality": "хорошее"}}

def stub(payload):
    def _call(prompt, max_tokens=400, json_mode=False, images=None):
        calls.append({"prompt": prompt, "max_tokens": max_tokens, "json_mode": json_mode, "images": images})
        if isinstance(payload, Exception):
            raise payload
        return payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return _call

def reset():
    k.llm_reset()
    k.AI_CACHE.clear()
    calls.clear()
    k.GEMINI_KEY, k.ANTHROPIC_KEY = "fake-key", ""
    k.fetch_photos = lambda ad_obj: ([ ("image/jpeg", b"fake-image-bytes") ], "")

# AI response includes deliberately incorrect text fields. None may become trusted facts.
reset()
k._llm_call = stub(reply)
a = ad(price=10000, desc="Состояние хорошее, акб 100%", images=True)
f = k.analyze_ad(a)
check("цена берётся из поля Куфара: 100 BYN, а не из ответа нейросети", f["price"] == 100, f["price"])
check("аккумулятор 100% из текста не заменяется выдуманными 90%", f["battery_pct"] == 100, f["battery_pct"])
check("память берётся из заголовка, а не выдуманная 256", f["mem"] == 64, f["mem"])
check("AI-дефект не вмешивается в расчёт рыночной категории", "screen" not in f["defects"], f["defects"])
check("торг / цена ремонта не подставляются из ответа AI", f["bargain"] is None and f["repair_cost"] is None, (f["bargain"], f["repair_cost"]))
check("комплект берётся из текста, а не из ответа AI", f["kit"] == [], f["kit"])
check("свободная AI-сводка и AI-риски не показываются как факты", f["summary"] == "" and f["risks"] == [], (f["summary"], f["risks"]))
check("нейросеть используется только для визуального разбора и ответ должен содержать photos", f["llm"] and f["photo"]["status"] == "analyzed" and len(calls) == 1)

# Without photos, use rule parsing only and do not waste a Gemini call.
reset()
k._llm_call = stub(reply)
f = k.analyze_ad(ad(price=10000, desc="Акб 100%", images=False))
check("без фото нейросеть не вызывается, текстовые правила работают", not calls and not f["llm"] and f["battery_pct"] == 100, (calls, f["battery_pct"]))
check("без фото статус анализа указан честно", f["photo"]["status"] == "no_photos", f["photo"]["status"])

# Strict battery parser: unrelated later percentages must not be mistaken for battery health.
check("battery parser не берёт отдалённый процент", k.parse_battery("АКБ неизвестна, скидка 90%, экран 100%") is None,
      k.parse_battery("АКБ неизвестна, скидка 90%, экран 100%"))
check("battery parser распознаёт прямое «здоровье батареи: 100%»", k.parse_battery("здоровье батареи: 100%") == 100)

# Failed visual request never replaces parsed listing data or blocks the listing.
reset()
resp = requests.Response(); resp.status_code = 429
k._llm_call = stub(requests.HTTPError("429", response=resp))
f = k.analyze_ad(ad(price=10000, desc="Акб 100%", images=True, ad_id=2))
check("ошибка 429 отключает нейросеть, но цена и батарея остаются из объявления", k._LLM["off"] and f["price"] == 100 and f["battery_pct"] == 100,
      (k._LLM, f["price"], f["battery_pct"]))
check("ошибка визуального анализа не превращает нормальное объявление в пропуск", f["is_phone"] is True)

print("итого ошибок (надёжность AI):", bad)
sys.exit(1 if bad else 0)
