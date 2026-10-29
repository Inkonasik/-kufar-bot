"""Запускает все тесты по очереди. Использование: python tests/run_all.py  (код выхода 0 — всё хорошо).
У каждого набора свой тайм-аут; статусы различаются: OK — прошёл, FAIL — упал (ненулевой код), TIMEOUT — не уложился во время,
SKIP — набор сам сообщил, что пропущен (код выхода 77). «Всё в порядке» печатается, только если ВСЕ наборы — OK.
Все внешние запросы в тестах подменены: Куфар, нейросеть и Telegram не вызываются."""
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = ["test_lint", "test_models", "test_facts", "test_fresh", "test_market", "test_appraise", "test_message", "test_stage2", "test_llm", "test_vision", "test_ratelimit",
         "test_report", "test_cycle", "test_audit", "fuzz", "stress_cycle"]
TIMEOUT_S = {"test_cycle": 600, "test_audit": 600, "test_ratelimit": 300, "fuzz": 300, "stress_cycle": 300}
SKIP_CODE = 77
results = {}
for name in TESTS:
    t0 = time.time()
    try:
        p = subprocess.run([sys.executable, "-I", str(HERE / f"{name}.py")], capture_output=True, text=True,
                           timeout=TIMEOUT_S.get(name, 180))
        status = "OK" if p.returncode == 0 else "SKIP" if p.returncode == SKIP_CODE else "FAIL"
        out, err = p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        status = "TIMEOUT"
        out = (e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        err = ""
    last = (out.strip().splitlines() or ["(нет вывода)"])[-1]
    results[name] = status
    print(f"{status:7s} {name:15s} {time.time() - t0:5.1f} с  {last[:150]}")
    if status != "OK":
        print(out[-3000:], err[-2000:])
summary = {s: [n for n, v in results.items() if v == s] for s in ("OK", "FAIL", "TIMEOUT", "SKIP")}
print("\nИтог: " + ", ".join(f"{s}: {len(v)}" for s, v in summary.items()))
bad = [f"{s}: {', '.join(v)}" for s, v in summary.items() if s != "OK" and v]
print("Всё в порядке." if not bad else "Не всё прошло — " + "; ".join(bad))
sys.exit(0 if not bad else 1)
