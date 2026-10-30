# -*- coding: utf-8 -*-
"""安卓数据目录探测/权限/迁移的手工验证（不依赖真机）。"""
import os
os.environ["KIVY_NO_ARGS"] = "1"

import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, r"C:\Users\sopmod2\Documents\deepseek-harness\default-workspace\word_trainer_kivy")
import main  # noqa: E402

WordApp = main.WordApp

# 1) _writable_dir
base = Path(tempfile.mkdtemp(prefix="wt_writable_"))
assert WordApp._writable_dir(base / "a" / "b") is True
file_path = base / "afile"
file_path.write_text("x", encoding="utf-8")
assert WordApp._writable_dir(file_path / "sub") is False, "文件路径下应不可写"

# 2) 迁移：私有目录有词库，共享目录为空 -> 复制
private = Path(tempfile.mkdtemp(prefix="wt_priv_"))
target = Path(tempfile.mkdtemp(prefix="wt_shared_"))
(private / "words.csv").write_text("word,meaning\nabide,遵从\n", encoding="utf-8")
(private / "settings_tablet.json").write_text('{"accent": 2}', encoding="utf-8")
(private / "daily_plan_tablet.json").write_text('{"20261030": []}', encoding="utf-8")
WordApp._migrate_private_files(SimpleNamespace(), target, private)
assert (target / "words.csv").exists()
assert (target / "settings_tablet.json").exists()
assert (target / "daily_plan_tablet.json").exists()

# 3) 共享目录已有更大的词库 -> 不被覆盖
big = "word,meaning\n" + "".join(f"w{i},m{i}\n" for i in range(50))
(target / "words.csv").write_text(big, encoding="utf-8")
(private / "words.csv").write_text("word,meaning\nx,y\n", encoding="utf-8")
WordApp._migrate_private_files(SimpleNamespace(), target, private)
assert (target / "words.csv").read_text(encoding="utf-8") == big

# 4) 目标已有的 json 不覆盖
(target / "settings_tablet.json").write_text('{"accent": 1}', encoding="utf-8")
WordApp._migrate_private_files(SimpleNamespace(), target, private)
assert (target / "settings_tablet.json").read_text(encoding="utf-8") == '{"accent": 1}'

# 5) 同一路径不复制（不抛异常）
WordApp._migrate_private_files(SimpleNamespace(), private, private)

shutil.rmtree(base, ignore_errors=True)
shutil.rmtree(private, ignore_errors=True)
shutil.rmtree(target, ignore_errors=True)
print("STORAGE HELPERS OK")
