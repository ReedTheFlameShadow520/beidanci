# -*- coding: utf-8 -*-
"""背单词 · 安卓版（Kivy）

沿用 V3 的数据层（words.csv / 每日计划 / 阶段复习 / 三档判定），
界面用 Kivy 重写，适配平板触屏；PC 与平板通过 Syncthing 同步 words.csv，
冲突文件在启动时按 updated_at 合并。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import threading
import time
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("KIVY_NO_ARGS", "1")

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.utils import get_color_from_hex, platform as kivy_platform
from kivy.graphics import Color, Line, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.recycleview import RecycleView
from kivy.uix.scrollview import ScrollView
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.spinner import Spinner
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

from audio import Speaker
from sync import SyncedStore, is_deleted, now_ts, touch
from wt_core import (
    DEFAULT_INTERVALS,
    DailyPlan,
    Settings,
    Scheduler,
    StudyLog,
    date_key,
    find_word_by_meaning,
    judge,
    parse_date,
    split_meanings,
)

APP_TITLE = "背单词"
APP_VERSION = "3.1-android"

COLORS = {
    "bg": (0.957, 0.965, 0.980, 1),
    "card": (1.0, 1.0, 1.0, 1),
    "primary": (0.145, 0.388, 0.922, 1),
    "primary_dark": (0.106, 0.302, 0.749, 1),
    "text": (0.118, 0.161, 0.231, 1),
    "muted": (0.420, 0.447, 0.502, 1),
    "line": (0.886, 0.910, 0.941, 1),
    "soft": (0.937, 0.953, 0.980, 1),
    "ok": (0.086, 0.639, 0.290, 1),
    "warn": (0.851, 0.467, 0.024, 1),
    "bad": (0.863, 0.149, 0.149, 1),
    "white": (1, 1, 1, 1),
}


# --------------------------------------------------------------------------- #
# 字体
# --------------------------------------------------------------------------- #

def _register_font() -> str:
    base = Path(__file__).resolve().parent
    candidates = [
        base / "NotoSansSC-Regular.ttf",
        base / "NotoSansSC-Regular.otf",
        base / "assets" / "NotoSansSC-Regular.ttf",
        base / "assets" / "NotoSansSC-Regular.otf",
        Path("/system/fonts/NotoSansCJK-Regular.ttc"),
        Path("/system/fonts/HarmonyOS_Sans_SC_Regular.ttf"),
        Path("/system/fonts/DroidSansFallback.ttf"),
    ]
    if kivy_platform == "win":
        candidates += [Path(r"C:\Windows\Fonts\msyh.ttc"),
                       Path(r"C:\Windows\Fonts\msyh.ttf")]
    for path in candidates:
        try:
            if not path.exists():
                continue
            LabelBase.register(name="CJK", fn_regular=str(path))
            return "CJK"
        except Exception:
            continue
    return "Roboto"


FONT = _register_font()

# 注意：python-for-android 上 sys.platform == 'linux'，不能只看 sys.platform
IS_ANDROID = kivy_platform == "android" or hasattr(sys, "getandroidapilevel")


# --------------------------------------------------------------------------- #
# 小部件
# --------------------------------------------------------------------------- #

def paint(widget: Widget, color, radius: float = dp(12)):
    with widget.canvas.before:
        Color(*color)
        widget._bg = RoundedRectangle(radius=[radius])

    def _update(*_):
        widget._bg.pos = widget.pos
        widget._bg.size = widget.size

    widget.bind(pos=_update, size=_update)
    _update()


def outline(widget: Widget, color, radius: float = dp(12), width: float = 1):
    with widget.canvas.after:
        Color(*color)
        widget._line = Line(rounded_rectangle=(0, 0, 0, 0, radius), width=width)

    def _update(*_):
        widget._line.rounded_rectangle = (
            widget.x, widget.y, widget.width, widget.height, radius)
    widget.bind(pos=_update, size=_update)
    _update()


class Card(BoxLayout):
    def __init__(self, radius=dp(16), color=None, **kwargs):
        kwargs.setdefault("orientation", "vertical")
        kwargs.setdefault("padding", dp(18))
        kwargs.setdefault("spacing", dp(8))
        super().__init__(**kwargs)
        paint(self, color or COLORS["card"], radius)


class RoundedButton(Button):
    def __init__(self, primary=False, flat=False, **kwargs):
        super().__init__(**kwargs)
        self.primary = primary
        self.flat = flat
        self.background_normal = ""
        self.background_down = ""
        self.background_color = (0, 0, 0, 0)
        self.font_name = kwargs.get("font_name", FONT)
        self.font_size = kwargs.get("font_size", sp(17))
        self.color = COLORS["white"] if primary else COLORS["text"]
        if not flat:
            paint(self, COLORS["primary"] if primary else COLORS["card"], dp(10))
            if not primary:
                outline(self, COLORS["line"], dp(10))


class RoundedInput(TextInput):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_active = ""
        self.background_color = (0, 0, 0, 0)
        self.foreground_color = COLORS["text"]
        self.cursor_color = COLORS["primary"]
        self.font_name = FONT
        self.font_size = sp(20)
        self.padding = [dp(14), dp(12), dp(14), dp(12)]
        paint(self, (1, 1, 1, 1), dp(10))
        outline(self, COLORS["line"], dp(10), 1)


class Divider(Widget):
    def __init__(self, **kwargs):
        kwargs.setdefault("size_hint_y", None)
        kwargs.setdefault("height", dp(1))
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*COLORS["line"])
            self._rect = RoundedRectangle()
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_):
        self._rect.pos = self.pos
        self._rect.size = self.size


def label(text="", size=14, color=None, bold=False, **kwargs):
    kwargs.setdefault("font_name", FONT)
    kwargs.setdefault("font_size", sp(size))
    kwargs.setdefault("color", color or COLORS["text"])
    if bold:
        kwargs.setdefault("bold", True)
    return Label(text=text, **kwargs)


def wrap(label_widget: Label, width: float | None = None):
    label_widget.text_size = (width or label_widget.width, None)
    label_widget.bind(width=lambda inst, val: setattr(inst, "text_size", (val, None)))


class ScreenBase(Screen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app


# --------------------------------------------------------------------------- #
# 首页
# --------------------------------------------------------------------------- #

class HomeScreen(ScreenBase):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        root = BoxLayout(orientation="vertical", padding=[dp(26), dp(16)],
                         spacing=dp(12))
        root.add_widget(self._header())

        body = BoxLayout(orientation="vertical", spacing=dp(10))
        body.add_widget(Widget())
        greeting = label("早上好，今天也要背单词。", size=20, bold=True)
        body.add_widget(greeting)
        self.date_label = label("", size=12, color=COLORS["muted"])
        body.add_widget(self.date_label)

        card = Card(size_hint=(1, None), height=dp(300), spacing=dp(6))
        card.add_widget(label("今日待复习", size=13, color=COLORS["muted"]))
        self.big = label("0", size=58, color=COLORS["primary"], bold=True,
                         size_hint=(1, None), height=dp(96))
        card.add_widget(self.big)
        self.stats = label("", size=13, color=COLORS["muted"])
        card.add_widget(self.stats)
        self.start_btn = RoundedButton(text="开始学习", primary=True,
                                       size_hint=(1, None), height=dp(52),
                                       font_size=sp(19))
        self.start_btn.bind(on_release=lambda *_: (self.app.open_words()
                                                   if not self.app.store.words
                                                   else self.app.start_today()))
        card.add_widget(self.start_btn)
        hint = label("点“开始学习”按今天的计划背单词 · 支持蓝牙键盘", size=11,
                     color=COLORS["muted"])
        card.add_widget(hint)
        body.add_widget(card)
        body.add_widget(Widget())
        root.add_widget(body)

        self.footer = label("", size=10, color=COLORS["muted"], size_hint=(1, None),
                            height=dp(20))
        root.add_widget(self.footer)
        self.add_widget(root)

        Clock.schedule_interval(self.refresh, 2.0)
        self.refresh()

    def _header(self):
        bar = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        title = label("背单词", size=22, bold=True, color=COLORS["primary"])
        bar.add_widget(title)
        sub = label("考研词汇 · 每日计划", size=12, color=COLORS["muted"])
        bar.add_widget(sub)
        bar.add_widget(Widget())
        for text, action in (("词库", self.app.open_words),
                             ("统计", self.app.show_stats),
                             ("同步", self.app.sync_now),
                             ("设置", self.app.open_settings)):
            btn = RoundedButton(text=text, size_hint=(None, 1), width=dp(72),
                                font_size=sp(15))
            btn.bind(on_release=lambda _b, act=action: act())
            bar.add_widget(btn)
        return bar

    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self, *_):
        app = self.app
        plan = app.plan
        today = date.today()
        remaining = plan.remaining(app.store, today)
        due = len(remaining)
        self.big.text = str(due)
        done = plan.done_count(app.store, today)
        entry = app.log.today(today)
        acc = entry.get("accuracy_rate", 0)
        acc_text = f"{int(round(acc * 100))}%" if entry else "—"
        self.stats.text = (f"今日计划 {len(plan.words(today))} 词 · 已完成 {done} 词 · "
                           f"正确率 {acc_text}\n"
                           f"词库 {len(app.store.words)} 词 · 永久掌握 "
                           f"{sum(1 for w in app.store.words if w.permanent)} 词")
        total = len(app.store.words)
        if total == 0:
            self.stats.text = ("词库还是空的\n把 words.csv 放进数据目录，或点「词库」→ 导入 CSV")
        self.start_btn.text = (f"开始学习（{due} 词）" if due
                               else ("先导入词库" if total == 0 else "今天已经背完了"))
        self.start_btn.disabled = due == 0 and total > 0
        self.date_label.text = today.strftime("%Y年%m月%d日")
        self.footer.text = f"数据：{app.data_dir}"
        self.footer.text_size = (self.footer.width, None)


# --------------------------------------------------------------------------- #
# 学习页
# --------------------------------------------------------------------------- #

class StudyScreen(ScreenBase):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        root = BoxLayout(orientation="vertical", padding=[dp(26), dp(12)],
                         spacing=dp(10))
        bar = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10))
        self.progress = label("0 / 0", size=14, color=COLORS["muted"],
                              size_hint=(None, 1), width=dp(120), halign="left")
        self.progress.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
        bar.add_widget(self.progress)
        bar.add_widget(Widget())
        quit_btn = RoundedButton(text="结束本次", size_hint=(None, 1), width=dp(100),
                                 font_size=sp(14))
        quit_btn.bind(on_release=lambda *_: app.finish_session(aborted=True))
        bar.add_widget(quit_btn)
        root.add_widget(bar)

        card = Card(spacing=dp(10), padding=[dp(36), dp(20)])
        self.meta = label("", size=12, color=COLORS["muted"], size_hint=(1, None),
                          height=dp(20))
        card.add_widget(self.meta)
        self.word = label("", size=46, bold=True, size_hint=(1, None),
                          height=dp(120), color=COLORS["text"])
        card.add_widget(self.word)
        card.add_widget(label("输入中文意思，多个义项用逗号分隔（回车提交）",
                              size=11, color=COLORS["muted"], size_hint=(1, None),
                              height=dp(18)))
        self.input = RoundedInput(hint_text="输入中文意思，多个义项用逗号分隔",
                                  hint_text_color=COLORS["muted"],
                                  multiline=False, write_tab=False,
                                  size_hint=(1, None), height=dp(56))
        self.input.bind(on_text_validate=lambda *_: app.submit_answer())
        card.add_widget(self.input)
        hint = label("Enter 提交 · Ctrl+P 发音 · 看答案会记为答错", size=11,
                     color=COLORS["muted"], size_hint=(1, None), height=dp(18))
        card.add_widget(hint)
        card.add_widget(Widget())

        buttons = BoxLayout(size_hint=(1, None), height=dp(54), spacing=dp(10))
        submit = RoundedButton(text="提交", primary=True)
        submit.bind(on_release=lambda *_: app.submit_answer())
        speak = RoundedButton(text="朗读")
        speak.bind(on_release=lambda *_: app.speak_current())
        reveal = RoundedButton(text="看答案")
        reveal.bind(on_release=lambda *_: app.reveal_answer())
        for btn in (submit, speak, reveal):
            buttons.add_widget(btn)
        card.add_widget(buttons)
        root.add_widget(card)

        self.status = label("", size=11, color=COLORS["muted"], size_hint=(1, None),
                            height=dp(18))
        root.add_widget(self.status)
        self.add_widget(root)


# --------------------------------------------------------------------------- #
# 判定弹窗
# --------------------------------------------------------------------------- #

class VerdictView(ModalView):
    def __init__(self, app, session, word, typed, verdict, **kwargs):
        super().__init__(size_hint=(0.86, None), height=dp(430), auto_dismiss=False,
                         background_color=(0, 0, 0, 0.45))
        self.app = app
        self.session = session
        self.word = word
        self.typed = typed
        self.verdict = verdict

        if verdict.status == "correct":
            head, color = "答对了", COLORS["ok"]
        elif verdict.status == "incomplete":
            head, color = "还差一点", COLORS["warn"]
        else:
            head, color = "答错了", COLORS["bad"]

        card = Card(padding=dp(22), spacing=dp(8))
        card.add_widget(label(head, size=22, bold=True, color=color))
        card.add_widget(label(word.word, size=34, bold=True))
        card.add_widget(label(f"你的答案：{typed or '（空）'}", size=13,
                             color=COLORS["muted"]))
        card.add_widget(Divider())
        if verdict.status != "correct":
            card.add_widget(label(f"释义   {word.meaning}", size=17))
        if verdict.status == "incomplete":
            self.extra = label(f"还差：{verdict.missing_text}（会留在待测列表里）",
                               size=12, color=COLORS["warn"])
            card.add_widget(self.extra)
        elif verdict.status == "wrong":
            hint = "这个词会留在待测列表里，稍后再考一次"
            others = find_word_by_meaning(self.app.store, word.meaning,
                                         exclude=word.word)
            if others:
                hint = f"你输入的其实是：{'、'.join(others)}。{hint}"
            self.extra = label(hint, size=12, color=COLORS["muted"])
            card.add_widget(self.extra)

        card.add_widget(Widget())
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8))
        next_btn = RoundedButton(text="下一个", primary=True)
        next_btn.bind(on_release=lambda *_: self.next_card())
        row.add_widget(next_btn)
        ok_btn = RoundedButton(text="算我答对")
        ok_btn.bind(on_release=lambda *_: self.finish(True))
        row.add_widget(ok_btn)
        bad_btn = RoundedButton(text="其实不会")
        bad_btn.bind(on_release=lambda *_: self.finish(False))
        row.add_widget(bad_btn)
        again = RoundedButton(text="再听一次", flat=True)
        again.bind(on_release=lambda *_: self.app.speaker.speak(self.word.word))
        row.add_widget(again)
        card.add_widget(row)
        self.add_widget(card)

        if verdict.status == "correct":
            self._timer = Clock.schedule_once(lambda *_: self.next_card(), 1.3)

    def on_touch_down(self, touch):
        # 模态：点空白不关闭，必须点按钮
        return super().on_touch_down(touch)

    def next_card(self):
        if getattr(self, "_closed", False):
            return
        self.app.resolve_verdict(self.session, self.word, self.typed, self.verdict,
                                 None)
        self._close()

    def finish(self, force_correct: bool):
        if getattr(self, "_closed", False):
            return
        self.app.resolve_verdict(self.session, self.word, self.typed, self.verdict,
                                 force_correct)
        self._close()

    def _close(self):
        self._closed = True
        try:
            Clock.unschedule(self._timer)
        except Exception:
            pass
        self.dismiss()


# --------------------------------------------------------------------------- #
# 结算页
# --------------------------------------------------------------------------- #

class SummaryScreen(ScreenBase):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)

    def show(self, session):
        self.clear_widgets()
        root = BoxLayout(orientation="vertical", padding=[dp(26), dp(24)],
                         spacing=dp(10))
        root.add_widget(Widget(size_hint_y=None, height=dp(16)))
        title = label("本次学习结束", size=25, bold=True, size_hint=(1, None),
                      height=dp(40))
        root.add_widget(title)
        minutes = max(1, int((time.time() - session.started) / 60))
        root.add_widget(label(f"共 {len(session.done_words)} 词 · 用时约 {minutes} 分钟",
                              size=12, color=COLORS["muted"], size_hint=(1, None),
                              height=dp(22)))
        card = Card(size_hint=(1, None), height=dp(130), orientation="horizontal",
                    spacing=dp(4))
        for text, value, color in (("答对", session.correct, COLORS["ok"]),
                                   ("不完整", session.incomplete, COLORS["warn"]),
                                   ("答错", session.wrong, COLORS["bad"])):
            box = BoxLayout(orientation="vertical")
            box.add_widget(label(str(value), size=30, bold=True, color=color))
            box.add_widget(label(text, size=11, color=COLORS["muted"]))
            card.add_widget(box)
        total = session.correct + session.incomplete + session.wrong
        rate = session.correct / total if total else 0
        box = BoxLayout(orientation="vertical")
        box.add_widget(label(f"{int(round(rate * 100))}%", size=30, bold=True))
        box.add_widget(label("正确率", size=11, color=COLORS["muted"]))
        card.add_widget(box)
        root.add_widget(card)

        wrongs = session.wrong_words()
        if wrongs:
            root.add_widget(label("这些词还要再看看", size=13, bold=True,
                                  size_hint=(1, None), height=dp(20)))
            scroll = ScrollView(size_hint=(1, 1))
            inner = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(6))
            inner.bind(minimum_height=inner.setter("height"))
            for word in wrongs[:30]:
                row = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(10),
                                padding=[dp(8), 0])
                row.add_widget(label(word.word, size=16, bold=True,
                                     color=COLORS["bad"], size_hint_x=None,
                                     width=dp(160)))
                row.add_widget(label(word.meaning, size=13, color=COLORS["muted"]))
                inner.add_widget(row)
            scroll.add_widget(inner)
            root.add_widget(scroll)
        else:
            root.add_widget(Widget())

        buttons = BoxLayout(size_hint=(1, None), height=dp(52), spacing=dp(10))
        again = RoundedButton(text="再练这些错词", primary=True)
        again.bind(on_release=lambda *_: self.app.start_words(wrongs))
        again.disabled = not wrongs
        home = RoundedButton(text="回到首页")
        home.bind(on_release=lambda *_: self.app.go_home())
        buttons.add_widget(again)
        buttons.add_widget(home)
        root.add_widget(buttons)
        self.add_widget(root)


# --------------------------------------------------------------------------- #
# 词库页
# --------------------------------------------------------------------------- #

class WordRow(BoxLayout):
    def __init__(self, word=None, app=None, **kwargs):
        super().__init__(**kwargs)
        self.word_obj = word
        self.app = app
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(54)
        self.padding = [dp(10), 0]
        self.spacing = dp(12)
        self.word_label = label("", size=16, bold=True, size_hint_x=None,
                                 width=dp(150), halign="left", valign="middle")
        self.word_label.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
        self.meaning_label = label("", size=13, color=COLORS["muted"],
                                   halign="left", valign="middle")
        self.meta_label = label("", size=11, color=COLORS["muted"],
                                size_hint_x=None, width=dp(110), halign="right")
        self.meta_label.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
        self.meaning_label.bind(size=lambda inst, val: setattr(inst, "text_size", (val[0], None)))
        for widget in (self.word_label, self.meaning_label, self.meta_label):
            self.add_widget(widget)

    def apply(self, item: dict):
        self.word_label.text = item["word"]
        self.meaning_label.text = item["meaning"]
        self.meta_label.text = item["meta"]
        self.word_label.color = item["color"]

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self.app is not None:
                self.app.edit_word(self.word_obj)
            return True
        return super().on_touch_down(touch)


class WordsScreen(ScreenBase):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)
        root = BoxLayout(orientation="vertical", padding=[dp(24), dp(12)],
                         spacing=dp(10))
        bar = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        back = RoundedButton(text="返回", size_hint=(None, 1), width=dp(80))
        back.bind(on_release=lambda *_: app.go_home())
        bar.add_widget(back)
        bar.add_widget(label("搜索", size=12, color=COLORS["muted"],
                             size_hint_x=None, width=dp(40)))
        self.search = RoundedInput(hint_text="搜索单词或释义", multiline=False,
                                   size_hint=(1, 1), font_size=sp(16))
        self.search.bind(text=lambda *_: self.refresh())
        bar.add_widget(self.search)
        self.count = label("", size=12, color=COLORS["muted"], size_hint_x=None,
                           width=dp(80))
        bar.add_widget(self.count)
        root.add_widget(bar)

        self.scroll = ScrollView(size_hint=(1, 1), bar_width=dp(5))
        self.inner = BoxLayout(orientation="vertical", size_hint_y=None,
                               spacing=dp(2))
        self.inner.bind(minimum_height=self.inner.setter("height"))
        self.scroll.add_widget(self.inner)
        root.add_widget(self.scroll)

        buttons = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        add = RoundedButton(text="新增单词", primary=True)
        add.bind(on_release=lambda *_: app.edit_word(None))
        buttons.add_widget(add)
        root.add_widget(buttons)
        self.add_widget(root)

    def on_pre_enter(self, *args):
        self.refresh()

    def refresh(self, *_):
        self.inner.clear_widgets()
        keyword = self.search.text.strip().lower() if hasattr(self, "search") else ""
        today = date.today()
        rows = []
        for word in self.app.store.words:
            if keyword and keyword not in f"{word.word} {word.meaning}".lower():
                continue
            rows.append(word)
        for word in rows:
            if word.permanent:
                meta, color = "永久掌握", COLORS["muted"]
            elif self.app.scheduler.is_due(word, today):
                meta, color = "待复习", COLORS["primary"]
            else:
                meta = date_key(word.next_review) if word.next_review else ""
                color = COLORS["text"]
            row = WordRow(word=word, app=self.app)
            row.apply({"word": word.word, "meaning": word.meaning,
                       "meta": meta, "color": color})
            self.inner.add_widget(row)
        self.count.text = f"{len(rows)} 词"


class SettingsScreen(ScreenBase):
    def __init__(self, app, **kwargs):
        super().__init__(app, **kwargs)

    def on_pre_enter(self, *args):
        self.clear_widgets()
        app = self.app
        root = BoxLayout(orientation="vertical", padding=[dp(24), dp(12)],
                         spacing=dp(8))
        bar = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        back = RoundedButton(text="返回", size_hint=(None, 1), width=dp(80))
        back.bind(on_release=lambda *_: app.go_home())
        bar.add_widget(back)
        bar.add_widget(label("设置", size=20, bold=True))
        root.add_widget(bar)

        scroll = ScrollView()
        body = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10))
        body.bind(minimum_height=body.setter("height"))

        body.add_widget(self._row("数据目录", app.data_dir.name or str(app.data_dir),
                                  str(app.data_dir)))
        if app.device == "tablet" and not getattr(app, "storage_ok", True):
            body.add_widget(label(
                "⚠ 当前数据在应用私有目录。Syncthing 需要 /storage/emulated/0/背单词："
                "请到系统设置里给「背单词」授予存储 / 所有文件访问权限，再重启应用，"
                "词库会自动迁移过去。",
                size=11, color=COLORS["bad"], size_hint=(1, None), height=dp(52)))
        body.add_widget(self._row("同步", "Syncthing 文件夹", "冲突文件启动时自动合并"))

        accent_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        accent_row.add_widget(label("口音", size=14, size_hint_x=None, width=dp(90)))
        spinner = Spinner(text="美式" if app.settings["accent"] == 2 else "英式",
                          values=("美式", "英式"), size_hint=(None, 1), width=dp(120),
                          font_name=FONT)
        spinner.bind(text=lambda inst, val: app.set_accent(2 if val == "美式" else 1))
        accent_row.add_widget(spinner)
        body.add_widget(accent_row)

        auto_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
        auto_row.add_widget(label("出现单词时自动发音", size=14))
        auto_row.add_widget(Widget())
        switch = Switch(active=bool(app.settings["autoplay"]))
        switch.bind(active=lambda inst, val: app.set_autoplay(bool(val)))
        auto_row.add_widget(switch)
        body.add_widget(auto_row)

        body.add_widget(label(f"复习间隔（阶段 0~6，天）："
                              f"{', '.join(map(str, app.scheduler.intervals))}",
                              size=12, color=COLORS["muted"], size_hint=(1, None),
                              height=dp(24)))
        body.add_widget(label("答对升一阶段，答错回阶段 0；阶段 6 再答对即永久掌握。",
                              size=11, color=COLORS["muted"], size_hint=(1, None),
                              height=dp(20)))

        diag_btn = RoundedButton(text="运行自检（数据目录 / 词库 / 音频）",
                                 size_hint_y=None, height=dp(46))
        diag_btn.bind(on_release=lambda *_: app.run_diagnostics())
        body.add_widget(diag_btn)

        sync_btn = RoundedButton(text="立即同步（合并冲突文件）", size_hint_y=None,
                                 height=dp(46))
        sync_btn.bind(on_release=lambda *_: app.sync_now())
        body.add_widget(sync_btn)

        body.add_widget(label(f"版本 {APP_VERSION} · 数据与 PC 共用 words.csv",
                              size=11, color=COLORS["muted"], size_hint=(1, None),
                              height=dp(22)))
        scroll.add_widget(body)
        root.add_widget(scroll)
        self.add_widget(root)

    def _row(self, title, value, sub=""):
        box = Card(size_hint_y=None, height=dp(74), spacing=dp(2))
        box.add_widget(label(title, size=13, color=COLORS["muted"]))
        box.add_widget(label(value, size=13))
        if sub:
            box.add_widget(label(sub, size=10, color=COLORS["muted"]))
        return box


# --------------------------------------------------------------------------- #
# 应用
# --------------------------------------------------------------------------- #


def make_popup(title, content, height=None, width_ratio=0.8):
    """统一主题的 Popup：白色圆角卡片、CJK 标题，避免默认深色主题与方块字。"""
    return Popup(title=title, content=content,
                 title_font=FONT, title_color=COLORS["text"], title_size=sp(18),
                 separator_color=COLORS["line"],
                 size_hint=(width_ratio, None),
                 height=height or dp(320),
                 background="", background_color=COLORS["card"])


class WordApp(App):
    def __init__(self, csv_path: str | None = None, demo: str | None = None,
                 demo_dir: str | None = None, shot: str | None = None,
                 shot_delay: float = 2.5, **kwargs):
        super().__init__(**kwargs)
        self.csv_override = csv_path
        self.demo = demo
        self.demo_dir = demo_dir
        self.shot = shot
        self.shot_delay = shot_delay
        self.session = None
        self._pending_words = None
        self.data_dir = Path(".")
        self.storage_ok = True
        self.store = None
        self.settings = None
        self.scheduler = None
        self.log = None
        self.plan = None
        self.speaker = None
        self.device = "tablet"

    # ---- 启动 ---------------------------------------------------------- #

    def build(self):
        self.title = APP_TITLE
        if kivy_platform == "win":
            Window.size = (1100, 800)
        try:
            Window.softinput_mode = "below_target"
        except Exception:
            pass
        Window.clearcolor = COLORS["bg"]
        self._bootstrap()
        sys.excepthook = self._crash_hook
        self.ensure_plan()

        self.sm = ScreenManager(transition=NoTransition())
        self.home = HomeScreen(self, name="home")
        self.study = StudyScreen(self, name="study")
        self.summary = SummaryScreen(self, name="summary")
        self.words = WordsScreen(self, name="words")
        self.settings_screen = SettingsScreen(self, name="settings")
        for screen in (self.home, self.study, self.summary, self.words,
                       self.settings_screen):
            self.sm.add_widget(screen)
        self.sm.current = "home"
        Window.bind(on_keyboard=self._on_keyboard)
        self.home.refresh()
        if self.demo:
            Clock.schedule_once(lambda *_: self._run_demo(), 0.8)
        if self.shot:
            Clock.schedule_once(self._take_shot, self.shot_delay)
        return self.sm

    def _bootstrap(self):
        self.device = "tablet" if IS_ANDROID else "pc"
        self.data_dir = self._pick_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "READ").mkdir(parents=True, exist_ok=True)

        csv_path = Path(self.csv_override) if self.csv_override else self.data_dir / "words.csv"
        self.store = SyncedStore(csv_path).load()
        if not self.store.words:
            self.store.save()
        conflicts = self.store.sync_from_conflicts()

        self.settings = Settings(self.data_dir / f"settings_{self.device}.json")
        intervals = self.settings.get("intervals") or DEFAULT_INTERVALS
        self.scheduler = Scheduler(intervals)
        self.log = StudyLog(self.data_dir / f"study_log_{self.device}.txt")
        self.plan = DailyPlan(self.data_dir / f"daily_plan_{self.device}.json")
        read_dir = self.data_dir / "READ"
        self.speaker = Speaker(self.data_dir / "audio", [read_dir],
                               accent=int(self.settings.get("accent") or 2))
        self._conflicts = conflicts

    ANDROID_DATA_DIRS = ("/storage/emulated/0/背单词", "/sdcard/背单词")

    def _pick_data_dir(self) -> Path:
        if self.demo_dir:
            self.storage_ok = True
            return Path(self.demo_dir)
        if IS_ANDROID:
            self._request_storage_permission()
            for candidate in (Path(p) for p in self.ANDROID_DATA_DIRS):
                if self._writable_dir(candidate):
                    self.storage_ok = True
                    self._migrate_private_files(candidate)
                    return candidate
            # 没拿到存储权限时先用应用私有目录，授权后重启会自动迁移
            self.storage_ok = False
            return Path(self.user_data_dir)
        self.storage_ok = True
        return Path(__file__).resolve().parent / "data"

    def _request_storage_permission(self) -> None:
        """安卓首次启动时申请存储权限；失败不抛错，下次启动再试。"""
        try:
            from android.permissions import Permission, request_permissions
        except Exception:
            return
        perms = []
        for name in ("READ_EXTERNAL_STORAGE", "WRITE_EXTERNAL_STORAGE",
                     "MANAGE_EXTERNAL_STORAGE"):
            perm = getattr(Permission, name, None)
            if perm:
                perms.append(perm)
        if perms:
            try:
                request_permissions(perms)
            except Exception:
                pass

    @staticmethod
    def _writable_dir(candidate: Path) -> bool:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("1", encoding="utf-8")
            probe.unlink()
            return True
        except Exception:
            return False

    def _migrate_private_files(self, target: Path, private: Path | None = None) -> None:
        """把私有目录里的数据搬到共享目录（目标已有同名文件则保留目标）。"""
        private = Path(private) if private is not None else Path(self.user_data_dir)
        try:
            if not private.exists() or private.resolve() == target.resolve():
                return
        except Exception:
            return
        words = private / "words.csv"
        dst = target / "words.csv"
        try:
            if words.exists() and (not dst.exists()
                                   or dst.stat().st_size < words.stat().st_size):
                shutil.copy2(words, dst)
        except Exception:
            pass
        for pattern in ("*.json", "study_log_*.txt"):
            for src in private.glob(pattern):
                dst = target / src.name
                try:
                    if not dst.exists():
                        shutil.copy2(src, dst)
                except Exception:
                    pass

    # ---- 计划 / 会话 --------------------------------------------------- #

    def ensure_plan(self):
        today = date.today()
        if not self.plan.has(today):
            self.plan.generate(self.store, self.scheduler, today,
                               permanent_sample=int(self.settings.get("permanent_sample") or 5))

    def start_today(self):
        self.ensure_plan()
        words = self.plan.remaining(self.store, date.today())
        self.start_words(words)

    def start_words(self, words):
        if not words:
            self.toast("今天没有待复习的词了")
            return
        self.session = Session(self, words)
        self.sm.current = "study"
        self.show_current()

    def show_current(self):
        session = self.session
        word = session.current()
        if word is None:
            self.finish_session()
            return
        self.study.progress.text = f"{session.index + 1} / {len(session.queue)}"
        self.study.meta.text = self.scheduler.describe(word) + (
            " · 新词" if word.stage == 0 and word.record_date is None else "")
        self.study.word.text = word.word
        self.study.input.text = ""
        self.study.input.focus = True
        self.study.status.text = ""
        if self.settings.get("autoplay") and self.speaker:
            self.speaker.speak(word.word)
        self.speaker.prefetch([w.word for w in session.queue[session.index + 1:session.index + 4]])

    def speak_current(self):
        if self.session and self.session.current():
            self.speaker.speak(self.session.current().word)

    def submit_answer(self):
        if not self.session or self.session.current() is None:
            return
        text = self.study.input.text.strip()
        if not text:
            self.study.status.text = "先输入意思，或用“看答案”"
            return
        self.judge_input(text)

    def reveal_answer(self):
        if not self.session or self.session.current() is None:
            return
        self.judge_input("")

    def judge_input(self, text):
        session = self.session
        word = session.current()
        verdict = judge(text, word.meaning)
        self.study.input.text = text
        self.study.input.disabled = True
        view = VerdictView(self, session, word, text, verdict)
        self._verdict = view
        view.open()

    def resolve_verdict(self, session, word, typed, verdict, force_correct):
        if force_correct is None:
            ruling = verdict.status == "correct"
        else:
            ruling = bool(force_correct)
        session.record(word, typed, verdict, ruling)
        self.store.save()
        self.study.input.disabled = False
        self.study.input.text = ""
        self.next_card()

    def next_card(self):
        session = self.session
        if session is None:
            return
        session.index += 1
        if session.index >= len(session.queue):
            self.finish_session()
        else:
            self.show_current()

    def finish_session(self, aborted: bool = False):
        session = self.session
        if session is None:
            return
        if session.index < len(session.queue) and not aborted:
            session.index = len(session.queue)
        self.summary.show(session)
        self.sm.current = "summary"
        self.session = None
        self.home.refresh()

    def go_home(self):
        self.session = None
        self.sm.current = "home"
        self.home.refresh()

    # ---- 词库 ---------------------------------------------------------- #

    def open_words(self):
        self.words.refresh()
        self.sm.current = "words"

    def open_settings(self):
        self.sm.current = "settings"

    def edit_selected(self):
        self.toast("点一下单词行即可编辑")

    def edit_word(self, word):
        content = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
        word_input = RoundedInput(hint_text="单词", multiline=False,
                                  size_hint_y=None, height=dp(52),
                                  text=word.word if word else "")
        meaning_input = RoundedInput(hint_text="释义，多个义项用逗号分隔", multiline=False,
                                     size_hint_y=None, height=dp(52),
                                     text=word.meaning if word else "")
        content.add_widget(label("单词", size=12, color=COLORS["muted"]))
        content.add_widget(word_input)
        content.add_widget(label("释义", size=12, color=COLORS["muted"]))
        content.add_widget(meaning_input)
        popup = make_popup("编辑单词" if word else "新增单词", content, dp(330))

        def save(*_):
            name = word_input.text.strip()
            meaning = meaning_input.text.strip()
            if not name or not meaning:
                return
            try:
                if word is None:
                    item = self.store.add(name, meaning)
                    touch(item)
                else:
                    self.store.update(word, word=name, meaning=meaning)
                    touch(word)
                self.store.save()
                popup.dismiss()
                self.words.refresh()
            except Exception as exc:
                self.toast(str(exc))

        def do_delete(*_):
            if word is None:
                popup.dismiss()
                return
            self.store.delete(word)
            self.store.save()
            popup.dismiss()
            self.words.refresh()

        row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        save_btn = RoundedButton(text="保存", primary=True)
        save_btn.bind(on_release=save)
        cancel = RoundedButton(text="取消")
        cancel.bind(on_release=lambda *_: popup.dismiss())
        row.add_widget(save_btn)
        if word is not None:
            delete = RoundedButton(text="删除", flat=True)
            delete.bind(on_release=do_delete)
            row.add_widget(delete)
        row.add_widget(cancel)
        content.add_widget(row)
        popup.open()

    # ---- 其它 ---------------------------------------------------------- #

    def set_accent(self, accent: int):
        self.settings["accent"] = accent
        self.settings.save()
        self.speaker.set_accent(accent)

    def set_autoplay(self, value: bool):
        self.settings["autoplay"] = value
        self.settings.save()

    def sync_now(self):
        try:
            results = self.store.sync_from_conflicts()
        except Exception as exc:
            self.toast(f"同步失败：{exc}")
            return
        if not results:
            self.toast("没有需要合并的冲突文件")
        else:
            changed = sum(item.get("changed", 0) for item in results)
            self.toast(f"合并了 {len(results)} 个冲突文件，更新 {changed} 个词条")
        self.home.refresh()

    def show_stats(self):
        days = self.log.recent(14)
        lines = []
        for entry in days:
            lines.append(
                f"{entry.get('date', '')}  新词 {entry.get('new_words', 0)} · "
                f"复习 {entry.get('review_words', 0)} · 正确率 "
                f"{int(round(entry.get('accuracy_rate', 0) * 100))}%")
        text = "\n".join(lines) if lines else "还没有学习记录"
        popup = make_popup("学习统计", label(text, size=13), dp(360))
        popup.open()
        self._stats_popup = popup

    def toast(self, text, seconds=2.0):
        popup = make_popup("提示", label(text, size=14), dp(180), width_ratio=0.6)
        popup.open()
        Clock.schedule_once(lambda *_: popup.dismiss(), seconds)
        self._toast = popup

    def on_stop(self):
        try:
            if self.store:
                self.store.save()
        except Exception:
            pass

    def on_pause(self):
        """Android 切到后台（例如去系统设置授权、切到 Syncthing）时保存。"""
        try:
            if self.store:
                self.store.save()
        except Exception:
            pass
        return True

    def on_resume(self):
        """回到前台时重新读取词库：Syncthing 可能已经在后台把新版本同步过来了。"""
        if getattr(self, "sm", None) is None:
            return
        if self.sm.current not in ("home", "summary"):
            return
        try:
            self.store.load()
            self.store.sync_from_conflicts()
            self.ensure_plan()
            self.home.refresh()
        except Exception:
            pass

    def _crash_hook(self, exc_type, exc, tb):
        try:
            text = "".join(traceback.format_exception(exc_type, exc, tb))
            (self.data_dir / "crash.log").write_text(text, encoding="utf-8")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    def run_diagnostics(self):
        """平板上的自检：数据目录、词库、计划、音频、字体，结果写文件并弹窗。"""
        lines = []
        ok = True

        def add(text, good=True):
            nonlocal ok
            lines.append(("✔ " if good else "✘ ") + text)
            ok = ok and good

        add(f"平台：{kivy_platform} / {getattr(sys, 'platform', '?')}")
        add(f"设备角色：{self.device}")
        try:
            probe = self.data_dir / ".write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            add(f"数据目录可写：{self.data_dir}")
        except Exception as exc:
            add(f"数据目录不可写：{self.data_dir}（{exc}）", False)
        add(f"词库：{len(self.store.words)} 词")
        try:
            self.ensure_plan()
            add(f"今日计划剩余：{len(self.plan.remaining(self.store, date.today()))} 词")
        except Exception as exc:
            add(f"每日计划异常：{exc}", False)
        add(f"音频后端：{'可用' if self.speaker else '不可用'}", bool(self.speaker))
        add(f"字体：{FONT}")
        lines.append("")
        lines.append("结果：" + ("全部通过" if ok else "发现问题，见上方 ✘"))
        try:
            (self.data_dir / "诊断.txt").write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass
        popup = make_popup("自检", label("\n".join(lines), size=12), dp(420))
        popup.open()
        self._diag_popup = popup

    # ---- 键盘 ---------------------------------------------------------- #

    def _on_keyboard(self, window, key, scancode, codepoint, modifiers):
        ctrl = "ctrl" in modifiers
        dialog = getattr(self, "_verdict", None)
        if dialog is not None and not getattr(dialog, "_closed", False):
            # 判定弹窗里的键盘操作（蓝牙键盘）
            if key == 13:  # Enter -> 下一个
                dialog.next_card()
                return True
            if ctrl and codepoint == "p":
                if self.speaker:
                    self.speaker.speak(dialog.word.word)
                return True
            if codepoint == "1":
                dialog.finish(True)
                return True
            if codepoint == "2":
                dialog.finish(False)
                return True

        if ctrl and codepoint == "p" and self.sm.current == "study":
            self.speak_current()
            return True
        if ctrl and codepoint == "n":
            self.open_words()
            return True

        if key == 27:  # Android 返回键 / Esc
            if self.sm.current in ("study", "summary"):
                if self.sm.current == "study" and self.session:
                    self.finish_session(aborted=True)
                else:
                    self.go_home()
                return True
            if self.sm.current in ("words", "settings"):
                self.go_home()
                return True
        return False

    def _take_shot(self, *_):
        # Kivy 的 screenshot 会在文件名里插入序号，这里先用固定名，再由调用方改名
        try:
            Window.screenshot(name="shot.png")
        except Exception:
            traceback.print_exc()
        finally:
            Clock.schedule_once(lambda *_: self.stop(), 0.5)

    # ---- 演示模式（截图用） -------------------------------------------- #

    def _run_demo(self):
        if self.demo == "incomplete":
            self.start_today()
            Clock.schedule_once(lambda *_: self._demo_partial(), 0.6)
        elif self.demo == "correct":
            self.start_today()
            Clock.schedule_once(lambda *_: self._demo_correct(), 0.6)
        elif self.demo == "wrong":
            self.start_today()
            Clock.schedule_once(lambda *_: self._demo_answer("错误答案"), 0.6)
        elif self.demo == "study":
            self.start_today()
        elif self.demo == "summary":
            self.start_today()
            Clock.schedule_once(lambda *_: self.finish_session(aborted=True), 0.8)
        elif self.demo == "words":
            self.open_words()
        elif self.demo == "settings":
            self.open_settings()

    def _demo_answer(self, text):
        if self.session and self.session.current():
            word = self.session.current()
            self.study.input.text = text
            self.judge_input(text)

    def _demo_correct(self):
        if self.session and self.session.current():
            word = self.session.current()
            self.study.input.text = word.meaning
            self.judge_input(word.meaning)

    def _demo_partial(self):
        if not self.session:
            return
        for i, item in enumerate(self.session.queue):
            tags = split_meanings(item.meaning)
            if len(tags) >= 2:
                self.session.index = i
                self.show_current()
                self.study.input.text = tags[0]
                self.judge_input(tags[0])
                return
        self._demo_answer(错误答案)


class Session:
    def __init__(self, app, words):
        self.app = app
        self.queue = list(words)
        self.index = 0
        self.correct = 0
        self.incomplete = 0
        self.wrong = 0
        self.done_words = []
        self.bad_words = []
        self.attempts = {}
        self.started = time.time()

    def current(self):
        if 0 <= self.index < len(self.queue):
            return self.queue[self.index]
        return None

    def record(self, word, typed, verdict, correct: bool):
        today = date.today()
        key = word.key
        is_new = word.record_date is None
        self.attempts[key] = self.attempts.get(key, 0) + 1
        if verdict.status == "correct":
            self.correct += 1
        elif verdict.status == "incomplete":
            self.incomplete += 1
        else:
            self.wrong += 1
        self.app.log.record(
            today,
            new=1 if is_new else 0,
            review=0 if is_new else 1,
            correct=1 if verdict.status == "correct" else 0,
            incomplete=1 if verdict.status == "incomplete" else 0,
            wrong=1 if verdict.status == "wrong" else 0,
        )
        if verdict.status != "correct":
            self.bad_words.append(word)
            if self.attempts[key] < 2:
                self.queue.append(word)  # 没答对：本轮再考一次
        self.app.scheduler.grade(word, correct, today)
        touch(word)
        if word not in self.done_words:
            self.done_words.append(word)

    def wrong_words(self):
        seen, result = set(), []
        for word in self.bad_words:
            if word.key not in seen:
                seen.add(word.key)
                result.append(word)
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", help="words.csv 路径（默认用数据目录里的）")
    parser.add_argument("--demo",
                        choices=["correct", "incomplete", "wrong", "study",
                                 "summary", "words", "settings"],
                        help="演示模式，自动答题（截图用）")
    parser.add_argument("--demo-dir", help="演示时使用的数据目录")
    parser.add_argument("--shot", help="截图保存路径（自动退出）")
    parser.add_argument("--shot-delay", type=float, default=2.5)
    args = parser.parse_args()
    WordApp(csv_path=args.csv, demo=args.demo, demo_dir=args.demo_dir,
            shot=args.shot, shot_delay=args.shot_delay).run()


if __name__ == "__main__":
    main()
