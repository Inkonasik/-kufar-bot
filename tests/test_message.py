"""Тесты сообщения в Telegram (без сети, без отправки)."""
import os
import re
import sys
import tempfile
import time
from pathlib import Path

os.environ.update(TG_TOKEN="t", TG_CHAT_ID="1")
for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "MODELS", "REPAIR_COSTS", "HOME_REGION"):
    os.environ.pop(key, None)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fresh_dir  # noqa: E402
tmp = fresh_dir()
sys.path.insert(0, str(tmp))
import kufar_bot as k  # noqa: E402

VERBOSE = "-v" in sys.argv
bad = 0


def check(name, cond, extra=""):
    global bad
    if not cond:
        print("FAIL", name, extra)
        bad += 1


def ad(subject, price=65000, desc="", cond="Б/у", ad_id=9001, region="Минск", company=False):
    d = {"ad_id": ad_id, "type": "sell", "company_ad": company, "price_byn": str(price), "price_usd": str(int(price * 0.3)),
         "subject": subject, "ad_link": f"https://www.kufar.by/item/{ad_id}",
         "ad_parameters": [{"p": "condition", "vl": cond}, {"p": "region", "vl": region}, {"p": "area", "vl": "Центральный"}]}
    if desc:
        d["body_short"] = desc
    return d


def put(key, items, age=0):
    k.STATE["market"][key] = {"t": int(time.time() - age), "items": items}


items = [[100 + i, 600 + i * 10, 64, 0, 1 if i % 2 == 0 else 3, 0] for i in range(20)]
items += [[200 + i, 330 + i * 15, 64, k.F_DEF, 1, 0] for i in range(4)]
put("iPhone 11", items)
put("iPhone 8", [[500 + i, 300 + i * 10, 64, 0, 1, 0] for i in range(3)])
put("iPhone SE", [[600 + i, 300 + i * 10, 64, 0, 1, 2020] for i in range(6)] + [[700 + i, 450 + i * 10, 64, 0, 1, 2022] for i in range(6)])

CASES = {
    "хорошая цена": ad("iPhone 11 64gb", 62000, "Состояние идеал, акб 91%, полный комплект: коробка, зарядка. Торг. Face ID работает. icloud чистый."),
    "дорого": ad("iPhone 11 64gb", 90000, "Без торга."),
    "без цены": ad("iPhone 11 64gb", 0, "Цена договорная"),
    "мало аналогов": ad("iPhone 8 64gb", 28000),
    "нет рынка": ad("iPhone 7 32gb", 15000),
    "SE без поколения": ad("iPhone SE 64gb", 30000),
    "дефект, ремонт неизвестен": ad("iPhone 11 64gb", 40000, "Разбит экран, остальное работает"),
    "запчасти": ad("iPhone 11 на запчасти", 12000, "Не включается, был в воде"),
    "экранирование": ad("iPhone 11 <b>&</b> 64gb", 62000, "Продам <script>alert(1)</script> & всё"),
    "магазин": ad("iPhone 11 64gb", 70000, company=True),
}
ALLOWED = re.compile(r"</?b>")
k._MARKET_REFRESHES["n"] = 99  # сеть не трогаем
for name, a in CASES.items():
    f = k.rule_facts(a)
    ap = k.appraise(a, f)
    msg = k.build_message(a, f, ap)
    if VERBOSE:
        print("=" * 70, name, f"[{ap['status']}] {len(msg)} симв.")
        print(msg)
    check(f"{name}: длина", len(msg) <= 4096, len(msg))
    stripped = ALLOWED.sub("", msg)
    check(f"{name}: нет «сырых» <>", "<" not in stripped and ">" not in stripped.replace("&gt;", ""), stripped[:200])
    check(f"{name}: теги <b> парные", msg.count("<b>") == msg.count("</b>"))
    check(f"{name}: ссылка на объявление", f"https://www.kufar.by/item/{a['ad_id']}" in msg)
    check(f"{name}: есть цена или пометка", "BYN" in msg or "договорная" in msg or "не указана" in msg)
    check(f"{name}: блок 📱💰📍🔧⚠️", all(e in msg for e in ("📱", "💰", "📍", "🔧", "⚠️")))
    if ap["comps"] and ap["status"] == "ok":
        check(f"{name}: пометка «не сделок»", "не сделок" in msg)
    if ap["status"] == "ok":
        check(f"{name}: есть 📊, 💵 (или «для справки») и 🤝", all(e in msg for e in ("📊", "🤝")) and ("💵" in msg), msg)
        check(f"{name}: 🎯 только при сравнении с такими же", ("🎯" in msg) == bool(ap.get("target")), ap.get("target"))
        check(f"{name}: ссылки на аналоги реальные", all(f"/item/{c[0]}" in msg for c in ap["comps"]))
    if ap["status"] in ("few", "no_market", "se_gen", "no_model"):
        check(f"{name}: нет вердикта по цене", not any(v in msg for v in ("ОЧЕНЬ ВЫГОДНО", "<b>ВЫГОДНО", "ДОРОГО", "НЕВЫГОДНО")))
    check(f"{name}: нет общей фразы «НЕДОСТАТОЧНО ДАННЫХ»", "НЕДОСТАТОЧНО ДАННЫХ" not in msg)
    check(f"{name}: ровно один вывод в конце оценки", msg.count("✅ <b>Вывод для перепродажи:</b>") == 1, msg)
    concl = [ln for ln in msg.split("\n") if ln.startswith("✅")][0]
    phrases = ("Покупать по текущей цене", "Покупать только после торга", "Не покупать для перепродажи", "Пока недостаточно данных для решения")
    check(f"{name}: вывод — одна из четырёх фраз", sum(ph in concl for ph in phrases) == 1, concl)
    check(f"{name}: вывод последний в блоке оценки (после него только аналоги и ссылка)",
          msg.index(concl) > msg.rfind("🤝") and (msg.rfind("💵") < msg.index(concl) or "💵" not in msg), msg)
    check(f"{name}: нет обещаний прибыли", "гарантирован" not in msg.replace("Не гарантия", "") and "точно заработ" not in msg)

