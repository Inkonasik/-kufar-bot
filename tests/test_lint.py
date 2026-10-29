"""Статическая проверка кода бота и тестов без внешних пакетов: синтаксис, повторно определённые функции/классы верхнего
уровня (новая функция с тем же именем молча подменяет старую), неопределённые имена. Если установлен pyflakes или flake8,
дополнительно запускается он (ошибки класса F). Сеть не нужна."""
import ast
import builtins
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILES = [HERE.parent / "kufar_bot.py"] + sorted(HERE.glob("*.py"))
bad = 0


def check(name, cond, extra=""):
    global bad
    print(("OK  " if cond else "FAIL"), name, "" if cond else extra)
    bad += 0 if cond else 1


for path in FILES:
    src = path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src, filename=str(path))
        compile(src, str(path), "exec")
    except SyntaxError as e:
        check(f"{path.name}: синтаксис", False, e)
        continue
    seen, dups = {}, []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in seen:
                dups.append(f"{node.name} (строки {seen[node.name]} и {node.lineno})")
            seen[node.name] = node.lineno
    check(f"{path.name}: нет повторно определённых функций/классов", not dups, dups)
    defined = set(dir(builtins)) | {"__file__", "__name__"}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            defined.add(n.id)
        elif isinstance(n, ast.arg):
            defined.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            defined.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            defined.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            defined.update(n.names)
    undef = sorted({(n.id, n.lineno) for n in ast.walk(tree)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in defined})
    check(f"{path.name}: нет неопределённых имён", not undef, undef[:10])

tool = None
try:
    import pyflakes  # noqa: F401
    tool = [sys.executable, "-m", "pyflakes"]
except ImportError:
    if shutil.which("flake8"):
        tool = ["flake8", "--select=F"]
if tool:
    p = subprocess.run(tool + [str(f) for f in FILES], capture_output=True, text=True)
    check(f"{' '.join(tool[-2:])}: замечаний класса F нет", p.returncode == 0, (p.stdout + p.stderr)[-2000:])
else:
    print("(pyflakes/flake8 не установлены — выполнены только встроенные проверки)")

print(f"итого ошибок (статическая проверка): {bad}")
sys.exit(1 if bad else 0)
