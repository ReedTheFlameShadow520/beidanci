# -*- coding: utf-8 -*-
"""空词库首次启动流程：首页提示“先导入词库”，点按钮跳词库，导入后能开始学习。"""
import os
os.environ["KIVY_NO_ARGS"] = "1"

import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"C:\Users\sopmod2\Documents\deepseek-harness\default-workspace\word_trainer_kivy")

from kivy.clock import Clock

import main as m

DATA = Path(tempfile.mkdtemp(prefix="wt_first_"))


class T(m.WordApp):
    def __init__(self, **kw):
        super().__init__(demo_dir=str(DATA), **kw)
        self.failed = []

    def check(self, cond, name):
        print(("ok: " if cond else "FAIL: ") + name)
        if not cond:
            self.failed.append(name)

    def on_start(self):
        Clock.schedule_once(self.t1, 0.4)

    def t1(self, *_):
        self.check(self.sm.current == "home", "启动在首页")
        self.check(self.store.words == [], "词库为空")
        self.check("导入" in self.home.start_btn.text, "首页按钮提示先导入")

        self.home.start_btn.dispatch("on_release")
        self.check(self.sm.current == "words", "点按钮进入词库页")

        # 模拟导入：直接把词库复制到数据目录后重载
        shutil.copy2(r"G:\point\考研\words.csv", DATA / "words.csv")
        self.store = m.SyncedStore(DATA / "words.csv").load()
        self.plan = m.DailyPlan(DATA / "daily_plan_tablet.json")
        self.ensure_plan()
        self.go_home()
        remaining = self.plan.remaining(self.store, m.date.today())
        self.check(len(remaining) > 0, f"导入后有 {len(remaining)} 个待复习词")
        self.check("开始学习" in self.home.start_btn.text, "首页按钮变为开始学习")

        print("FIRST-RUN", "OK" if not self.failed else "FAILED")
        self.stop()


T().run()