m = k.build_message(CASES["экранирование"], k.rule_facts(CASES["экранирование"]), k.appraise(CASES["экранирование"], k.rule_facts(CASES["экранирование"])))
check("экранирование заголовка", "&lt;b&gt;&amp;&lt;/b&gt;" in m and "iPhone 11 <b>&</b>" not in m)
f = k.rule_facts(CASES["экранирование"])
f["summary"] = "Продам <script>alert(1)</script> & всё"
f["risks"] = ["<i>риск</i>"]
m = k.build_message(CASES["экранирование"], f, k.appraise(CASES["экранирование"], f))
check("экранирование сводки и рисков", "&lt;script&gt;" in m and "<script>" not in m and "&lt;i&gt;" in m and "<i>" not in m)
for n, want in ((1, "1 активное объявление"), (2, "2 активных объявления"), (5, "5 активных объявлений"), (11, "11 активных объявлений"),
                (21, "21 активное объявление"), (22, "22 активных объявления"), (112, "112 активных объявлений")):
    check(f"склонение {n}", k.n_ads(n) == want, k.n_ads(n))
for n, want in ((1, "1 объявление"), (2, "2 объявления"), (4, "4 объявления"), (5, "5 объявлений"), (11, "11 объявлений"), (12, "12 объявлений"),
                (21, "21 объявление"), (34, "34 объявления"), (35, "35 объявлений"), (111, "111 объявлений")):
    check(f"ads_nom {n}", k.ads_nom(n) == want, k.ads_nom(n))
for n, want in ((1, "1 объявления"), (2, "2 объявлений"), (21, "21 объявления"), (34, "34 объявлений")):
    check(f"ads_gen {n}", k.ads_gen(n) == want, k.ads_gen(n))
check("склонение сопоставимых", k.n_ads(3, "сопоставимых") == "3 сопоставимых объявления" and k.n_ads(1, "сопоставимых") == "1 сопоставимое объявление")
f = k.rule_facts(CASES["запчасти"])
m = k.build_message(CASES["запчасти"], f, k.appraise(CASES["запчасти"], f))
check("запчасти: «не покупать» и пометка", "Не покупать для перепродажи" in m and "на запчасти" in m, m)
check("запчасти: лимит покупки не считается, цифры только «для справки»", "Для справки" in m and "Макс. цена покупки" not in m, m)
f = k.rule_facts(CASES["дефект, ремонт неизвестен"])
m = k.build_message(CASES["дефект, ремонт неизвестен"], f, k.appraise(CASES["дефект, ремонт неизвестен"], f))
check("дефект: ремонт неизвестен — показана формула и предварительный лимит", "Лимит предварительный" in m and "цена не известна" in m, m)
check("дефект: прибыль названа «до учёта ремонта»", "Прибыль до учёта ремонта" in m, m)
check("дефект: не выдуманы расходы на ремонт", "ремонт 0" not in m and "(ремонт:" not in m)
check("дефект: конкретно, чего не хватает", "у них не подтверждены" in m and "оценка основана на общем рынке и может быть неточной" in m, m)
check("дефект: счётчики раздельно", "Аналоги: найдено 10 объявлений" in m and "С таким же дефектом (экран) в заголовках аналогов: 0" in m, m)
# --- пример из задачи: iPhone XS 64 ГБ, 250 BYN, аккумулятор 74%, 34 аналога ---
put("iPhone XS", [[500 + i, 330 + i * 7, 64, 0, 1 if i < 16 else 5 if i < 22 else 3 if i < 28 else 4, 0] for i in range(34)])
axs = ad("iPhone XS 64gb", 25000, "Состояние хорошее, акб 74%.", region="Гомельская область", ad_id=9100)
fxs = k.rule_facts(axs)
k.REPAIR_COSTS.clear()
mx = k.build_message(axs, fxs, k.appraise(axs, fxs))
if VERBOSE:
    print(mx)
