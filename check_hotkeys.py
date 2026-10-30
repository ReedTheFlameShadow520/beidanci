# -*- coding: utf-8 -*-
"""验证 Kivy 版蓝牙键盘快捷键（无需真机）。"""
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

DATA = Path(tempfile.mkdtemp(prefix="wt_keys_"))
shutil.copy2(r"G:\point\考研\words.csv", DATA / "words.csv")


class T(m.WordApp):
    def __init__(self, **kw):
        super().__init__(demo_dir=str(DATA), **kw)
        self.events = []
        self.failed = []

    def on_start(self):
        self.speaker.speak = lambda w: self.events.append(("speak", w))
        Clock.schedule_once(self.t1, 0.4)

    def check(self, cond, name):
        if not cond:
            self.failed.append(name)
            print("FAIL:", name)
        else:
            print("ok:", name)

    def t1(self, *_):
        self.start_today()
        self.check(self.sm.current == "study", "start_today -> study")

        Window.dispatch("on_keyboard", 0, 0, "p", ["ctrl"])
        self.check(any(e[0] == "speak" for e in self.events), "Ctrl+P 发音")

        self.study.input.text = "随便写的"
        self.submit_answer()
        dialog = getattr(self, "_verdict", None)
        self.check(dialog is not None and not getattr(dialog, "_closed", False),
                   "提交后弹出判定弹窗")

        Window.dispatch("on_keyboard", 13, 0, "\r", [])
        self.check(getattr(dialog, "_closed", False), "Enter 关闭弹窗并进入下一题")

        Window.dispatch("on_keyboard", 0, 0, "n", ["ctrl"])
        self.check(self.sm.current == "words", "Ctrl+N 打开词库")

        self.check(not self.failed, "全部快捷键")
        print("HOTKEYS", "OK" if not self.failed else "FAILED")
        self.stop()

T().run()
