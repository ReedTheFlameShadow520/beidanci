# -*- coding: utf-8 -*-
"""模拟安卓环境（IS_ANDROID=True）验证数据目录选择：共享目录不可写时回退私有目录。"""
import os
os.environ["KIVY_NO_ARGS"] = "1"

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, r"C:\Users\sopmod2\Documents\deepseek-harness\default-workspace\word_trainer_kivy")

from kivy.clock import Clock

import main as m

TMP = Path(tempfile.mkdtemp(prefix="wt_android_"))
# 用一个“父路径是文件”的位置，确保 mkdir 必然失败
blocker = TMP / "blocker"
blocker.write_text("x", encoding="utf-8")
BAD = (str(blocker / "nope1"), str(blocker / "nope2"))
GOOD = TMP / "shared_backup"


class T(m.WordApp):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.failed = []

    def check(self, cond, name):
        print(("ok: " if cond else "FAIL: ") + name)
        if not cond:
            self.failed.append(name)

    def on_start(self):
        Clock.schedule_once(self.t1, 0.3)

    def t1(self, *_):
        self.check(m.IS_ANDROID is False, "Windows 上 IS_ANDROID=False")

        m.IS_ANDROID = True
        try:
            m.WordApp.ANDROID_DATA_DIRS = BAD
            chosen = self._pick_data_dir()
            self.check(chosen == Path(self.user_data_dir), "共享目录不可写 -> 回退私有目录")
            self.check(self.storage_ok is False, "storage_ok 标记为 False")

            m.WordApp.ANDROID_DATA_DIRS = (str(GOOD),)
            chosen2 = self._pick_data_dir()
            self.check(chosen2 == GOOD, "共享目录可写 -> 使用共享目录")
            self.check(self.storage_ok is True, "storage_ok 标记为 True")
        finally:
            m.IS_ANDROID = False
            m.WordApp.ANDROID_DATA_DIRS = ("/storage/emulated/0/背单词", "/sdcard/背单词")

        print("ANDROID PATHS", "OK" if not self.failed else "FAILED")
        self.stop()


T().run()
