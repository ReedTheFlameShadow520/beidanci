# -*- coding: utf-8 -*-
"""检查工程内所有 Python 文件能否被 Python 3.11 语法解析（Android 端运行时版本）。

用法: python check_py311.py
"""
import ast
import pathlib
import sys


def main() -> int:
    bad = []
    for path in sorted(pathlib.Path(".").rglob("*.py")):
        if ".git" in path.parts or "build" in path.parts or ".buildozer" in path.parts:
            continue
        src = path.read_text(encoding="utf-8-sig")
        try:
            ast.parse(src, filename=str(path), feature_version=(3, 11))
        except SyntaxError as exc:
            bad.append((str(path), exc.lineno, exc.msg))
    if bad:
        for item in bad:
            print("PY311-INCOMPATIBLE", item)
        return 1
    print("PY311 SYNTAX OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())