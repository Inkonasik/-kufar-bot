"""Ограничитель запросов к Gemini: пауза и лимит в минуту, 429 и 503 по отдельности, повторные 429, кеш, работа без нейросети.
Сеть и время поддельные: «часы» ходят мгновенно (ожидание просто сдвигает стрелку), а поддельный Gemini сам считает запросы за минуту
и отвечает 429, как настоящий бесплатный уровень (15 запросов в минуту)."""
import json
import os
import subprocess
import sys
import time
from email.utils import formatdate
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

k.MESSAGE_STYLE = "full"  # здесь проверяются пометки про нейросеть и фото — они есть в подробном разборе

bad = 0
real_time = time.time


def check(name, cond, extra=""):
    global bad
    print(("OK  " if cond else "FAIL"), name, "" if cond else extra)
    bad += 0 if cond else 1


# ---------------------------------------------------------------------------------------------------------------------
# Поддельные часы, сеть и сервер Gemini
# ---------------------------------------------------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.t, self.naps = 5000.0, []

    def mono(self):
        return self.t

    def nap(self, sec):
        self.naps.append(sec)
        self.t += sec


clock = Clock()
k._mono, k._nap = clock.mono, clock.nap
logs = []
k.log = lambda *a: logs.append(" ".join(str(x) for x in a))


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self.body, self.headers = status, body, headers or {}

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            e = requests.HTTPError(str(self.status_code))
            e.response = self
            raise e


OK_REPLY = {"is_phone": True, "memory_gb": 64, "condition": "б/у", "defects": [], "summary": "Продают iPhone.", "risks": [], "kit": []}
PHOTO_REPLY = dict(OK_REPLY, photos={"findings": [], "kit_visible": ["коробка"], "mismatch": "", "quality": "хорошее"})


def ok_text(text):
    return Resp(200, {"candidates": [{"content": {"parts": [{"text": text}]}}]})


def ok(reply=None):
    # Для анализа объявления нормальный ответ содержит визуальный блок photos.
    return ok_text(json.dumps(reply if reply is not None else PHOTO_REPLY, ensure_ascii=False))


MINUTE = "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
DAY = "GenerateRequestsPerDayPerProjectPerModel-FreeTier"


