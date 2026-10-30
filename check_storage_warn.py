# -*- coding: utf-8 -*-
"""强制模拟“安卓未授权存储权限”，检查设置页红色提示能正常显示。"""
import os
os.environ["KIVY_NO_ARGS"] = "1"

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"C:\Users\sopmod2\Documents\deepseek-harness\default-workspace\word_trainer_kivy")

from kivy.clock import Clock
from kivy.core.window import Window

import main as m

DATA = Path(tempfile.mkdtemp(prefix="wt_warn_"))
shutil.copy2(r"G:\point\考研\words.csv", DATA / "words.csv")


class T(m.WordApp):
    def on_start(self):
        self.device = "tablet"
        self.storage_ok = False
        Clock.schedule_once(lambda *_: self.open_settings(), 0.3)
        Clock.schedule_once(lambda *_: Window.screenshot(name="warn.png"), 1.2)
        Clock.schedule_once(lambda *_: self.stop(), 1.8)


T(demo_dir=str(DATA)).run()
print("WARN SHOT DONE")
