# -*- coding: utf-8 -*-
"""安卓兼容性静态检查：确保移动端代码不依赖 Windows 专有 API / 写死的绝对路径。"""
import ast
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MOBILE = ["main.py", "audio.py", "wt_core.py", "sync.py"]

BANNED_IMPORTS = {"winsound", "tkinter", "winreg", "msvcrt"}
BANNED_ATTRS = {"windll", "WinDLL"}
problems = []

for name in MOBILE:
    path = ROOT / name
    tree = ast.parse(io.open(path, encoding="utf-8").read(), filename=name)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in BANNED_IMPORTS:
                    problems.append(f"{name}: 直接 import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if top in BANNED_IMPORTS:
                problems.append(f"{name}: from {node.module} import ...")
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_ATTRS:
            problems.append(f"{name}: 使用 .{node.attr}")
        elif (isinstance(node, ast.Attribute) and node.attr == "platform"
              and isinstance(node.value, ast.Name) and node.value.id == "sys"):
            problems.append(f"{name}: 使用 sys.platform（p4a 上等于 linux）")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if ("C:\\" in value or "C:/" in value) and not value.startswith("C:\\Windows\\Fonts"):
                problems.append(f"{name}: 写死的 Windows 路径 {value[:40]!r}")

main_src = io.open(ROOT / "main.py", encoding="utf-8").read()
if "IS_ANDROID" not in main_src:
    problems.append("main.py: 缺少 IS_ANDROID 判断")

print(f"checked {len(MOBILE)} files")
if problems:
    print("ANDROID STATIC: FAILED")
    for item in problems:
        print("  -", item)
    sys.exit(1)

print("ANDROID STATIC OK")
