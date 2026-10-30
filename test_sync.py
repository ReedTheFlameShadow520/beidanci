# -*- coding: utf-8 -*-
"""Syncthing 同步层的最小回归测试。"""
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from sync import SyncedStore, now_ts, touch
from wt_core import Word


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="wtsync_"))
        self.path = self.dir / "words.csv"

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def make(self, word="alpha", meaning="阿尔法", ts=None):
        store = SyncedStore(self.path)
        if not store.words and not self.path.exists():
            store.save()
        w = Word(word=word, meaning=meaning)
        w.extras["updated_at"] = str(ts or now_ts())
        return store, w

    def test_add_and_reload(self):
        store, w = self.make()
        store.words.append(w)
        touch(w)
        store.save()
        again = SyncedStore(self.path).load()
        self.assertEqual([x.word for x in again.words], ["alpha"])
        self.assertEqual(again.words[0].meaning, "阿尔法")

    def test_soft_delete_stays_deleted(self):
        store, w = self.make()
        store.words.append(w)
        store.save()
        store = SyncedStore(self.path).load()
        store.delete(store.words[0])
        store.save()
        again = SyncedStore(self.path).load()
        self.assertEqual(again.words, [])
        self.assertIn("alpha", again.tombstones)

    def test_add_and_update_auto_stamp(self):
        """新增/修改必须自动写入 updated_at，否则冲突合并会丢平板端的改动。"""
        store = SyncedStore(self.path)
        item = store.add("beta", "贝塔")
        self.assertTrue(str(item.extras.get("updated_at") or "").strip())
        store.save()

        again = SyncedStore(self.path).load()
        item2 = again.words[0]
        old = item2.extras.get("updated_at")
        time.sleep(1.2)  # now_ts 精度是秒
        again.update(item2, meaning="贝塔2")
        self.assertNotEqual(again.words[0].extras.get("updated_at"), old)

    def test_conflict_merge_newer_wins(self):
        store, w = self.make(meaning="旧释义", ts=1000)
        store.words.append(w)
        store.save()

        # 模拟另一台设备改了释义，Syncthing 留下冲突文件
        conflict = self.dir / "words.sync-conflict-20260101-120000-ABC.csv"
        lines = self.path.read_text(encoding="utf-8-sig").splitlines()
        header = lines[0]
        body = []
        for line in lines[1:]:
            if line.startswith("alpha"):
                line = line.replace("旧释义", "新释义")
            body.append(line)
        # 冲突文件里 updated_at 更大
        idx = header.split(",").index("updated_at")
        fixed = []
        for line in body:
            cells = line.split(",")
            if cells[0] == "alpha":
                cells[idx] = str(2000)
                line = ",".join(cells)
            fixed.append(line)
        conflict.write_text("\n".join([header] + fixed) + "\n", encoding="utf-8")

        store = SyncedStore(self.path).load()
        results = store.sync_from_conflicts()
        self.assertEqual(len(results), 1)
        self.assertGreaterEqual(results[0]["changed"], 1)
        again = SyncedStore(self.path).load()
        self.assertEqual(again.words[0].meaning, "新释义")
        self.assertFalse(conflict.exists())


if __name__ == "__main__":
    unittest.main()