def err429(header=None, delay=None, quota=MINUTE):
    """Ответ 429 в том виде, как его присылает Gemini: QuotaFailure + (необязательно) RetryInfo; Retry-After — по желанию."""
    details = [{"@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                                "quotaId": quota, "quotaValue": "15"}]}]
    if delay is not None:
        details.append({"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay})
    body = {"error": {"code": 429, "message": "You exceeded your current quota, please check your plan and billing details.",
                      "status": "RESOURCE_EXHAUSTED", "details": details}}
    return Resp(429, body, {"Retry-After": header} if header is not None else {})


def err5xx(code=503, header=None):
    body = {"error": {"code": code, "message": "The model is overloaded. Please try again later.", "status": "UNAVAILABLE"}}
    return Resp(code, body, {"Retry-After": header} if header is not None else {})


class Server:
    """Поддельный Gemini: отвечает по сценарию (ответы и исключения по очереди), потом — default(сервер) или удачным ответом."""
    def __init__(self, script=(), latency=0.0, default=None):
        self.script, self.latency, self.default = list(script), latency, default
        self.calls, self.accepted, self.rejected = [], [], 0

    def post(self, url, **kw):
        self.calls.append({"t": clock.t, "url": url, "json": kw.get("json"), "headers": kw.get("headers"), "timeout": kw.get("timeout")})
        clock.t += self.latency
        item = self.script.pop(0) if self.script else (self.default(self) if self.default else ok())
        if isinstance(item, Exception):
            raise item
        return item

    def times(self):
        return [c["t"] for c in self.calls]


def strict15(srv):
    """Бесплатный лимит Google: больше 15 запросов за скользящую минуту — 429 с подсказкой «подождите 20 с»."""
    recent = [t for t in srv.accepted if clock.t - t < 60]
    if len(recent) >= 15:
        srv.rejected += 1
        return err429(delay="20s")
    srv.accepted.append(clock.t)
    return ok()


def setup(script=(), latency=0.0, default=None):
    """Новый «запуск»: часы идут дальше, а ограничитель, счётчики, кеш и настройки — чистые."""
    k.llm_reset()
    k.AI_CACHE.clear()
    k._GATE.update(stamps=[], last=None)
    k.RUN.update(deadline=0.0, cards=0, card_fails=0, img_fails=0)
    k.GEMINI_KEY, k.ANTHROPIC_KEY = "fake-key", ""
    k.GEMINI_RPM, k.GEMINI_MIN_GAP_S, k.GEMINI_RETRIES, k.GEMINI_MAX_WAIT_S, k.HTTP_BACKOFF = 10, 6.0, 2, 60.0, 1.0
    k.PHOTOS_MAX = 4
    k.AI_CACHE_MAX = 200
    clock.naps.clear()
    logs.clear()
    srv = Server(script, latency, default)
    k.requests.post = srv.post
    return srv


class Img:
    status_code = 200
    headers = {"Content-Type": "image/jpeg"}
    content = b"\xff\xd8\xff\xe0fake-jpeg"


class Img404:
    status_code = 404
    headers = {}
    content = b""


downloads = []


def good_get(url, params=None, timeout=20, tries=3):
    downloads.append(url)
    return Img()


k.http_get = good_get


def imgs(n=4, tag="a"):
    return [{"path": f"adim1/{tag}{i}.jpg"} for i in range(n)]


def ad(subject="iPhone XS 64gb", price=30000, desc="Состояние хорошее. Продаю.", ad_id=1, images=None):
    d = {"ad_id": ad_id, "type": "sell", "company_ad": False, "price_byn": str(price), "price_usd": "9000", "subject": subject,
         "ad_link": f"https://www.kufar.by/item/{ad_id}",
         "ad_parameters": [{"p": "condition", "vl": "Б/у"}, {"p": "region", "vl": "Минск"}]}
    if desc:
        d["body_short"] = desc
    if images:
        d["images"] = images
    return d


def has_images(call):
    return any("inline_data" in p for p in call["json"]["contents"][0]["parts"])


def window_max(ts, width=60.0):
    """Больше всего запросов в любом окне шириной width секунд (окно начинается с очередного запроса)."""
    return max(sum(1 for u in ts if t <= u < t + width) for t in ts)


# ---------------------------------------------------------------------------------------------------------------------
# 1. Настройки по умолчанию и мусор в переменных окружения
# ---------------------------------------------------------------------------------------------------------------------
def child(env):
    full = {x: v for x, v in os.environ.items() if not x.startswith("GEMINI_") or x == "GEMINI_API_KEY"}
    full.update(TG_TOKEN="t", TG_CHAT_ID="1", **env)
    code = ("import sys; sys.argv=['kufar_bot.py']; sys.path.insert(0, %r); import kufar_bot as k; "
            "print(k.GEMINI_RPM, k.GEMINI_MIN_GAP_S, k.GEMINI_RETRIES, k.GEMINI_MAX_WAIT_S)") % str(tmp)
    p = subprocess.run([sys.executable, "-I", "-c", code], env=full, capture_output=True, text=True)
    return p.stdout.split() if p.returncode == 0 else p.stderr[-400:]


check("настройки по умолчанию: 10 запросов в минуту, пауза 6 с, 2 повтора после 503, ждать не дольше 60 с",
      child({}) == ["10", "6.0", "2", "60.0"], child({}))
check("пустые переменные (так их передаёт GitHub Actions) — значения по умолчанию",
      child({"GEMINI_RPM": "", "GEMINI_MIN_GAP_S": "", "GEMINI_RETRIES": "", "GEMINI_MAX_WAIT_S": ""}) == ["10", "6.0", "2", "60.0"])
check("мусор, nan и inf — значения по умолчанию",
      child({"GEMINI_RPM": "abc", "GEMINI_MIN_GAP_S": "nan", "GEMINI_RETRIES": "inf", "GEMINI_MAX_WAIT_S": "-inf"}) == ["10", "6.0", "2", "60.0"],
      child({"GEMINI_RPM": "abc", "GEMINI_MIN_GAP_S": "nan", "GEMINI_RETRIES": "inf", "GEMINI_MAX_WAIT_S": "-inf"}))
check("крайние значения зажимаются: RPM 0 -> 1, пауза 1e9 -> 60, повторы -3 -> 0, ожидание 9999 -> 600, RPM 7.9 -> 7",
      child({"GEMINI_RPM": "0", "GEMINI_MIN_GAP_S": "1e9", "GEMINI_RETRIES": "-3", "GEMINI_MAX_WAIT_S": "9999"}) == ["1", "60.0", "0", "600.0"]
      and child({"GEMINI_RPM": "7.9"})[0] == "7", child({"GEMINI_RPM": "0", "GEMINI_MIN_GAP_S": "1e9", "GEMINI_RETRIES": "-3", "GEMINI_MAX_WAIT_S": "9999"}))

# ---------------------------------------------------------------------------------------------------------------------
# 2. Ограничитель: пауза не меньше 6 с и не больше 10 запросов в любые 60 с
# ---------------------------------------------------------------------------------------------------------------------
setup()
t0 = clock.t
ts = []
for _ in range(25):
    k.llm_gate()
    ts.append(clock.t)
gaps = [b - a for a, b in zip(ts, ts[1:])]
check("ограничитель: первый запрос уходит сразу, без ожидания", ts[0] == t0 and clock.naps[0] > 0 and len(clock.naps) == 24, (ts[0] - t0, len(clock.naps)))
check("ограничитель: между 25 запросами подряд пауза не меньше 6 с", min(gaps) >= 6.0, min(gaps))
check("ограничитель: в любые 60 с не больше 10 запросов", window_max(ts) <= 10, window_max(ts))
check("ограничитель: время ожидания посчитано (для строки-итога в логе)", abs(k.LLM_STATS["waited"] - sum(clock.naps)) < 1e-6, k.LLM_STATS["waited"])

# только лимит в минуту (паузы между запросами нет): 10 запросов сразу, 11-й — когда из минутного окна уйдёт самый старый
setup()
k.GEMINI_MIN_GAP_S = 0
ts = []
for _ in range(25):
    k.llm_gate()
    ts.append(clock.t)
check("лимит в минуту: первые 10 запросов уходят сразу, 11-й — не раньше чем через 60 с после первого",
      ts[9] == ts[0] and ts[10] >= ts[0] + 60.0, (ts[9] - ts[0], ts[10] - ts[0]))
check("лимит в минуту: в любые 60 с не больше 10 (25 запросов подряд)", window_max(ts) <= 10, window_max(ts))
check("лимит в минуту: окно скользящее — 25 запросов растянулись минимум на 2 минуты", ts[-1] - ts[0] >= 120.0, ts[-1] - ts[0])
setup()
k.GEMINI_RPM = 3
ts = []
for _ in range(7):
    k.llm_gate()
    ts.append(clock.t)
check("лимит в минуту настраивается (GEMINI_RPM=3): не больше 3 запросов в окне", window_max(ts) <= 3, window_max(ts))

# страховка: если время «стоит» (часы сломаны), ограничитель не виснет и не засыпает бесконечно
setup()
k.llm_gate()
frozen_calls = []


def frozen_nap(sec):
    frozen_calls.append(sec)
    if len(frozen_calls) > 100:
        raise RuntimeError("ограничитель зациклился")


k._nap = frozen_nap
try:
    k.llm_gate()
    hung = False
except RuntimeError:
    hung = True
k._nap = clock.nap
check("часы стоят на месте: ограничитель выходит из ожидания (не больше ~2 минут суммарно), а не виснет", not hung and sum(frozen_calls) < 135, (hung, len(frozen_calls)))

# ограничитель переживает «новый запуск» (режим постоянного цикла): сброс нейросети его не обнуляет
setup()
k.llm_gate()
a = clock.t
k.llm_reset()
k.llm_gate()
check("llm_reset() ограничитель скорости не сбрасывает: пауза 6 с действует и между проходами", clock.t - a >= 6.0, clock.t - a)

# пауза считается от КОНЦА предыдущего запроса: долгий запрос не «съедает» паузу
srv = setup(latency=4.0)
for _ in range(3):
    k._llm_call("p", 100)
starts = srv.times()
check("пауза между вызовами (от конца предыдущего до начала следующего) не меньше 6 с, даже если запрос шёл 4 с",
      all(starts[i + 1] - (starts[i] + 4.0) >= 6.0 for i in range(2)), starts)

# ---------------------------------------------------------------------------------------------------------------------
# 3. Всплеск объявлений: с ограничителем 429 нет, без него — есть (поддельный сервер строг, как бесплатный уровень)
# ---------------------------------------------------------------------------------------------------------------------
srv = setup(latency=1.0, default=strict15)
facts = [k.analyze_ad(ad(f"iPhone XS {i}", 30000 + i, ad_id=1000 + i, images=imgs(2, f"b{i}"))) for i in range(25)]
check("25 новых объявлений подряд: все разобраны нейросетью, ни одного 429", srv.rejected == 0 and len(srv.calls) == 25 and all(f["llm"] for f in facts),
      (srv.rejected, len(srv.calls)))
check("25 новых объявлений: между запросами не меньше 6 с после конца предыдущего", all(srv.calls[i + 1]["t"] - (srv.calls[i]["t"] + 1.0) >= 6.0 for i in range(24)))
check("25 новых объявлений: в любые 60 с не больше 10 запросов", window_max(srv.times()) <= 10, window_max(srv.times()))
check("25 новых объявлений: один запрос на объявление (текст и 2 фото вместе)",
      all(has_images(c) and len(c["json"]["contents"][0]["parts"]) == 3 for c in srv.calls))

srv = setup(latency=1.0, default=strict15)
k.GEMINI_MIN_GAP_S, k.GEMINI_RPM = 0, 1000  # как было до исправления: без ограничителя
facts = [k.analyze_ad(ad(f"iPhone XS {i}", 30000 + i, ad_id=1100 + i, images=imgs(2, f"c{i}"))) for i in range(25)]
check("без ограничителя (как раньше) всплеск упирается в лимит: приходит 429", srv.rejected >= 1, srv.rejected)
check("…и бот не молотит дальше: после повторного 429 запросов больше нет (17 из 25 возможных)", srv.rejected == 2 and len(srv.calls) == 17 and k._LLM["off"], (srv.rejected, len(srv.calls)))
check("…остальные объявления обработаны без нейросети, ничего не потеряно", len(facts) == 25 and sum(1 for f in facts if f["llm"]) == 15
      and all(f["photo"]["status"] == "llm_off" for f in facts if not f["llm"]), sum(1 for f in facts if f["llm"]))

# ---------------------------------------------------------------------------------------------------------------------
# 4. 429: один повтор после ожидания, Retry-After и RetryInfo, повторный 429 — отключение до конца запуска
# ---------------------------------------------------------------------------------------------------------------------
def gap_before_retry(srv, lat=0.0):
    return srv.calls[1]["t"] - (srv.calls[0]["t"] + lat)


srv = setup([err429(header="17"), ok()], latency=0.5)
text = k._llm_call("p", 100, json_mode=True)
check("429 с Retry-After: ровно один повтор, и он успешен", len(srv.calls) == 2 and "iPhone" in text, len(srv.calls))
check("Retry-After соблюдён: до повтора прошло не меньше 17 с", gap_before_retry(srv, 0.5) >= 17.0, gap_before_retry(srv, 0.5))
check("после одного 429 нейросеть не отключена; счётчики: 429 — 1, повторов — 1",
      not k._LLM["off"] and k._LLM["n429"] == 1 and k.LLM_STATS["r429"] == 1 and k.LLM_STATS["retries"] == 1, (k._LLM, k.LLM_STATS))
check("в логе есть понятное сообщение про ожидание", any("429" in m and "повторяю один раз" in m for m in logs), logs)

srv = setup([err429(header=formatdate(real_time() + 20, usegmt=True)), ok()])
k._llm_call("p", 100)
check("Retry-After в виде даты (HTTP-date) тоже учитывается (~20 с)", 15.0 <= gap_before_retry(srv) <= 23.0, gap_before_retry(srv))

srv = setup([err429(delay="12s"), ok()])
k._llm_call("p", 100)
check("RetryInfo в теле ответа (без заголовка): ждём ~12 с, а не 30 по умолчанию", 12.0 <= gap_before_retry(srv) < 15.0, gap_before_retry(srv))

srv = setup([err429(header="3", delay="25s"), ok()])
k._llm_call("p", 100)
check("если указаны и Retry-After, и RetryInfo — берём большее (25 с)", gap_before_retry(srv) >= 25.0, gap_before_retry(srv))

srv = setup([err429(), ok()])
k._llm_call("p", 100)
check("429 без подсказки: ждём 30 секунд по умолчанию", 30.0 <= gap_before_retry(srv) < 32.0, gap_before_retry(srv))

for garbage in ("abc", "nan", "-5", "inf", ""):
    srv = setup([err429(header=garbage), ok()])
    k._llm_call("p", 100)
    check(f"мусор в Retry-After ({garbage!r}) не ломает ожидание: 30 с по умолчанию", 30.0 <= gap_before_retry(srv) < 32.0 and len(srv.calls) == 2, gap_before_retry(srv))

# повторный 429
srv = setup([err429(header="2")] * 50)
try:
    k._llm_call("p", 100)
    raised = None
except requests.HTTPError as e:
    raised = e
check("429, потом снова 429: бросается ошибка с кодом 429, запросов ровно 2", raised is not None and raised.response.status_code == 429 and len(srv.calls) == 2, len(srv.calls))
check("повторный 429: нейросеть отключена до конца запуска", k._LLM["off"] and k._LLM["n429"] == 2, k._LLM)
check("в логе сказано, что нейросеть отключена и объявления идут по правилам", any("отключена до конца запуска" in m and "по правилам" in m for m in logs), logs)
check("в логе названа исчерпанная квота (минутная) — по ней видно, в чём именно упёрлись",
      any("повторный 429" in m and MINUTE in m for m in logs) and MINUTE in str(raised), (logs, str(raised)))
n = len(srv.calls)
try:
    k._llm_call("p", 100)
    again = "ушёл запрос"
except k.LlmOff:
    again = "отказ"
check("после отключения запросов к Gemini нет вообще (даже напрямую через _llm_call)", again == "отказ" and len(srv.calls) == n, again)

# десять объявлений при постоянном 429
srv = setup([err429(header="2")] * 50)
res = [k.analyze_ad(ad(f"iPhone 8 {i}", 20000 + i, ad_id=2000 + i, images=imgs(3, f"d{i}"))) for i in range(10)]
check("10 объявлений при постоянном 429: всего 2 запроса к Gemini, а не десятки", len(srv.calls) == 2, len(srv.calls))
check("все 10 объявлений разобраны по правилам (без нейросети), статус «нейросеть недоступна»",
      len(res) == 10 and all(not f["llm"] and f["photo"]["status"] == "llm_off" and f["is_phone"] for f in res), [f["photo"]["status"] for f in res])
k._MARKET_REFRESHES["n"] = 99
text, okflag = k.process_ad(ad("iPhone 8 64gb", ad_id=2100, images=imgs(3, "e")))
check("сообщение по такому объявлению собирается и честно говорит про нейросеть",
      text and "iPhone 8" in text and "нейросеть недоступна" in text and len(srv.calls) == 2, (text or "")[:300])

# причина «фото не разобраны» называется верно, когда нейросеть отключена
srv = setup([err429(header="1")] * 5)
k.analyze_ad(ad(ad_id=2300, images=imgs(2, "x")))
f_nophoto = k.analyze_ad(ad(ad_id=2301))
k.PHOTOS_MAX = 0
f_off = k.analyze_ad(ad(ad_id=2302, images=imgs(2, "y")))
k.PHOTOS_MAX = 4
check("нейросеть отключена: у объявления без фото статус «нет фото», при PHOTOS_MAX=0 — «отключён», с фото — «нейросеть недоступна»",
      k._LLM["off"] and f_nophoto["photo"]["status"] == "no_photos" and f_off["photo"]["status"] == "off"
      and k.analyze_ad(ad(ad_id=2303, images=imgs(2, "z")))["photo"]["status"] == "llm_off", (f_nophoto["photo"], f_off["photo"]))

# 429 пришёл один раз, а потом — снова в другом объявлении: это повторный 429 за запуск
srv = setup([err429(header="2"), ok(PHOTO_REPLY), err429(header="2")] + [ok(PHOTO_REPLY)] * 20)
f1 = k.analyze_ad(ad("iPhone 8 a", ad_id=2200, images=imgs(1, "f1")))
f2 = k.analyze_ad(ad("iPhone 8 b", ad_id=2201, images=imgs(1, "f2")))
check("429 в начале и снова позже в том же запуске: нейросеть отключена, третье объявление без неё",
      f1["llm"] and not f2["llm"] and k._LLM["off"] and len(srv.calls) == 3, (f1["llm"], f2["llm"], len(srv.calls)))

# Retry-After слишком большой: не ждём, отключаем сразу (никакого сна)
for header in ("300", "61", "1e9"):
    srv = setup([err429(header=header), ok()])
    try:
        k._llm_call("p", 100)
        raised = None
    except requests.HTTPError as e:
        raised = e
    check(f"Retry-After {header} с (больше предела 60 с): один запрос, без сна, нейросеть отключена",
          raised is not None and len(srv.calls) == 1 and clock.naps == [] and k._LLM["off"], (len(srv.calls), clock.naps, k._LLM["off"]))
check("…и в логе объяснено почему", any("просит подождать" in m for m in logs), logs)

srv = setup([err429(header="60"), ok()])
k._llm_call("p", 100)
check("подсказка ровно 60 с (предел) ещё принимается: ждём 61 с и повторяем", len(srv.calls) == 2 and gap_before_retry(srv) >= 60.0, gap_before_retry(srv))
srv = setup([err429(header="20"), ok()])
k.GEMINI_MAX_WAIT_S = 10.0
try:
    k._llm_call("p", 100)
    raised = None
except requests.HTTPError as e:
    raised = e
check("GEMINI_MAX_WAIT_S=10, а Gemini просит 20: не ждём, нейросеть отключена", raised is not None and len(srv.calls) == 1 and k._LLM["off"])
srv = setup([err429(), ok()])
k.GEMINI_MAX_WAIT_S = 10.0
try:
    k._llm_call("p", 100)
    raised = None
except requests.HTTPError as e:
    raised = e
check("предел меньше ожидания по умолчанию (30 с): без подсказки тоже не ждём и отключаем", raised is not None and len(srv.calls) == 1 and k._LLM["off"])

# суточная квота: ждать бесполезно
srv = setup([err429(delay="33s", quota=DAY), ok()])
try:
    k._llm_call("p", 100)
    raised = None
except requests.HTTPError as e:
    raised = e
check("суточная квота (quotaId с PerDay): один запрос, без ожидания и повтора, нейросеть отключена до конца запуска",
      raised is not None and len(srv.calls) == 1 and clock.naps == [] and k._LLM["off"], (len(srv.calls), clock.naps))
check("в логе честно сказано: квота суточная, сбрасывается в полночь по тихоокеанскому времени, снижение скорости её не восстановит",
      any("суточная квота" in m and "полночь" in m and "не восстановит" in m for m in logs), logs)
check("…и названа сама квота (PerDay), она же — в тексте ошибки", any(DAY in m for m in logs) and DAY in str(raised), (logs, str(raised)))
srv = setup([err429(delay="5s", quota=MINUTE), ok()])
k._llm_call("p", 100)
check("минутная квота (PerMinute) — другое дело: ждём подсказку и повторяем, нейросеть остаётся включённой", len(srv.calls) == 2 and not k._LLM["off"])

# бюджет запуска: ждать больше, чем осталось до конца запуска, не будем
srv = setup([err429(header="30"), ok()])
k.RUN["deadline"] = real_time() + 5
try:
    k._llm_call("p", 100)
    raised = None
except requests.HTTPError as e:
    raised = e
check("до конца запуска осталось 5 с, а Gemini просит 30: не ждём, нейросеть отключена, запрос один",
      raised is not None and len(srv.calls) == 1 and clock.naps == [] and k._LLM["off"], (len(srv.calls), clock.naps))
srv = setup([err429(header="30"), ok()])
k.RUN["deadline"] = real_time() + 200
k._llm_call("p", 100)
check("времени достаточно (200 с): подождали и повторили", len(srv.calls) == 2 and gap_before_retry(srv) >= 30.0)

# ---------------------------------------------------------------------------------------------------------------------
# 5. 503 (и 500/502/504): отдельная логика — повторы с растущей паузой, Retry-After, предел повторов
# ---------------------------------------------------------------------------------------------------------------------
srv = setup([err5xx(), err5xx(), ok()])
text = k._llm_call("p", 100)
t = srv.times()
check("503, 503, затем успех: три запроса, нейросеть не отключена, 429-счётчик не тронут",
      len(srv.calls) == 3 and "iPhone" in text and not k._LLM["off"] and k._LLM["n429"] == 0 and k.LLM_STATS["r5xx"] == 2, (len(srv.calls), k.LLM_STATS))
check("паузы растут: 5 с, затем 10 с", 5.0 in clock.naps and 10.0 in clock.naps and clock.naps.index(10.0) > clock.naps.index(5.0)
      and t[1] - t[0] >= 5.0 and t[2] - t[1] >= 10.0, (clock.naps, t))
check("между всеми попытками пауза не меньше 6 с (ограничитель действует и на повторы)", t[1] - t[0] >= 6.0 and t[2] - t[1] >= 6.0, t)
check("в логе указано, какой это повтор", any("503" in m and "Повтор 1 из 2" in m for m in logs) and any("Повтор 2 из 2" in m for m in logs), logs)

srv = setup([err5xx()] * 10)
try:
    k._llm_call("p", 100)
    raised = None
except requests.HTTPError as e:
    raised = e
check("постоянный 503: 1 запрос + 2 повтора = 3, потом ошибка с кодом 503 (не десятки повторов)",
      raised is not None and raised.response.status_code == 503 and len(srv.calls) == 3 and k.LLM_STATS["retries"] == 2, len(srv.calls))

for code in (500, 502, 504):
    srv = setup([err5xx(code), ok()])
    k._llm_call("p", 100)
    check(f"{code} тоже временная ошибка: один повтор и успех", len(srv.calls) == 2)

srv = setup([err5xx(header="7"), ok()])
k._llm_call("p", 100)
check("503 с Retry-After: 7 — ждём именно столько (а не 5 по умолчанию)", 7.0 in clock.naps and gap_before_retry(srv) >= 7.0, (clock.naps, gap_before_retry(srv)))

srv = setup([err5xx(header="500"), ok()])
try:
    k._llm_call("p", 100)
    raised = None
except requests.HTTPError as e:
    raised = e
check("503 с Retry-After: 500 (больше предела): без повтора и без сна, нейросеть при этом не отключается сама",
      raised is not None and len(srv.calls) == 1 and clock.naps == [] and not k._LLM["off"], (len(srv.calls), clock.naps))

k.RUN["deadline"] = 0.0
srv = setup([err5xx(), ok()])
k.RUN["deadline"] = real_time() + 2
try:
    k._llm_call("p", 100)
    raised = None
except requests.HTTPError:
    raised = True
check("до конца запуска 2 с, а пауза 5 с: повтора нет", raised and len(srv.calls) == 1 and clock.naps == [], (len(srv.calls), clock.naps))

srv = setup([err5xx(), ok()])
k.GEMINI_RETRIES = 0
try:
    k._llm_call("p", 100)
    raised = None
except requests.HTTPError:
    raised = True
check("GEMINI_RETRIES=0: повторов нет", raised and len(srv.calls) == 1)

# что НЕ повторяется
for name, item in (("400", Resp(400, {"error": {"code": 400, "message": "bad"}})), ("401", Resp(401, {"error": {"code": 401}})),
                   ("403", Resp(403, {"error": {"code": 403}})), ("обрыв связи", requests.ConnectionError("нет связи")),
                   ("таймаут", requests.Timeout("долго"))):
    srv = setup([item, ok()])
    try:
        k._llm_call("p", 100)
        raised = None
    except Exception as e:
        raised = e
    check(f"{name}: не повторяется (1 запрос), ошибка пробрасывается", raised is not None and len(srv.calls) == 1 and clock.naps == [], (len(srv.calls), raised))

# 503 через llm_json: две неудачи подряд — нейросеть отключается, всего 6 запросов (не больше)
srv = setup([err5xx()] * 30)
res = [k.analyze_ad(ad(f"iPhone 7 {i}", 15000 + i, ad_id=3000 + i, images=imgs(2, f"g{i}"))) for i in range(6)]
check("шторм 503 на 6 объявлениях: два объявления по 3 попытки, потом нейросеть отключена — всего 6 запросов, не 6×3",
      len(srv.calls) == 6 and k._LLM["off"] and all(not f["llm"] for f in res), (len(srv.calls), k._LLM))
check("шторм 503: второго «текстового» запроса после неудачи фото-запроса нет (все 6 запросов — с картинками)", all(has_images(c) for c in srv.calls))
check("шторм 503: все объявления разбираются по правилам и сообщают о недоступности AI", all(f["is_phone"] for f in res) and all(f["photo"]["status"] == "llm_off" for f in res))

# 503 один раз и дальше всё хорошо: нейросеть работает для остальных
srv = setup([err5xx(), err5xx(), err5xx(), ok(PHOTO_REPLY)])
f1 = k.analyze_ad(ad("iPhone 7 a", ad_id=3100, images=imgs(2, "h1")))
f2 = k.analyze_ad(ad("iPhone 7 b", ad_id=3101, images=imgs(2, "h2")))
check("503 на одном объявлении не отключает нейросеть: следующее объявление разобрано", not f1["llm"] and f2["llm"] and not k._LLM["off"] and len(srv.calls) == 4, (f1["llm"], f2["llm"], len(srv.calls)))

# ---------------------------------------------------------------------------------------------------------------------
# 6. Один запрос на объявление: текст и фото вместе; второй (только текст) — только если дело в самом запросе
# ---------------------------------------------------------------------------------------------------------------------
srv = setup(default=lambda s: ok(PHOTO_REPLY))
f = k.analyze_ad(ad(ad_id=4000, images=imgs(5, "i")))
parts = srv.calls[0]["json"]["contents"][0]["parts"]
check("нормально: один запрос, в нём текст и 4 фото (PHOTOS_MAX), таймаут 60 с",
      len(srv.calls) == 1 and "text" in parts[0] and sum(1 for p in parts if "inline_data" in p) == 4 and srv.calls[0]["timeout"] == 60, (len(srv.calls), len(parts)))
check("нормально: фото разобраны (analyzed, 4 из 5)", f["photo"]["status"] == "analyzed" and f["photo"]["n"] == 4 and f["photo"]["total"] == 5, f["photo"])

srv = setup()
f = k.analyze_ad(ad(ad_id=4001))
check("нет фото: API не вызывается, используется разбор по правилам", len(srv.calls) == 0 and f["photo"]["status"] == "no_photos" and not f["llm"])

srv = setup([err429(delay="30s", quota=DAY), ok()])
f = k.analyze_ad(ad(ad_id=4002, images=imgs(2, "j")))
check("запрос с фото -> суточный 429: второго запроса «только текст» НЕТ, объявление идёт без нейросети",
      len(srv.calls) == 1 and not f["llm"] and f["photo"]["status"] == "llm_off" and k._LLM["off"], (len(srv.calls), f["photo"]))

srv = setup([err5xx()] * 3 + [ok()])
f = k.analyze_ad(ad(ad_id=4003, images=imgs(2, "k")))
check("запрос с фото -> 503 на всех попытках: текстового запроса следом нет (3 запроса, все с фото)",
      len(srv.calls) == 3 and all(has_images(c) for c in srv.calls) and not f["llm"] and f["photo"]["status"] == "llm_off", (len(srv.calls), f["photo"]))

srv = setup([requests.ConnectionError("нет связи"), ok()])
f = k.analyze_ad(ad(ad_id=4004, images=imgs(2, "l")))
check("запрос с фото -> обрыв связи: второго запроса нет", len(srv.calls) == 1 and not f["llm"] and k._LLM["last"] == "net", (len(srv.calls), k._LLM["last"]))

srv = setup([Resp(400, {"error": {"code": 400, "message": "картинка не принята"}}), ok()])
f = k.analyze_ad(ad(ad_id=4005, images=imgs(2, "m")))
check("запрос с фото -> HTTP 400: повторный текстовый запрос не тратит квоту, объявление разбирается по правилам",
      len(srv.calls) == 1 and has_images(srv.calls[0]) and not f["llm"] and f["photo"]["status"] == "error", (len(srv.calls), f["photo"]))

srv = setup([ok_text("это не JSON"), ok()])
f = k.analyze_ad(ad(ad_id=4006, images=imgs(2, "n")))
check("запрос с фото -> нечитаемый ответ: нет второго бесполезного запроса", len(srv.calls) == 1 and not f["llm"] and f["photo"]["status"] == "error")

srv = setup([Resp(400, {"error": {"code": 400}}), ok()])
f = k.analyze_ad(ad(ad_id=4007, images=imgs(2, "o")))
check("HTTP 400: один запрос, объявление не теряется и сеть не объявляется выключенной",
      len(srv.calls) == 1 and not f["llm"] and not k._LLM["off"] and f["is_phone"], (len(srv.calls), k._LLM))

# Claude (запасной путь) идёт через тот же ограничитель и ту же обработку ошибок
srv = setup([Resp(529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}})],
            default=lambda s: Resp(200, {"content": [{"text": json.dumps(OK_REPLY)}]}))
k.GEMINI_KEY, k.ANTHROPIC_KEY = "", "ak"
k._llm_call("p", 100)
k._llm_call("p", 100)
t = srv.times()
check("Claude: 529 («перегружен») повторяется, между всеми запросами пауза не меньше 6 с, адрес — api.anthropic.com",
      len(srv.calls) == 3 and all("api.anthropic.com" in c["url"] for c in srv.calls) and all(t[i + 1] - t[i] >= 6.0 for i in range(2)), (len(srv.calls), t))

# ---------------------------------------------------------------------------------------------------------------------
# 7. Кеш разборов
# ---------------------------------------------------------------------------------------------------------------------
srv = setup(default=lambda s: ok(PHOTO_REPLY))
downloads.clear()
a1 = ad(ad_id=5000, images=imgs(4, "p"))
f1 = k.analyze_ad(a1)
n_down = len(downloads)
f2 = k.analyze_ad(a1)
check("кеш: то же объявление второй раз — без запроса к Gemini и без скачивания фото",
      len(srv.calls) == 1 and len(downloads) == n_down and k.LLM_STATS["cached"] == 1 and n_down == 4, (len(srv.calls), len(downloads), k.LLM_STATS["cached"]))
check("кеш: результат тот же (сводка, статус фото, число фото)",
      f2["llm"] and f2["summary"] == f1["summary"] and f2["photo"]["status"] == "analyzed" and f2["photo"]["n"] == 4 and f2["photo"]["total"] == 4, (f1["photo"], f2["photo"]))
data = k.llm_analyze(a1, k.rule_facts(a1))
data["summary"] = "ИСПОРЧЕНО"
data["defects"].append({"type": "screen", "note": "x"})
data2 = k.llm_analyze(a1, k.rule_facts(a1))
check("кеш отдаёт копии: правка результата не портит сохранённое", data2["photos"]["findings"] == [], data2)
k.llm_reset()
f3 = k.analyze_ad(a1)
check("кеш не сбрасывается новым запуском (режим постоянного цикла)", len(srv.calls) == 1 and f3["llm"])
k._LLM["off"] = True
f4 = k.analyze_ad(a1)
f5 = k.analyze_ad(ad(ad_id=5001, images=imgs(4, "q")))
check("нейросеть отключена: объявление из кеша всё равно разобрано, новое — по правилам", f4["llm"] and not f5["llm"] and f5["photo"]["status"] == "llm_off" and len(srv.calls) == 1, (f4["llm"], f5["llm"], f5["photo"]["status"], len(srv.calls)))

srv = setup(default=lambda s: ok(PHOTO_REPLY))
base = ad(ad_id=5100, images=imgs(4, "r"))
k.analyze_ad(base)
changes = {"цена изменилась": dict(base, price_byn="25000"), "описание изменилось": dict(base, body_short="Совсем другое описание"),
           "название изменилось": dict(base, subject="iPhone XS 256gb"), "фото другие": dict(base, images=imgs(4, "zz")),
           "фото стало меньше": dict(base, images=imgs(2, "r")), "другой id (то же содержимое)": dict(base, ad_id=5101)}
for name, changed in changes.items():
    before = len(srv.calls)
    k.analyze_ad(changed)
    check(f"кеш: {name} — разбор делается заново (новый запрос)", len(srv.calls) == before + 1, (name, before, len(srv.calls)))

# ошибки не кешируются
srv = setup([err5xx()] * 3 + [ok(PHOTO_REPLY)])
a2 = ad(ad_id=5200, images=imgs(2, "s"))
f1 = k.analyze_ad(a2)
f2 = k.analyze_ad(a2)
f3 = k.analyze_ad(a2)
check("кеш: неудачный разбор не запоминается; следующий разбор успешен и запоминается (всего 4 запроса, третий вызов — из кеша)",
      not f1["llm"] and f2["llm"] and f3["llm"] and len(srv.calls) == 4 and k.LLM_STATS["cached"] == 1, (len(srv.calls), k.LLM_STATS))

# фото не скачались: результат «только текст» не запоминаем, чтобы при повторе фото всё же посмотреть
srv = setup(default=lambda s: ok(PHOTO_REPLY if s.calls and has_images(s.calls[-1]) else OK_REPLY))
k.http_get = lambda url, params=None, timeout=20, tries=3: Img404()
a3 = ad(ad_id=5300, images=imgs(2, "t"))
f1 = k.analyze_ad(a3)
k.http_get = good_get
k.RUN["img_fails"] = 0
f2 = k.analyze_ad(a3)
check("кеш: если фото не скачались, запрос не кешируется — при повторе фото анализируются",
      f1["photo"]["status"] == "no_download" and f2["photo"]["status"] == "analyzed" and len(srv.calls) == 1, (f1["photo"]["status"], f2["photo"]["status"], len(srv.calls)))

# вытеснение: не больше AI_CACHE_MAX разборов
srv = setup()
k.AI_CACHE_MAX = 3
for i in range(5):
    k.analyze_ad(ad(f"iPhone 8 {i}", ad_id=5400 + i, images=imgs(1, f"cache{i}")))
check("кеш ограничен по размеру (3): самые старые вытеснены, свежие на месте", list(k.AI_CACHE) == ["5402", "5403", "5404"], list(k.AI_CACHE))
k.AI_CACHE_MAX = 200

# ---------------------------------------------------------------------------------------------------------------------
# 8. Целый проход cycle(): мониторинг не ломается ни при 429, ни при шторме 503, ни при очереди объявлений
# ---------------------------------------------------------------------------------------------------------------------
MODELS_FOR_ADS = ["7", "8", "X", "XS", "XR", "11"]
PRE_HISTORY = {"900001": {"t": int(real_time()) - 3600, "m": "iPhone 8", "p": 100, "c": "Б/у", "s": "s", "l": "l", "ok": True}}


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def make_ads(n, base_id=7000):
    """n свежих объявлений (опубликованы минуту назад) + опорное объявление 45-минутной давности с меньшим номером:
    по нему бот подтверждает, что это новые публикации, а не поднятые старые (см. originality)."""
    now = time.time()
    out = []
    for i in range(n):
        a = ad(f"iPhone {MODELS_FOR_ADS[i % 6]} 64gb", 30000 + 100 * i, f"Описание {i}. Всё работает.", ad_id=base_id + i, images=imgs(3, f"u{base_id}_{i}"))
        a["list_time"] = iso(now - 60)
        out.append(a)
    ref = ad("Чехол для iPhone", 1000, "", ad_id=100)
    ref["list_time"] = iso(now - 2700)
    return out + [ref]


def run_cycle(ads, srv, seen=None, reset_state=True):
    sent = []
    k.tg_send = lambda text, **kw: sent.append(text)
    k.fetch = lambda q, size=30: ads
    k.QUERIES, k.EXTRA_QUERIES, k.MARKET_MAX_REFRESH = ["iphone"], [], 0
    if reset_state:
        k.STATE.update(market={}, baseline=["iphone"], pending={}, notice=k.NOTICE_VERSION)
        k.mdb_reset()  # чистый старт: и журнал отправок в базе рынка
        k.HISTORY.clear()
        k.HISTORY.update(json.loads(json.dumps(PRE_HISTORY)))
    k.SEEN_FILE = tmp / "seen_cycle.json"
    seen = k.Seen() if seen is None else seen
    res = k.cycle(seen, False)
    return sent, seen, res


def photo_note(text):
    return "нейросеть недоступна" in text


# 8.1. Gemini всё время отвечает 429
srv = setup([err429(header="2")] * 50)
sent, seen, res = run_cycle(make_ads(6), srv)
check("проход при постоянном 429: ВСЕ 6 объявлений дошли до Telegram", len(sent) == 6 and seen == set(range(7000, 7006)) and res == (1, 1), (len(sent), sorted(seen)))
check("проход при постоянном 429: к Gemini всего 2 запроса (первый и один повтор), дальше нейросеть выключена", len(srv.calls) == 2 and k._LLM["off"], len(srv.calls))
check("проход при постоянном 429: сообщения полноценные (модель, оценка) и честно говорят про нейросеть",
      all("iPhone" in s and "📊" in s and photo_note(s) for s in sent), [s[:80] for s in sent if not photo_note(s)])
k.llm_log_summary()
check("итог в логе: запросов 2, ответов 429: 2, нейросеть отключена до конца запуска",
      any("Нейросеть за запуск: запросов 2" in m and "ответов 429: 2" in m and "отключена до конца запуска" in m for m in logs), [m for m in logs if "за запуск" in m])
data = json.loads(k.SEEN_FILE.read_text())
check("seen.json: отметки времени сохраняются вместе с теми же полями состояния; кеш нейросети не записывается",
      set(data) == {"seen", "history", "market", "baseline", "notice", "pending", "marks"}
      and {int(x) for x in data["seen"]} == set(range(7000, 7006))
      and all(isinstance(t, int) for t in data["seen"].values())
      and "900001" in data["history"], sorted(data))
check("seen.json: все 6 объявлений записаны в историю, очередь повторов пуста", all(str(7000 + i) in data["history"] for i in range(6)) and data["pending"] == {}, data["pending"])

# 8.2. шторм 503
srv = setup(default=lambda s: err5xx())
sent, seen, res = run_cycle(make_ads(6), srv)
check("проход при штормe 503: все 6 объявлений доставлены; запросов 6 (2 объявления × 3 попытки), дальше нейросеть выключена",
      len(sent) == 6 and len(srv.calls) == 6 and k._LLM["off"] and seen == set(range(7000, 7006)), (len(sent), len(srv.calls)))

# 8.3. всё хорошо: запросы идут не чаще, чем разрешено
srv = setup(latency=1.0)
sent, seen, res = run_cycle(make_ads(6), srv)
t = srv.times()
check("проход без сбоев: 6 запросов на 6 объявлений, паузы между ними не меньше 6 с", len(srv.calls) == 6 and len(sent) == 6 and all(t[i + 1] - (t[i] + 1.0) >= 6.0 for i in range(5)), (len(srv.calls), t))
check("проход без сбоев: в сообщениях нет пометки «нейросеть недоступна»", not any(photo_note(s) for s in sent))
check("проход без сбоев: разборы запомнены в памяти (кеш), а в seen.json их нет", len(k.AI_CACHE) == 6 and "ai" not in json.loads(k.SEEN_FILE.read_text()))

# 8.4. очередь: ограничитель замедляет разбор, а бюджет запуска не пропускает ничего — остаток уходит в очередь и доезжает со следующим запуском
srv = setup(latency=1.0)
WALL0, CLOCK0 = real_time(), clock.t
time.time = lambda: WALL0 + (clock.t - CLOCK0)
k.RUN_BUDGET_S = 60
ads12 = make_ads(12, base_id=7200)
sent1, seen, res = run_cycle(ads12, srv)
queued = sorted(int(x) for x in k.STATE["pending"])
check("бюджет запуска 60 с при паузе 6 с: часть объявлений успели, остальные — в очереди повторов, ничего не потеряно",
      0 < len(sent1) < 12 and len(sent1) + len(queued) == 12 and set(queued).isdisjoint(seen), (len(sent1), queued))
check("…все отправленные — с разбором нейросетью, не более 10 запросов в минуту", all(not photo_note(s) for s in sent1) and window_max(srv.times()) <= 10)
clock.t += 300  # следующий запуск cron-job.org через 5 минут: новый процесс (здесь — сброс нейросети через cycle), очередь разбирается первой
sent2, seen, res = run_cycle(ads12, srv, seen=seen, reset_state=False)
check("следующий запуск через 5 минут: остаток очереди уже старше 5 минут — НЕ отправлен, очередь пуста, повторов нет",
      sent2 == [] and k.STATE["pending"] == {} and set(queued).isdisjoint(seen) and len(sent1) + len(queued) == 12,
      (len(sent1), len(sent2), k.STATE["pending"].keys()))
time.time = real_time
k.RUN_BUDGET_S = 200

# 8.5. то же объявление повторно в том же процессе (режим постоянного цикла): запроса нет
srv = setup()
ads2 = make_ads(2, base_id=7400)
sent, seen, res = run_cycle(ads2, srv)
n_calls = len(srv.calls)
seen.clear()
k.mdb_reset()  # и журнал отправок в базе: проверяем именно кеш разборов нейросети, а не защиту от повторов
sent_again, seen, res = run_cycle(ads2, srv, seen=seen, reset_state=False)
check("повторный проход по тем же объявлениям в одном процессе: новых запросов к Gemini нет (кеш), сообщения те же",
      n_calls == 2 and len(srv.calls) == 2 and len(sent_again) == 2 and k.LLM_STATS["cached"] == 2, (n_calls, len(srv.calls), k.LLM_STATS))

# ---------------------------------------------------------------------------------------------------------------------
# 9. Недельный отчёт идёт через тот же ограничитель и переживает 429
# ---------------------------------------------------------------------------------------------------------------------
NOW = real_time()
k.HISTORY.clear()
for i, price in enumerate((140, 150, 155, 160, 90)):
    k.HISTORY[str(i)] = {"t": int(NOW) - 86400, "m": "iPhone 5s", "p": price, "c": "Б/у", "s": "s", "l": "l", "ok": True}
sent = []
k.tg_send = lambda text, **kw: sent.append(text)
srv = setup([err429(header="2")] * 5)
k.send_report()
check("отчёт при 429: ушёл без выводов нейросети, запросов к Gemini 2 (первый и повтор)", len(sent) == 1 and "Выводы нейросети" not in sent[0] and len(srv.calls) == 2 and k._LLM["off"], (len(sent), len(srv.calls)))
sent.clear()
srv = setup()
k.send_report()
check("отчёт без сбоев: выводы нейросети добавлены, один запрос", len(sent) == 1 and "Выводы нейросети" in sent[0] and len(srv.calls) == 1)
sent.clear()
srv = setup()
k._LLM["off"] = True
k.send_report()
check("отчёт, когда нейросеть уже отключена: запросов нет, отчёт ушёл без выводов", len(sent) == 1 and "Выводы нейросети" not in sent[0] and len(srv.calls) == 0)

# ---------------------------------------------------------------------------------------------------------------------
# 10. Разбор ответов-ошибок (Retry-After, RetryInfo, суточная квота) на мусоре
# ---------------------------------------------------------------------------------------------------------------------
def info(status=429, body=None, headers=None):
    return k._error_info(Resp(status, body, headers))


MSG = "You exceeded your current quota. * Quota exceeded for metric: generate_content_free_tier_requests, limit: 15\nPlease retry in 12.5s."
check("Retry-After: число и дробное число", info(headers={"Retry-After": "30"})[1] == 30.0 and info(headers={"retry-after": "1.5"})[1] == 1.5)
d = info(headers={"Retry-After": formatdate(real_time() + 20, usegmt=True)})[1]
check("Retry-After: дата в формате HTTP", d is not None and 15.0 <= d <= 21.0, d)
check("Retry-After: мусор, nan, inf, минус, пусто, дата из прошлого — игнорируются/обнуляются",
      all(info(headers={"Retry-After": x})[1] is None for x in ("abc", "nan", "inf", "-1", "", "завтра"))
      and info(headers={"Retry-After": formatdate(real_time() - 100, usegmt=True)})[1] == 0.0)
check("RetryInfo: «33s», «33.5s», «1s»", k._error_info(err429(delay="33s"))[1] == 33.0 and k._error_info(err429(delay="33.5s"))[1] == 33.5
      and k._error_info(err429(delay="1s"))[1] == 1.0)
check("RetryInfo: мусор («скоро», «5 минут») игнорируется", k._error_info(err429(delay="скоро"))[1] is None and k._error_info(err429(delay="5m"))[1] is None)
check("подсказка из текста ошибки («Please retry in 12.5s»), если RetryInfo нет",
      info(body={"error": {"message": MSG}})[1] == 12.5 and info(body={"error": {"message": "Please retry in 4s."}})[1] == 4.0)
check("указаны и заголовок, и тело — берётся большее", info(body={"error": {"details": [{"retryDelay": "33s"}]}}, headers={"Retry-After": "5"})[1] == 33.0)
check("суточная квота: PerDay в quotaId (в любом написании)",
      k._error_info(err429(quota=DAY))[0] is True and k._error_info(err429(quota="generate_requests_per_day_per_project"))[0] is True
      and k._error_info(err429(quota="GenerateRequestsPerMinutePerProjectPerModel-FreeTier"))[0] is False)
check("суточная квота: фраза «per day» в тексте ошибки", info(body={"error": {"message": "Quota exceeded: 50 requests per day"}})[0] is True)
check("ответ не JSON / список / строка вместо объекта: разбор молча даёт «ничего не известно»",
      info(body=ValueError("не json")) == (False, None, "", "") and info(body=[1, 2]) == (False, None, "", "")
      and info(body={"error": "строка"}) == (False, None, "", "") and info(body=None) == (False, None, "", "")
      and info(body={"error": {"details": "x"}}) == (False, None, "", ""))
d_all, h_all, m_all, q_all = k._error_info(err429(delay="33s", quota=DAY))
check("в тексте ошибки — только первая фраза Google (без ссылок и справки), названия исчерпанных квот — отдельно",
      m_all == "You exceeded your current quota, please check your plan and billing details." and q_all == DAY, (m_all, q_all))
check("ответ без заголовков (None) не ломает разбор", k._error_info(Resp(429, None, None))[1] is None)

# ---------------------------------------------------------------------------------------------------------------------
print("итого ошибок (ограничитель Gemini):", bad)
if bad:
    print("лог последнего сценария:", *logs[-12:], sep="\n  ")
sys.exit(1 if bad else 0)
