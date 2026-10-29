"""Описание и фото → Gemini → факты → оценка (сквозной путь, сеть и часы подменены; настоящих запросов нет).
Проверяется: в Gemini уходит ПОЛНОЕ описание из карточки и НАСТОЯЩИЕ байты картинок (base64), а не ссылки; находки на фото
влияют на расчёт только при уверенном видимом дефекте; одинаковый дефект в тексте и на фото учитывается один раз; пересказ
текста нейросетью не считается наблюдением; сомнительная находка снижает уверенность, но не цену; без фото / при сбое загрузки
/ при 503 и 429 ничего не выдаётся за проведённый анализ; кеш разборов разделён по объявлению и содержимому."""
import base64
import json
import os
import struct
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fresh_dir  # noqa: E402

D = fresh_dir()
sys.path.insert(0, str(D))
os.environ.update(GEMINI_API_KEY="fake-key", TG_TOKEN="t", TG_CHAT_ID="1", MESSAGE_STYLE="short")
sys.argv = ["kufar_bot.py", "--once"]
import kufar_bot as k  # noqa: E402

LOGS = []
k.log = lambda *a: LOGS.append(" ".join(str(x) for x in a))
T0 = 1_793_196_000.0
NOW = [T0]
time.time = lambda: NOW[0]
time.sleep = lambda s: NOW.__setitem__(0, NOW[0] + max(0.0, float(s)))
k.KUFAR_PAUSE = k.SEND_PAUSE = 0.0
k.SEEN_FILE, k.MARKET_DB_FILE, k.MARKET_DB_BACKUP = D / "seen.json", D / "market_history.json", D / "market_history.backup.json"
bad = 0


def check(name, cond, extra=""):
    global bad
    print(("OK  " if cond else "FAIL"), name, "" if cond else extra)
    bad += 0 if cond else 1