check("XS: нет общей фразы «НЕДОСТАТОЧНО ДАННЫХ» и нет противоречия «34 аналога» после неё", "НЕДОСТАТОЧНО ДАННЫХ" not in mx)
check("XS: конкретная формулировка, чего не хватает",
      "Найдено 34 объявления похожих устройств, но состояние аккумулятора и наличие дефектов у них не подтверждены. "
      "Поэтому оценка основана на общем рынке и может быть неточной." in mx, mx)
check("XS: счётчики раздельно (34 всего / 0 с таким же дефектом)", "Аналоги: найдено 34 объявления" in mx and "С таким же дефектом (слабый акб) в заголовках аналогов: 0" in mx, mx)
check("XS: происхождение цен: в объявлении", "В объявлении: 250 BYN — цена продавца" in mx, mx)
check("XS: происхождение цен: выставление = медиана 34", "Выставлять ≈ 445 BYN — медиана цен 34 объявлений" in mx, mx)
check("XS: происхождение цен: быстрая продажа = нижняя четверть", "Быстро продать ≈ 390 BYN — нижняя четверть цен тех же объявлений" in mx, mx)
check("XS: лимит покупки — формула с числами, ремонт неизвестен",
      "Макс. цена покупки = ожидаемая продажа − ремонт − прочие расходы − целевая прибыль:" in mx and
      "390 (быстрая продажа) − ремонт (аккумулятор 74%; цена не известна) − 0 (прочие расходы не заданы) − 50 (целевая прибыль) = 340 − ремонт" in mx, mx)
check("XS: лимит помечен предварительным", "Лимит предварительный: не дороже <b>340 BYN</b> минус ремонт" in mx, mx)
check("XS: вывод — недостаточно данных, с порогом цены ремонта", "<b>Пока недостаточно данных для решения</b>" in mx and "не дороже 90 BYN" in mx, mx)
check("XS: примеры аналогов помечены как «без подтверждённого дефекта» и «не сделки»", "Примеры аналогов без подтверждённого дефекта (активные объявления, не сделки):" in mx, mx)
k.REPAIR_COSTS.update({"battery": 60})
mx = k.build_message(axs, fxs, k.appraise(axs, fxs))
check("XS ремонт 60: формула с известным ремонтом, один раз",
      "390 (быстрая продажа) − 60 (ремонт: аккумулятор 74%) − 0 (прочие расходы не заданы) − 50 (целевая прибыль) = 280 → не дороже <b>280 BYN</b>" in mx, mx)
check("XS ремонт 60: нет слова «предварительный» про лимит и есть «Покупать по текущей цене»", "Лимит предварительный" not in mx and "<b>Покупать по текущей цене</b>" in mx, mx)
check("XS ремонт 60: прибыль с учётом ремонта", "Прибыль при цене 250 BYN: ≈ +80 BYN при быстрой продаже, ≈ +135 BYN по цене выставления (ремонт 60 BYN" in mx, mx)
k.REPAIR_COSTS.clear()
check("XS: «ниже медианы» не подаётся плюсом при дефекте (сравнение не с такими же)", "Плюсы: цена на" not in mx, mx)
f_long = k.rule_facts(axs)
f_long["summary"] = "С" * 3000  # искусственно раздутое сообщение
m_long = k.build_message(axs, f_long, k.appraise(axs, f_long))
check("слишком длинное сообщение: влезает, вывод и ссылка сохранены, теги парные",
      len(m_long) <= 3990 and "✅ <b>Вывод для перепродажи:</b>" in m_long and "https://www.kufar.by/item/9100" in m_long
      and m_long.count("<b>") == m_long.count("</b>"), len(m_long))

print("итого ошибок (сообщение):", bad)
sys.exit(1 if bad else 0)
