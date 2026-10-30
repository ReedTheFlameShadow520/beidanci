# -*- coding: utf-8 -*-
"""验证 buildozer.spec 可被 configparser 解析、关键文件存在，并重建发布用 zip。"""
import configparser
import os
import zipfile
from pathlib import Path

ROOT = Path(r"C:\Users\sopmod2\Documents\deepseek-harness\default-workspace\word_trainer_kivy")
ZIP = Path(r"C:\Users\sopmod2\Documents\deepseek-harness\default-workspace\背单词安卓版_Kivy.zip")

cp = configparser.ConfigParser()
cp.read(ROOT / "buildozer.spec", encoding="utf-8")
app = cp["app"]
print("title =", app["title"])
print("package =", app["package.domain"], app["package.name"])
print("requirements =", app["requirements"])
for key in ("icon.filename", "presplash.filename"):
    value = app[key].replace("%(source.dir)s", ".")
    path = (ROOT / value).resolve()
    print(key, "->", path, "exists:", path.exists())
assert (ROOT / "assets" / "icon.png").exists()
assert (ROOT / "assets" / "NotoSansSC-Regular.ttf").exists()
assert (ROOT / ".github" / "workflows" / "build-apk.yml").exists()

EXCLUDE_DIRS = {"__pycache__", "data", "screenshots_tmp", ".git", "bin", "build", "dist"}
EXCLUDE_FILES = {"hotkeys.log", "warn.log", "run_study.log", "run_words.log",
                 "hint.log", "hint2.log", "hint3.log"}
EXCLUDE_PREFIX = ("hint", "warn", "shot", "k_", "_", "dbg", "run_", "make_icon",
                  "patch_", "show_")
KEEP_PREFIX = ("_shot_verdict.ps1",) if False else ()

count = 0
if ZIP.exists():
    ZIP.unlink()
with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
    for path in sorted(ROOT.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if path.name in EXCLUDE_FILES:
            continue
        if path.name.startswith(EXCLUDE_PREFIX):
            continue
        zf.write(path, Path("word_trainer_kivy") / rel)
        count += 1
print("zip files:", count, "size:", ZIP.stat().st_size)