def png(seed):
    """Настоящий PNG 2×2 (разные байты для разных фото)."""
    raw = b"".join(b"\x00" + bytes([seed, 255 - seed, seed // 2] * 2) for _ in range(2))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


IMAGES = {f"adim1/p{i}.png": png(40 + i) for i in range(4)}
FULL_DESC = ("Продаю iPhone X 64 ГБ. Пользовался аккуратно, в чехле. Всё работает, Face ID работает, аккумулятор 87%. "
             "В комплекте коробка и кабель. Торг уместен. Это длинное описание из карточки — в выдаче его нет целиком. " * 2).strip()


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def comp(i, title, price, desc):
    return {"ad_id": 7000 + i, "type": "sell", "subject": title, "price_byn": str(price * 100), "price_usd": "0", "currency": "BYR",
            "list_time": iso(T0 - 3600 - i * 60), "ad_link": f"https://www.kufar.by/item/{7000 + i}", "body_short": desc,
            "ad_parameters": [{"p": "condition", "vl": "Б/у"}, {"p": "region", "vl": "Минск"}]}


COMPS = ([comp(i, "iPhone X 64gb", 300 + 10 * i, "Всё работает, без дефектов") for i in range(9)]
         + [comp(20 + i, "iPhone X 64gb разбит экран", 170 + 10 * i, "Разбит экран, остальное работает") for i in range(7)])
WORLD = {"cards": {}, "gemini": [], "posts": [], "cdn_fail": False}


class R:
    def __init__(self, data=None, code=200, content=b"", ctype="application/json"):
        self.data, self.status_code, self.content = data, code, content
        self.headers = {"Content-Type": ctype}

    def raise_for_status(self):
        if self.status_code >= 400:
            e = k.requests.HTTPError(str(self.status_code))
            e.response = self
            raise e

    def json(self):
        return self.data


def fake_get(url, params=None, **kw):
    if "/item/" in url:
        i = url.split("/item/")[1].split("/")[0]
        return R({"result": WORLD["cards"].get(i, {})})
    if "rms.kufar.by" in url or "yams.kufar.by" in url:
        if WORLD["cdn_fail"]:
            return R(code=404, ctype="text/html")
        for path, data in IMAGES.items():
            if path in url:
                return R(content=data, ctype="image/png")
        return R(code=404, ctype="text/html")
    return R({"ads": [dict(c) for c in COMPS]})  # поиск аналогов


def fake_post(url, **kw):
    if "generativelanguage.googleapis.com" not in url:
        raise AssertionError("неожиданный POST: " + url)
    WORLD["posts"].append(kw["json"])
    step = WORLD["gemini"].pop(0) if WORLD["gemini"] else {"photos": {"findings": [], "kit_visible": [], "mismatch": "", "quality": "хорошее"}}
    if isinstance(step, int):
        return R({"error": {"code": step, "message": "fake"}}, code=step)
    return R({"candidates": [{"content": {"parts": [{"text": json.dumps(step, ensure_ascii=False)}]}}]})


k.requests.get, k.requests.post = fake_get, fake_post
k.RUN["deadline"] = 0


def target(ad_id, desc_short="iPhone X 64gb, состояние хорошее", n_img=2, card_body=FULL_DESC, price=200):
    WORLD["cards"][str(ad_id)] = {"body": card_body, "price_byn": str(price * 100)}
    return {"ad_id": ad_id, "type": "sell", "subject": "iPhone X 64gb", "price_byn": str(price * 100), "price_usd": "0", "currency": "BYR",
            "list_time": iso(NOW[0] - 60), "ad_link": f"https://www.kufar.by/item/{ad_id}", "body_short": desc_short,
            "images": [{"path": p} for p in list(IMAGES)[:n_img]],
            "ad_parameters": [{"p": "condition", "vl": "Б/у"}, {"p": "region", "vl": "Минск"}]}


def run_ad(ad_, gemini=None, cdn_fail=False):
    """Как в боте: process_ad (карточка → разбор → фото → оценка → сообщение). Возвращает (факты, оценка, сообщение, новые POST)."""
    k.llm_reset()
    k.mdb_reset()  # каждый сценарий — на одном и том же рынке (иначе прошлые объявления сценариев становятся аналогами)
    k.STATE["market"] = {}
    k.RUN.update(cards=0, card_fails=0, img_fails=0)
    k._MARKET_REFRESHES["n"] = 0  # как в начале каждого запуска (cycle)
    WORLD["gemini"], WORLD["cdn_fail"] = list(gemini or []), cdn_fail
    n0 = len(WORLD["posts"])
    captured = {}
    orig_appraise = k.appraise

    def spy(a, f, now=None):
        captured["facts"], captured["ap"] = f, orig_appraise(a, f, now)
        return captured["ap"]
    k.appraise = spy
    try:
        text, _ok = k.process_ad(ad_)
    finally:
        k.appraise = orig_appraise
    return captured.get("facts"), captured.get("ap"), text, WORLD["posts"][n0:]


def limit(ap):
    plan = ap.get("plan") or {}
    c = plan.get(plan.get("best")) if plan.get("best") else None
    return c["limit"] if c else None


def finding(kind, what, conf="высокая"):
    return {"part": "экран", "kind": kind, "what": what, "confidence": conf, "check": "осмотреть"}


def resp(*finds, quality="хорошее", mismatch=""):
    return {"photos": {"findings": list(finds), "kit_visible": ["коробка"], "mismatch": mismatch, "quality": quality},
            "battery_pct": 50, "model": "iPhone 15"}


# ---------------------------------------------------------------------------------------------------------------------
# 1. Что уходит в Gemini
# ---------------------------------------------------------------------------------------------------------------------
fA, apA, msgA, postsA = run_ad(target(9001), [resp()])
body = postsA[0] if postsA else {}
parts = (body.get("contents") or [{}])[0].get("parts") or []
texts = [p_["text"] for p_ in parts if "text" in p_]
imgs = [p_["inline_data"] for p_ in parts if "inline_data" in p_]
check("1 один запрос к Gemini на объявление, в нём текст и 2 картинки", len(postsA) == 1 and len(texts) == 1 and len(imgs) == 2,
      (len(postsA), len(texts), len(imgs)))
check("1б в запросе — НАСТОЯЩИЕ байты обеих картинок (base64 совпадает с файлами CDN), тип image/png, ссылок на картинки нет",
      [base64.b64decode(i_["data"]) for i_ in imgs] == list(IMAGES.values())[:2] and all(i_["mime_type"] == "image/png" for i_ in imgs)
      and "kufar.by" not in json.dumps(body), [i_.get("mime_type") for i_ in imgs])
check("1в в запросе — ПОЛНОЕ описание из карточки, а не короткое из выдачи", FULL_DESC in texts[0] and fA["desc"] == FULL_DESC,
      texts[0][:300] if texts else None)
check("1г ответ нейросети про аккумулятор/модель не принят: модель и АКБ из текста продавца (87%), не 50% и не iPhone 15",
      fA["label"] == "iPhone X" and fA["battery_pct"] == 87, (fA["label"], fA["battery_pct"]))

# ---------------------------------------------------------------------------------------------------------------------
# 2. Находки на фото влияют на расчёт (только уверенные видимые)
# ---------------------------------------------------------------------------------------------------------------------
fB, apB, msgB, _ = run_ad(target(9002), [resp(finding("screen", "трещина на экране от левого угла"))])
check("2 уверенная трещина на фото (продавец о ней молчит): дефект «по фото» в расчёте, источник — фото",
      fB["defects"].get("screen", "").startswith("по фото") and fB["defect_src"].get("screen") == "фото"
      and "screen" not in fB["defects_text"], (fB["defects"], fB.get("defect_src")))
check("2б максимальная цена покупки снизилась: оценка по аналогам с разбитым экраном, а не по исправным",
      limit(apA) and limit(apB) is not None and limit(apB) < limit(apA), (limit(apA), limit(apB)))
check("2в уверенность не выше средней: дефект видит только нейросеть", apB.get("conf") in ("средняя", "низкая")
      and any("на фото" in w for w in apB.get("conf_why") or []), (apB.get("conf"), apB.get("conf_why")))

fC, apC, _, _ = run_ad(target(9003, card_body="Разбит экран, остальное всё работает. АКБ 87%."), [resp(finding("screen", "трещина на экране"))])
fCt, apCt, _, _ = run_ad(target(9004, card_body="Разбит экран, остальное всё работает. АКБ 87%."), [resp()])
check("2г тот же дефект в тексте и на фото — учтён ОДИН раз (источник «текст+фото»), максимум покупки как при одном тексте",
      list(fC["defects"]).count("screen") == 1 and fC["defect_src"]["screen"] == "текст+фото" and limit(apC) == limit(apCt),
      (fC["defects"], fC.get("defect_src"), limit(apC), limit(apCt)))

fD, apD, _, _ = run_ad(target(9005), [resp(finding("screen", "возможно, царапина на экране", conf="средняя"))])
check("2д сомнительная находка (средняя уверенность): цена и максимум как без неё, но уверенность снижена и причина названа",
      limit(apD) == limit(apA) and "screen" not in fD["defects"] and any("возможен дефект" in w for w in apD.get("conf_why") or []),
      (limit(apD), limit(apA), apD.get("conf_why")))
fE, apE, _, _ = run_ad(target(9006), [resp(finding("cosmetic", "мелкие царапины (по описанию продавца)"))])
check("2е пересказ текста нейросетью («по описанию продавца») не считается наблюдением по фото", "cosmetic" not in fE["defects"]
      and limit(apE) == limit(apA) and not (fE["photo"].get("confirmed") or fE["photo"].get("possible")), fE["photo"])
fF, apF, _, _ = run_ad(target(9007), [resp(finding("screen", "трещина"), quality="плохое")])
check("2ж фото плохого качества: даже «высокая» находка в цену не идёт, только снижает уверенность",
      "screen" not in fF["defects"] and limit(apF) == limit(apA) and fF["photo"].get("possible"), fF["photo"])
fG, apG, _, _ = run_ad(target(9008), [resp(finding("other", "повреждения под наклейками"))])
check("2з неясная находка («other») в цену не идёт", not set(fG["defects"]) - set(fG["defects_text"]) and limit(apG) == limit(apA))
check("2и нет видимых дефектов на фото — это НЕ делает телефон «исправным»: категория та же, что по тексту",
      k.ad_cat(fA) == k.ad_cat(k.rule_facts(dict(target(9009), body=FULL_DESC))), (k.ad_cat(fA),))
fM, apM, _, _ = run_ad(target(9010), [resp(finding("screen", "трещина"), mismatch="в тексте «всё работает», а на экране трещина")])
check("2к фото противоречит описанию: уверенность низкая", apM.get("conf") == "низкая", apM.get("conf"))

# ---------------------------------------------------------------------------------------------------------------------
# 3. Нет фото / сбой загрузки / сбой Gemini — анализ не выдаётся за проведённый
# ---------------------------------------------------------------------------------------------------------------------
fN, apN, msgN, postsN = run_ad(target(9011, n_img=0))
check("3 у объявления нет фото: запроса к Gemini нет, статус no_photos, расчёт как по тексту", not postsN
      and fN["photo"]["status"] == "no_photos" and limit(apN) == limit(apA), (fN["photo"], limit(apN)))
fL, apL, _, postsL = run_ad(target(9012), cdn_fail=True)
check("3б фото не загрузились: запроса к Gemini нет, статус no_download", not postsL and fL["photo"]["status"] == "no_download",
      fL["photo"])
fS, apS, msgS, postsS = run_ad(target(9013), [503, 503, 503, 503])
check("3в Gemini 503: повторы, затем отказ; статус «нейросеть недоступна», расчёт по тексту, находок нет",
      fS["photo"]["status"] == "llm_off" and limit(apS) == limit(apA) and not fS["photo"].get("findings") and len(postsS) >= 2,
      (fS["photo"], len(postsS)))
fQ, apQ, _, postsQ = run_ad(target(9014), [429, 429])
check("3г Gemini 429: не больше одного повтора, затем нейросеть выключена до конца запуска; расчёт по тексту",
      fQ["photo"]["status"] == "llm_off" and len(postsQ) <= 2 and limit(apQ) == limit(apA), (fQ["photo"], len(postsQ)))
check("3д в коротком сообщении нет раздела о фото и описании ни в одном случае",
      all("По фото" not in m_ and "По описанию" not in m_ for m_ in (msgA, msgB, msgN, msgS)), msgB)

# ---------------------------------------------------------------------------------------------------------------------
# 4. Кеш разборов разделён по объявлению и содержимому
# ---------------------------------------------------------------------------------------------------------------------
n0 = len(WORLD["posts"])
run_ad(target(9002), [resp(finding("screen", "трещина на экране от левого угла"))])
check("4 повторный разбор того же объявления с тем же текстом и фото — из кеша, без запроса", len(WORLD["posts"]) == n0)
fB2, _, _, p2 = run_ad(target(9002, card_body=FULL_DESC + " Добавлю: есть царапина на рамке."), [resp()])
check("4б описание изменилось — новый запрос (кеш не подменяет новое содержимое старым разбором)", len(p2) == 1, len(p2))
_, _, _, p3 = run_ad(target(9015), [resp()])
check("4в другое объявление с теми же фото — свой запрос (кеш по номеру объявления)", len(p3) == 1, len(p3))

# ---------------------------------------------------------------------------------------------------------------------
# 5. База: слова продавца и находки на фото хранятся раздельно
# ---------------------------------------------------------------------------------------------------------------------
_fB3, _apB3, _, _ = run_ad(target(9016), [resp(finding("screen", "трещина на экране"))])
r3 = k._mdb_ads().get("9016") or {}
check("5 в базе дефекты продавца отдельно (их нет), трещина — в photo.confirmed с пометкой «не проверка»",
      "defects" not in r3 and (r3.get("photo") or {}).get("confirmed") == [{"code": "screen", "what": "трещина на экране"}]
      and "не проверка" in (r3.get("photo") or {}).get("src", "") and "фото" in (r3.get("condition_cat") or {}).get("src", ""),
      (r3.get("defects"), r3.get("photo"), r3.get("condition_cat")))

print(f"итого ошибок (фото и описание → оценка): {bad}")
sys.exit(1 if bad else 0)
