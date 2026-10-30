# -*- coding: utf-8 -*-
"""Syncthing 同步层。

思路：
* words.csv 里加一列 updated_at（epoch 秒），谁改得晚就以谁为准；
* Syncthing 在两端同时改同一文件时会留下 words.sync-conflict-*.csv，
  应用启动时把这些冲突文件按 updated_at 合并进主文件，然后删掉冲突文件；
* 删除用 deleted 墓碑标记，避免另一台设备把删掉的词“复活”；
* daily_plan 文件名里带设备名，各端各自生成，不参与同步。
"""

from __future__ import annotations

import time
from pathlib import Path

from wt_core import Word, WordStore

UPDATED_COLUMN = "updated_at"
DELETED_COLUMN = "deleted"


def now_ts() -> int:
    return int(time.time())


def touch(word: Word) -> None:
    """标记这个词刚被改过。"""
    word.extras[UPDATED_COLUMN] = str(now_ts())


def is_deleted(word: Word) -> bool:
    raw = str(word.extras.get(DELETED_COLUMN, "") or "").strip().lower()
    return raw in {"1", "true", "yes", "y"}


def word_ts(word: Word | None, fallback: float = 0.0) -> float:
    if word is None:
        return -1.0
    raw = str(word.extras.get(UPDATED_COLUMN, "") or "").strip()
    if not raw:
        return float(fallback or 0.0)
    try:
        return float(raw)
    except ValueError:
        return float(fallback or 0.0)


class SyncedStore(WordStore):
    """带同步元数据的词库：删除是软删除，冲突文件可合并。"""

    def __init__(self, path: Path | str):
        super().__init__(path)
        self.tombstones: dict[str, Word] = {}

    # ---- 列 ------------------------------------------------------------ #

    def ensure_columns(self) -> None:
        lower = {col.lower() for col in self.columns}
        for name in (UPDATED_COLUMN, DELETED_COLUMN):
            if name not in lower:
                self.columns.append(name)

    # ---- 读写 ---------------------------------------------------------- #

    def load(self) -> "SyncedStore":
        super().load()
        self.tombstones = {word.key: word for word in self.words if is_deleted(word)}
        self.words = [word for word in self.words if not is_deleted(word)]
        return self

    def save(self, make_backup: bool = False) -> None:
        self.ensure_columns()
        extra = list(self.tombstones.values())
        if extra:
            self.words = self.words + extra
        try:
            super().save(make_backup)
        finally:
            if extra:
                self.words = self.words[: len(self.words) - len(extra)]

    # ---- 删除（墓碑） -------------------------------------------------- #

    def delete(self, word: Word) -> None:
        clone = Word(
            word=word.word,
            meaning=word.meaning,
            stage=word.stage,
            next_review=word.next_review,
            permanent=word.permanent,
            today_correct=word.today_correct,
            record_date=word.record_date,
            extras=dict(word.extras),
        )
        clone.extras[DELETED_COLUMN] = "1"
        touch(clone)
        self.tombstones[clone.key] = clone
        try:
            self.words.remove(word)
        except ValueError:
            pass

    # ---- 冲突合并 ------------------------------------------------------ #

    def merge_file(self, path: Path) -> int:
        """把一个冲突文件合并进当前词库，返回被更新的词条数。"""
        other = SyncedStore(path).load()
        fallback = path.stat().st_mtime
        for item in list(other.words) + list(other.tombstones.values()):
            if not str(item.extras.get(UPDATED_COLUMN, "") or "").strip():
                item.extras[UPDATED_COLUMN] = str(int(fallback))
        index = {word.key: word for word in self.words}
        changed = 0

        for row in list(other.words) + list(other.tombstones.values()):
            current = index.get(row.key)
            if word_ts(row, fallback) <= word_ts(current, self.loaded_mtime):
                continue
            if is_deleted(row):
                if current is not None:
                    try:
                        self.words.remove(current)
                    except ValueError:
                        pass
                self.tombstones[row.key] = row
                index.pop(row.key, None)
            else:
                if current is None:
                    self.words.append(row)
                else:
                    current.meaning = row.meaning
                    current.stage = row.stage
                    current.next_review = row.next_review
                    current.permanent = row.permanent
                    current.today_correct = row.today_correct
                    current.record_date = row.record_date
                    current.extras = dict(row.extras)
                self.tombstones.pop(row.key, None)
                index[row.key] = row
            changed += 1
        return changed

    def sync_from_conflicts(self) -> list[dict]:
        """合并并删除所有 words.sync-conflict-*.csv。"""
        results: list[dict] = []
        folder = self.path.parent
        for path in sorted(folder.glob(f"{self.path.stem}.sync-conflict-*")):
            if not path.is_file():
                continue
            try:
                changed = self.merge_file(path)
            except Exception as exc:  # 单个坏文件不阻塞启动
                results.append({"file": path.name, "changed": 0, "error": str(exc)})
                continue
            if changed:
                self.save()
            try:
                path.unlink()
            except OSError:
                pass
            results.append({"file": path.name, "changed": changed})
        return results

    # ---- 新增/修改时自动打时间戳 ---------------------------------------- #

    def add(self, *args, **kwargs):
        word = super().add(*args, **kwargs)
        touch(word)
        return word

    def update(self, original, **changes):
        word = super().update(original, **changes)
        touch(word)
        return word
