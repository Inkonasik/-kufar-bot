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
PHRASES = ("Покупать по текущей цене", "Покупать только после торга", "Не покупать для перепродажи", "Пока недостаточно данных для решения")
k._MARKET_REFRESHES["n"] = 99  # сеть не трогаем
for name, a in CASES.items():
    f = k.rule_facts(a)
    ap = k.appraise(a, f)
    msg = k.build_full_message(a, f, ap)
    if VERBOSE:
        print("=" * 70, name, f"[{ap['status']}] {len(msg)} симв.")
        print(msg)
    check(f"{name}: длина", len(msg) <= 4096, len(msg))
    stripped = ALLOWED.sub("", msg)
    check(f"{name}: нет «сырых» <>", "<" not in stripped and ">" not in stripped.replace("&gt;", ""), stripped[:200])
    check(f"{name}: теги <b> парные", msg.count("<b>") == msg.count("</b>"))
    check(f"{name}: ссылка на объявление", f"https://www.kufar.by/item/{a['ad_id']}" in msg)
    check(f"{name}: есть цена или пометка", "BYN" in msg or "договорная" in msg or "не указана" in msg)
    check(f"{name}: шапка 📱💰📍🔧 и блоки 🔍 Состояние, ⚠️ Риски, ✅ Итоговая рекомендация",
          all(e in msg for e in ("📱", "💰 Цена продавца:", "📍", "🔧", "🔍 <b>Состояние</b>", "⚠️ <b>Риски</b>", "✅ <b>Итоговая рекомендация:</b>")), msg)
    if ap["comps"] and ap["status"] == "ok":
        check(f"{name}: пометка «не сделок»", "не сделок" in msg or "не сделки" in msg)
    if ap["status"] == "ok":
        check(f"{name}: блоки 📊 Рынок, 💵 Вариант 1, 🔧 Вариант 2",
              all(e in msg for e in ("📊 <b>Рынок</b>", "💵 <b>Вариант 1 — перепродажа без ремонта</b>", "🔧 <b>Вариант 2 — ремонт и перепродажа</b>")), msg)
        check(f"{name}: все пять категорий состояния показаны", all(f"• {n}:" in msg for n in k.CAT_NAMES.values()), msg)
        check(f"{name}: ссылки на аналоги реальные", all(f"/item/{c[0]}" in msg for c in ap["comps"]))
    if ap["status"] in ("few", "no_market", "se_gen", "no_model"):
        check(f"{name}: нет вердикта по цене", not any(v in msg for v in ("ОЧЕНЬ ВЫГОДНО", "<b>ВЫГОДНО", "ДОРОГО", "НЕВЫГОДНО")))
    check(f"{name}: нет общей фразы «НЕДОСТАТОЧНО ДАННЫХ»", "НЕДОСТАТОЧНО ДАННЫХ" not in msg)
    check(f"{name}: нет шаблонных X/Y вместо цифр", not re.search(r"(?<![A-Za-zА-Яа-я])[XY](?![A-Za-zА-Яа-я])|X–Y", msg), msg)
    check(f"{name}: ровно один итог", msg.count("✅ <b>Итоговая рекомендация:</b>") == 1, msg)
    concl = [ln for ln in msg.split("\n") if ln.startswith("✅")][0]
    check(f"{name}: итог — одна из четырёх фраз", sum(ph in concl for ph in PHRASES) == 1, concl)
    check(f"{name}: итог после блоков рисков и вариантов (после него только проверка, аналоги и ссылка)",
          msg.index(concl) > msg.rfind("⚠️ <b>Риски</b>") and (msg.rfind("🔧 <b>Вариант 2") < msg.index(concl) or "Вариант 2" not in msg), msg)
    check(f"{name}: нет обещаний прибыли", "гарантирован" not in msg.replace("Не гарантия", "") and "точно заработ" not in msg)

m = k.build_full_message(CASES["экранирование"], k.rule_facts(CASES["экранирование"]), k.appraise(CASES["экранирование"], k.rule_facts(CASES["экранирование"])))
check("экранирование заголовка", "&lt;b&gt;&amp;&lt;/b&gt;" in m and "iPhone 11 <b>&</b>" not in m)
f = k.rule_facts(CASES["экранирование"])
f["summary"] = "Продам <script>alert(1)</script> & всё"
f["risks"] = ["<i>риск</i>"]
m = k.build_full_message(CASES["экранирование"], f, k.appraise(CASES["экранирование"], f))
check("AI-сводка не выводится; риски экранируются", "<script>" not in m and "&lt;i&gt;" in m and "<i>" not in m)
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
m = k.build_full_message(CASES["запчасти"], f, k.appraise(CASES["запчасти"], f))
check("запчасти: «не покупать» и пометка", "Не покупать для перепродажи" in m and "на запчасти" in m, m)
check("запчасти: вариант 2 не рассматривается (скрытые повреждения непредсказуемы)", "Не рассматриваю" in m, m)
f = k.rule_facts(CASES["дефект, ремонт неизвестен"])
m = k.build_full_message(CASES["дефект, ремонт неизвестен"], f, k.appraise(CASES["дефект, ремонт неизвестен"], f))
check("дефект: ремонт неизвестен — не придуман, максимум предварительный", "цена ремонта не задана (REPAIR_COSTS), бот её не придумывает" in m and "(до вычета ремонта)" in m, m)
check("дефект: прибыль названа «до вычета ремонта»", "Прибыль до вычета ремонта" in m, m)
check("дефект: не выдуманы расходы на ремонт", "ремонт 0" not in m and "(ремонт 0" not in m)
check("дефект: конкретно, чего не хватает", "у них не подтверждены" in m and "оценка основана на общем рынке и может быть неточной" in m, m)
check("дефект: счётчики раздельно", "Найдено 10 объявлений похожих устройств" in m and "С таким же дефектом (экран) в заголовках аналогов: 0" in m, m)
check("дефект: чувствительность к цене ремонта показана как «что если», а не как цены", "Что если (не цены ремонта" in m or "ремонт выгоднее" not in m.lower(), m)
# --- пример из задачи: iPhone XS 64 ГБ, 250 BYN, аккумулятор 74%, 34 аналога (значения этапа 2 по умолчанию: резерв 5%, запас на ремонт 15%) ---
put("iPhone XS", [[500 + i, 330 + i * 7, 64, 0, 1 if i < 16 else 5 if i < 22 else 3 if i < 28 else 4, 0] for i in range(34)])
axs = ad("iPhone XS 64gb", 25000, "Состояние хорошее, акб 74%.", region="Гомельская область", ad_id=9100)
fxs = k.analyze_ad(axs)  # как в боте: правила + (нет ключа нейросети) -> фото не анализируются, и это честно сказано
k.REPAIR_COSTS.clear()
mx = k.build_full_message(axs, fxs, k.appraise(axs, fxs))
if VERBOSE:
    print(mx)
