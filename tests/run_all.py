"""Запускает все тесты по очереди. Использование: python tests/run_all.py  (код выхода 0 — всё хорошо)."""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTS = ["test_models", "test_facts", "test_appraise", "test_message", "test_stage2", "test_llm", "test_ratelimit", "test_report", "test_cycle", "fuzz"]
failed = []
for name in TESTS:
    p = subprocess.run([sys.executable, "-I", str(HERE / f"{name}.py")], capture_output=True, text=True)
    last = (p.stdout.strip().splitlines() or ["(нет вывода)"])[-1]
    print(f"{'OK  ' if p.returncode == 0 else 'FAIL'} {name:15s} {last}")
    if p.returncode:
        failed.append(name)
        print(p.stdout[-3000:], p.stderr[-2000:])
print("\nВсё в порядке." if not failed else f"\nПровалены: {', '.join(failed)}")
sys.exit(1 if failed else 0)
