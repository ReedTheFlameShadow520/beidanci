# -*- coding: utf-8 -*-
"""wt_core（V3）的单元测试：python -m unittest test_core"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import wt_core as core

REAL_CSV = Path(r"G:\point\考研\words.csv")

SAMPLE = """\ufeffword,meaning,review_stage,next_review,permanent,today_correct,record_date
assassinate,暗杀,6,20260824,TRUE,False,20261023
cue,暗示，提示,6,20260822,TRUE,False,20261023
enact,颁布，实行,2,20261023,False,False,20261023
"delegate, to",代表，委托,6,20261015,True,False,20261023
bail,保释，保释金,6,20260824,True,False,
"""


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wt3_test_"))
        self.csv = self.tmp / "words.csv"
        self.csv.write_bytes(SAMPLE.encode("utf-8"))
        self.store = core.WordStore(self.csv).load()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_load(self) -> None:
        self.assertEqual(len(self.store.words), 5)
        self.assertEqual(self.store.columns[:7], core.STANDARD_COLUMNS)
        first = self.store.words[0]
        self.assertEqual(first.word, "assassinate")
        self.assertEqual(first.meaning, "暗杀")
        self.assertEqual(first.stage, 6)
        self.assertTrue(first.permanent)
        self.assertEqual(first.next_review, date(2026, 8, 24))
        self.assertTrue(first.is_new is False)
        self.assertTrue(self.store.words[-1].is_new)

    def test_bom_and_crlf_preserved(self) -> None:
        self.store.save()
        raw = self.csv.read_bytes()
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        self.assertIn(b"\r\n", raw)

    def test_roundtrip(self) -> None:
        self.store.save()
        again = core.WordStore(self.csv).load()
        self.assertEqual(len(again.words), 5)
        self.assertEqual(again.words[3].word, "delegate, to")
        self.assertEqual(again.words[3].meaning, "代表，委托")

    def test_add_update_delete(self) -> None:
        word = self.store.add("novel", "新颖的", next_review=date(2026, 10, 26))
        self.assertIs(self.store.get("NOVEL"), word)
        self.assertIsNone(word.record_date)
        self.assertTrue(word.is_new)
        with self.assertRaises(core.DuplicateWord):
            self.store.add("Novel", "小说")
        self.store.update(word, word="novelty", meaning="新奇", stage=2)
        self.assertIsNone(self.store.get("novel"))
        self.assertEqual(self.store.get("novelty").stage, 2)
        self.store.delete(word)
        self.assertIsNone(self.store.get("novelty"))

    def test_normalize_today(self) -> None:
        today = date(2026, 10, 26)
        self.store.words[0].today_correct = True
        self.store.words[0].record_date = today - timedelta(days=1)
        self.store.words[1].today_correct = True
        self.store.words[1].record_date = today
        self.store.normalize_today(today)
        self.assertFalse(self.store.words[0].today_correct)
        self.assertTrue(self.store.words[1].today_correct)

    def test_done_today(self) -> None:
        today = date(2026, 10, 26)
        self.store.words[0].today_correct = True
        self.store.words[0].record_date = today
        self.assertEqual(self.store.done_today(today), {"assassinate"})

    def test_backup(self) -> None:
        self.store.save()
        backup = self.store.backup()
        self.assertIsNotNone(backup)
        self.assertEqual(backup.read_bytes(), self.csv.read_bytes())


class JudgeTests(unittest.TestCase):
    def test_exact(self) -> None:
        verdict = core.judge("暗杀", "暗杀")
        self.assertEqual(verdict.status, "correct")
        self.assertTrue(verdict.correct)

    def test_incomplete(self) -> None:
        verdict = core.judge("暗示", "暗示，提示")
        self.assertEqual(verdict.status, "incomplete")
        self.assertEqual(verdict.missing, ["提示"])
        self.assertEqual(verdict.missing_text, "提示")

    def test_all_answered(self) -> None:
        verdict = core.judge("提示，暗示", "暗示，提示")
        self.assertEqual(verdict.status, "correct")
        self.assertEqual(verdict.missing, [])

    def test_extra_meaning_is_wrong(self) -> None:
        verdict = core.judge("暗示，随便", "暗示，提示")
        self.assertEqual(verdict.status, "wrong")

    def test_wrong(self) -> None:
        verdict = core.judge("吃饭", "暗杀")
        self.assertEqual(verdict.status, "wrong")

    def test_empty(self) -> None:
        self.assertEqual(core.judge("", "暗杀").status, "wrong")

    def test_punctuation_ignored(self) -> None:
        self.assertEqual(core.judge("暗杀。", "暗杀").status, "correct")
        self.assertEqual(core.judge(" 暗杀 , ", "暗杀").status, "correct")

    def test_partial_sentence(self) -> None:
        meaning = "负有法律责任的，有...倾向的，容易受...影响的"
        self.assertEqual(core.judge("负有法律责任的", meaning).status, "incomplete")
        self.assertEqual(core.judge("容易受影响", meaning).status, "incomplete")
        self.assertNotEqual(core.judge("法律", meaning).status, "correct")

    def test_find_word_by_meaning(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="wt3_find_"))
        try:
            csv_path = tmp / "words.csv"
            csv_path.write_bytes(SAMPLE.encode("utf-8"))
            store = core.WordStore(csv_path).load()
            self.assertEqual(core.find_word_by_meaning(store, "代表，委托"), ["delegate, to"])
            self.assertEqual(core.find_word_by_meaning(store, "代表，委托", exclude="delegate, to"), [])
            self.assertEqual(core.find_word_by_meaning(store, "不存在的意思"), [])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.today = date(2026, 10, 26)
        self.scheduler = core.Scheduler()

    def make(self, **kwargs) -> core.Word:
        return core.Word(word="test", **kwargs)

    def test_default_intervals(self) -> None:
        self.assertEqual(self.scheduler.intervals, [0, 1, 2, 3, 5, 7, 14])

    def test_due(self) -> None:
        self.assertTrue(self.scheduler.is_due(self.make(next_review=self.today), self.today))
        self.assertTrue(self.scheduler.is_due(self.make(next_review=None), self.today))
        self.assertFalse(
            self.scheduler.is_due(self.make(next_review=self.today + timedelta(days=1)), self.today)
        )
        self.assertFalse(
            self.scheduler.is_due(self.make(next_review=self.today, permanent=True), self.today)
        )

    def test_grade_up(self) -> None:
        word = self.make(stage=2)
        self.scheduler.grade(word, True, self.today)
        self.assertEqual(word.stage, 3)
        self.assertEqual(word.next_review, self.today + timedelta(days=3))
        self.assertTrue(word.today_correct)
        self.assertEqual(word.record_date, self.today)

    def test_grade_to_permanent(self) -> None:
        word = self.make(stage=6)
        self.scheduler.grade(word, True, self.today)
        self.assertEqual(word.stage, 6)
        self.assertTrue(word.permanent)
        self.assertEqual(word.next_review, self.today + timedelta(days=14))

    def test_grade_down(self) -> None:
        word = self.make(stage=5, permanent=True)
        self.scheduler.grade(word, False, self.today)
        self.assertEqual(word.stage, 0)
        self.assertFalse(word.permanent)
        self.assertEqual(word.next_review, self.today + timedelta(days=1))
        self.assertFalse(word.today_correct)

    def test_custom_intervals(self) -> None:
        scheduler = core.Scheduler([0, 1, 1, 2, 3])
        word = self.make(stage=3)
        scheduler.grade(word, True, self.today)
        self.assertEqual(word.stage, 4)
        self.assertEqual(word.next_review, self.today + timedelta(days=3))


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="wt3_plan_"))
        self.csv = self.tmp / "words.csv"
        rows = [
            "word,meaning,review_stage,next_review,permanent,today_correct,record_date",
            "new0,新词,0,20261026,False,False,20261023",
            "due2,到期,2,20261025,False,False,20261023",
            "future3,未到期,3,20261101,False,False,20261023",
            "perm1,永久一,6,20261020,True,False,20261023",
            "perm2,永久二,6,20261020,True,False,20261023",
            "done1,今天已掌握,1,20261026,False,True,20261026",
        ]
        self.csv.write_text("\ufeff" + "\n".join(rows) + "\n", encoding="utf-8")
        self.store = core.WordStore(self.csv).load()
        self.plan = core.DailyPlan(self.tmp / "daily_plan.json")
        self.today = date(2026, 10, 26)
        self.scheduler = core.Scheduler()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_generate(self) -> None:
        words = self.plan.generate(self.store, self.scheduler, self.today, permanent_sample=1)
        self.assertIn("new0", words)
        self.assertIn("due2", words)
        self.assertNotIn("future3", words)
        self.assertNotIn("done1", words)
        self.assertEqual(len([w for w in words if w.startswith("perm")]), 1)
        self.assertEqual(len(words), len(set(words)))
        self.assertTrue(self.plan.has(self.today))

    def test_generate_no_permanent_sample(self) -> None:
        words = self.plan.generate(self.store, self.scheduler, self.today, permanent_sample=0)
        self.assertEqual([w for w in words if w.startswith("perm")], [])

    def test_persist(self) -> None:
        self.plan.generate(self.store, self.scheduler, self.today, permanent_sample=0)
        again = core.DailyPlan(self.tmp / "daily_plan.json")
        self.assertTrue(again.has(self.today))
        self.assertEqual(again.words(self.today), self.plan.words(self.today))

    def test_insert_and_remaining(self) -> None:
        self.plan.set_words(self.today, ["new0", "due2", "done1", "missing"])
        self.plan.save()
        self.plan.insert(self.today, "future3")
        remaining = [w.word for w in self.plan.remaining(self.store, self.today)]
        self.assertIn("new0", remaining)
        self.assertIn("due2", remaining)
        self.assertIn("future3", remaining)
        self.assertNotIn("done1", remaining)
        self.assertNotIn("missing", remaining)
        self.assertEqual(self.plan.done_count(self.store, self.today), 1)

    def test_old_plan_file_format(self) -> None:
        path = self.tmp / "daily_plan.json"
        path.write_text(json.dumps({"20260828": ["fiscal", "audit"]}), encoding="utf-8")
        plan = core.DailyPlan(path)
        self.assertEqual(plan.words(date(2026, 8, 28)), ["fiscal", "audit"])


class LogTests(unittest.TestCase):
    def test_accumulate(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="wt3_log_"))
        try:
            path = tmp / "study_log.txt"
            log = core.StudyLog(path)
            day = date(2026, 10, 26)
            log.record(day, new=2, review=8, correct=8, wrong=1, incomplete=1)
            entry = log.record(day, new=0, review=4, correct=4, wrong=0, incomplete=0)
            self.assertEqual(entry["new_words"], 2)
            self.assertEqual(entry["review_words"], 12)
            self.assertEqual(entry["total_words"], 14)
            self.assertEqual(entry["correct_count"], 12)
            self.assertEqual(entry["incomplete_count"], 1)
            # 12 / (12 + 1 + 1) = 0.86
            self.assertEqual(entry["accuracy_rate"], 0.86)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class SettingsTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="wt3_set_"))
        try:
            path = tmp / "settings.json"
            settings = core.Settings(path)
            self.assertEqual(settings.get("permanent_sample"), 5)
            settings["permanent_sample"] = 8
            settings["intervals"] = [0, 1, 3]
            settings.save()
            again = core.Settings(path)
            self.assertEqual(again.get("permanent_sample"), 8)
            self.assertEqual(again.get("intervals"), [0, 1, 3])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(REAL_CSV.exists(), "没有找到真实词库")
class RealFileTests(unittest.TestCase):
    def test_load_real(self) -> None:
        store = core.WordStore(REAL_CSV).load()
        self.assertGreater(len(store.words), 250)
        self.assertEqual(store.encoding, "utf-8-sig")
        self.assertEqual(store.columns, core.STANDARD_COLUMNS)
        self.assertIn("abolish", {w.word for w in store.words})

        tmp = Path(tempfile.mkdtemp(prefix="wt3_real_"))
        try:
            copy = tmp / "words.csv"
            copy.write_bytes(REAL_CSV.read_bytes())
            store.path = copy
            store.save()
            again = core.WordStore(copy).load()
            self.assertEqual(len(again.words), len(store.words))
            self.assertEqual(again.words[0].word, store.words[0].word)
            self.assertEqual(again.words[0].meaning, store.words[0].meaning)
            self.assertEqual(again.words[0].stage, store.words[0].stage)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