check("XS: нет общей фразы «НЕДОСТАТОЧНО ДАННЫХ» и нет противоречия «34 аналога» после неё", "НЕДОСТАТОЧНО ДАННЫХ" not in mx)
check("XS: конкретная формулировка, чего не хватает",
      "Найдено 34 объявления похожих устройств, но состояние аккумулятора и наличие дефектов у них не подтверждены. "
      "Поэтому оценка основана на общем рынке и может быть неточной." in mx, mx)
check("XS: счётчики раздельно (34 всего / 0 с таким же дефектом)", "найдено 34 активных объявления" in mx and "С таким же дефектом (слабый акб) в заголовках аналогов: 0" in mx, mx)
check("XS: цена продавца названа", "💰 Цена продавца: 250 BYN" in mx, mx)
check("XS: категория «небольшие дефекты» отмечена как этот телефон", "небольшие дефекты: объявлений нет ◀ этот телефон" in mx, mx)
check("XS: вариант 1 честно: оценить «как есть» не из чего, ничего не выдумано", "Оценить продажу «как есть» не из чего" in mx and "нужно ≥ 3" in mx, mx)
check("XS: происхождение цен продажи: выставлять = медиана, быстро = нижняя четверть (q1 387,5 → вниз до 385), найдено 34", 
      "выставлять ≈ 445 BYN, быстро ≈ 385 BYN (найдено: 34 объявления без названных дефектов" in mx, mx)
check("XS: формула максимума с числами, ремонт неизвестен, резерв и цель",
      "385 (быстрая продажа) − ремонт (аккумулятор 74%; цена не известна) − 20 (резерв 5% на непроверенные функции) − 50 (целевая прибыль) = 315 (до вычета ремонта)" in mx, mx)
check("XS: три уровня цены покупки", "желательно ≤ <b>290</b> · максимум <b>315</b> · отказ выше 425 BYN" in mx, mx)
check("XS: вывод — недостаточно данных, с порогом цены ремонта", "<b>Пока недостаточно данных для решения</b>" in mx and "≈ 55 BYN" in mx, mx)
check("XS: непроверенные функции перечислены в «Не проверено» и в рисках", "Не проверено: блокировка (iCloud/активация); Face ID/Touch ID;" in mx and "Возможны скрытые дефекты" in mx, mx)
check("XS: фото честно «не анализировались» (нет ключа нейросети)", "По фото: не анализировались — не подключена нейросеть" in mx, mx)
check("XS: примеры аналогов помечены как «без названных дефектов» и «не сделки»", "Примеры аналогов без названных дефектов (активные объявления, не сделки):" in mx, mx)
k.REPAIR_COSTS.update({"battery": 60})
mx = k.build_full_message(axs, fxs, k.appraise(axs, fxs))
check("XS ремонт 60: формула с известным ремонтом один раз, запас 15%, резерв 5%",
      "385 (быстрая продажа) − 69 (ремонт 60 + запас 15%) − 20 (резерв 5% на непроверенные функции) − 50 (целевая прибыль) = 246 → 245" in mx, mx)
check("XS ремонт 60: нет «до вычета ремонта»", "(до вычета ремонта)" not in mx and "Ремонт: аккумулятор 74% 60 BYN (REPAIR_COSTS)" in mx, mx)
check("XS ремонт 60: прибыль после всех учтённых расходов",
      "Прибыль после всех учтённых расходов при цене 250 BYN: от +46 (быстрая продажа) до +115 (по цене выставления) BYN" in mx, mx)
k.REPAIR_COSTS.clear()
check("XS: «ниже медианы» не подаётся плюсом при дефекте (сравнение не с такими же)", "Плюсы: цена на" not in mx, mx)
f_long = k.rule_facts(axs)
f_long["summary"] = "С" * 3000  # искусственно раздутое сообщение
m_long = k.build_full_message(axs, f_long, k.appraise(axs, f_long))
check("слишком длинное сообщение: влезает, итог и ссылка сохранены, теги парные",
      len(m_long) <= 3990 and "✅ <b>Итоговая рекомендация:</b>" in m_long and "https://www.kufar.by/item/9100" in m_long
      and m_long.count("<b>") == m_long.count("</b>"), len(m_long))

print("итого ошибок (сообщение):", bad)
sys.exit(1 if bad else 0)
