# -*- coding: utf-8 -*-
"""按 buildozer.spec 的规则模拟“哪些文件会进 APK”，确认关键文件和排除项都正确。"""
import configparser
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
cp = configparser.ConfigParser()
cp.read(ROOT / "buildozer.spec", encoding="utf-8")
app = cp["app"]

include_exts = {e.strip().lstrip(".") for e in app["source.include_exts"].split(",")}
exclude_dirs = {d.strip() for d in app.get("source.exclude_dirs", "").split(",") if d.strip()}
patterns = [p.strip() for p in app.get("source.include_patterns", "").split(",") if p.strip()]

included = []
for path in sorted(ROOT.rglob("*")):
    rel = path.relative_to(ROOT)
    if any(part in exclude_dirs for part in rel.parts):
        continue
    if path.is_dir():
        continue
    suffix = path.suffix.lstrip(".").lower()
    matched_pattern = any(rel.match(pat) for pat in patterns)
    if suffix in include_exts or matched_pattern:
        included.append(rel)

names = {p.as_posix() for p in included}
required = {
    "main.py", "wt_core.py", "sync.py", "audio.py",
    "assets/icon.png", "assets/NotoSansSC-Regular.ttf",
}
missing = sorted(required - names)
forbidden = [n for n in names if n.startswith(("screenshots/", ".github/", "tests/"))]

print(f"apk files: {len(included)}")
print("required missing:", missing or "none")
print("should-be-excluded but included:", forbidden or "none")
print("sample:", ", ".join(sorted(names)[:8]))

if missing or forbidden:
    sys.exit(1)
print("APK FILE LIST OK")
