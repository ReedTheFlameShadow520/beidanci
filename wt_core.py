# -*- coding: utf-8 -*-
"""背单词 V3 —— 数据与逻辑层（V1 的每日计划 + V2 的数据层）。

融合点：
1. words.csv 读写沿用 V2：保留原有列与未知列、UTF-8 BOM、CRLF、TRUE/True 兼容；
2. 每日计划沿用 V1：daily_plan.json 存当天要背的词，一天只生成一次，
   新词（阶段 0）+ 到期复习词 + 每天随机抽查的永久词；
3. 复习规则沿用 V1：阶段 0~6，间隔 0/1/2/3/5/7/14 天，答对升阶段、
   到顶后标记永久掌握，答错回到阶段 0 且第二天再考；
4. 释义比对沿用 V1 的“完整 / 不完整 / 错误”三种结果，但用 V2 的模糊匹配，
   标点、空格、顺序不同不会误判；
5. 学习日志沿用 V1 的字段与正确率算法（正确 / 全部作答）。

这个模块不依赖 tkinter，可以单独跑单元测试。
"""

from __future__ import annotations

import csv
import io
import json
import os
import random
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

# --------------------------------------------------------------------------- #
# 常量与路径
# --------------------------------------------------------------------------- #

STANDARD_COLUMNS = [
    "word",
    "meaning",
    "review_stage",
    "next_review",
    "permanent",
    "today_correct",
    "record_date",
]

#: 阶段 0~6 对应的复习间隔（天）。阶段 6 答对后标记为永久掌握。
DEFAULT_INTERVALS = [0, 1, 2, 3, 5, 7, 14]

#: 每天随机抽查的永久掌握词数量（V1 的行为）。
DEFAULT_PERMANENT_SAMPLE = 5

#: daily_plan.json 保留最近多少天的计划。
PLAN_RETAIN_DAYS = 7

TRUE_WORDS = {"1", "true", "t", "yes", "y", "是", "对", "永久"}
FALSE_WORDS = {"0", "false", "f", "no", "n", "否", "错", ""}

#: 释义切分符：中英文逗号、分号、顿号、斜杠、竖线、空白、句号。
_SPLIT_RE = re.compile(r"[\s，,；;、/／|｜。.·]+")
#: 比对前去掉的标点（保留中文与字母数字）。
_STRIP_RE = re.compile(r"[（）()\[\]【】<>《》\"'“”‘’`~!！?？:：,，;；、/\\|\-—_+=*&^%$#@]+")


def app_dir() -> Path:
    """可执行文件所在目录；源码运行时是脚本所在目录。"""
    if getattr(sys, "frozen", False):  # PyInstaller 打包后
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def writable_dir() -> Path:
    """优先用程序目录（便携），不可写时退到 %APPDATA%\\WordTrainer。"""
    base = app_dir()
    try:
        probe = base / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return base
    except OSError:
        fallback = Path(os.environ.get("APPDATA") or Path.home()) / "WordTrainer"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def find_default_csv() -> Path:
    """按常见位置找 words.csv。"""
    base = app_dir()
    candidates = [
        base / "words.csv",
        base.parent / "words.csv",
        writable_dir() / "words.csv",
        Path.cwd() / "words.csv",
    ]
    for cand in candidates:
        try:
            if cand.exists():
                return cand
        except OSError:
            continue
    return base / "words.csv"


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #

def parse_date(value) -> date | None:
    """接受 20261023 / 2026-10-23 / 2026/10/23，失败返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = text.replace("-", "").replace("/", "").replace(".", "")
    if len(cleaned) == 8 and cleaned.isdigit():
        try:
            return date(int(cleaned[:4]), int(cleaned[4:6]), int(cleaned[6:8]))
        except ValueError:
            return None
    return None


def date_key(value: date | None = None) -> str:
    return (value or date.today()).strftime("%Y%m%d")


def parse_bool(value, default: bool = False) -> bool:
    text = str(value or "").strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    return default


def to_bool_text(value: bool) -> str:
    return "True" if value else "False"


def split_meanings(text: str) -> list[str]:
    """把“暗杀，刺杀；谋杀”切成 ['暗杀', '刺杀', '谋杀']。"""
    return [part.strip() for part in _SPLIT_RE.split(str(text or "")) if part.strip()]


def normalize_text(text: str) -> str:
    """去标点、去空白、转小写，用于比对。"""
    return _STRIP_RE.sub("", str(text or "").strip().lower())


def similarity(a: str, b: str) -> float:
    """两个释义片段的相似度（0~1）。"""
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    # 允许“容易受影响”匹配“容易受...影响的”，但“法律”不能匹配“负有法律责任的”
    if len(shorter) >= 2 and shorter in longer and len(shorter) / len(longer) >= 0.5:
        return 0.92
    return SequenceMatcher(None, na, nb).ratio()


# --------------------------------------------------------------------------- #
# 数据模型
# --------------------------------------------------------------------------- #

@dataclass
class Word:
    word: str
    meaning: str = ""
    stage: int = 0
    next_review: date | None = None
    permanent: bool = False
    today_correct: bool = False
    record_date: date | None = None
    extras: dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return self.word.strip().lower()

    @property
    def is_new(self) -> bool:
        """从未复习过（record_date 为空）。"""
        return self.record_date is None

    def interval_days(self, intervals: list[int]) -> int:
        idx = max(0, min(int(self.stage or 0), len(intervals) - 1))
        return int(intervals[idx])


class DuplicateWord(ValueError):
    pass


class WordStore:
    """words.csv 的内存模型。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.words: list[Word] = []
        self.columns: list[str] = list(STANDARD_COLUMNS)
        self.encoding = "utf-8-sig"
        self.delimiter = ","
        self.loaded_mtime: float = 0.0

    # ---- 读取 ---------------------------------------------------------- #

    def load(self) -> "WordStore":
        self.words = []
        self.columns = list(STANDARD_COLUMNS)
        if not self.path.exists():
            return self
        raw = self.path.read_bytes()
        text = None
        if raw.startswith(b"\xef\xbb\xbf"):
            text, self.encoding = raw.decode("utf-8-sig"), "utf-8-sig"
        else:
            for enc in ("utf-8", "gb18030"):
                try:
                    text = raw.decode(enc)
                    self.encoding = enc
                    break
                except UnicodeDecodeError:
                    continue
        if text is None:  # 兜底：忽略坏字节
            text, self.encoding = raw.decode("utf-8", errors="replace"), "utf-8"

        first_line = text.splitlines()[0] if text.splitlines() else ""
        if "\t" in first_line and "," not in first_line:
            self.delimiter = "\t"

        reader = csv.reader(io.StringIO(text), delimiter=self.delimiter)
        rows = [row for row in reader if any(str(cell).strip() for cell in row)]
        if not rows:
            return self

        header = [cell.strip().lstrip("\ufeff") for cell in rows[0]]
        lower = [cell.lower() for cell in header]
        if "word" in lower:
            self.columns = [cell or f"col{i}" for i, cell in enumerate(header)]
            data_rows = rows[1:]
            index = {name.lower(): i for i, name in enumerate(self.columns)}
        else:
            # 没有表头：按标准列顺序读取，视为旧文件
            self.columns = list(STANDARD_COLUMNS)
            index = {name: i for i, name in enumerate(STANDARD_COLUMNS)}
            data_rows = rows

        for row in data_rows:
            def cell(name: str) -> str:
                i = index.get(name)
                if i is None or i >= len(row):
                    return ""
                return str(row[i]).strip()

            word_text = cell("word")
            if not word_text:
                continue
            try:
                stage = int(float(cell("review_stage") or 0))
            except (TypeError, ValueError):
                stage = 0
            extras = {
                name: (str(row[i]).strip() if i < len(row) else "")
                for name, i in index.items()
                if name not in STANDARD_COLUMNS
            }
            self.words.append(
                Word(
                    word=word_text,
                    meaning=cell("meaning"),
                    stage=max(0, stage),
                    next_review=parse_date(cell("next_review")),
                    permanent=parse_bool(cell("permanent")),
                    today_correct=parse_bool(cell("today_correct")),
                    record_date=parse_date(cell("record_date")),
                    extras=extras,
                )
            )
        try:
            self.loaded_mtime = self.path.stat().st_mtime
        except OSError:
            self.loaded_mtime = 0.0
        return self

    # ---- 保存 ---------------------------------------------------------- #

    def backup(self, keep: int = 40) -> Path | None:
        """备份当前文件到 backups/，保留最近 keep 份。"""
        if not self.path.exists():
            return None
        folder = self.path.parent / "backups"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = folder / f"{self.path.stem}_{stamp}.csv"
            shutil.copy2(self.path, target)
            backups = sorted(folder.glob(f"{self.path.stem}_*.csv"))
            for old in backups[:-keep]:
                try:
                    old.unlink()
                except OSError:
                    pass
            return target
        except OSError:
            return None

    def normalize_today(self, today: date) -> None:
        """把不是今天的 today_correct 清掉，让 CSV 里的“今日已掌握”只表示今天。"""
        for word in self.words:
            if word.today_correct and word.record_date != today:
                word.today_correct = False

    def save(self, make_backup: bool = False) -> None:
        if make_backup:
            self.backup()
        self.normalize_today(date.today())
        for name in STANDARD_COLUMNS:
            if name not in [c.lower() for c in self.columns]:
                self.columns.append(name)
        # 统一表头名称，避免大小写混乱
        lower_map = {c.lower(): c for c in self.columns}
        self.columns = [lower_map[name.lower()] for name in self.columns]
        self.columns = list(dict.fromkeys(self.columns))

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with open(tmp, "w", encoding=self.encoding, newline="") as handle:
            writer = csv.writer(handle, delimiter=self.delimiter, lineterminator="\r\n")
            writer.writerow(self.columns)
            for word in self.words:
                row = []
                for col in self.columns:
                    key = col.lower()
                    if key == "word":
                        row.append(word.word)
                    elif key == "meaning":
                        row.append(word.meaning)
                    elif key == "review_stage":
                        row.append(str(word.stage))
                    elif key == "next_review":
                        row.append(date_key(word.next_review) if word.next_review else "")
                    elif key == "permanent":
                        row.append(to_bool_text(word.permanent))
                    elif key == "today_correct":
                        row.append(to_bool_text(word.today_correct))
                    elif key == "record_date":
                        row.append(date_key(word.record_date) if word.record_date else "")
                    else:
                        row.append(word.extras.get(col, ""))
                writer.writerow(row)
        os.replace(tmp, self.path)

    # ---- 查询 / 增删改 -------------------------------------------------- #

    def get(self, word: str) -> Word | None:
        key = str(word or "").strip().lower()
        for item in self.words:
            if item.key == key:
                return item
        return None

    def search(self, text: str = "") -> list[Word]:
        needle = str(text or "").strip().lower()
        if not needle:
            return list(self.words)
        result = []
        for item in self.words:
            haystack = f"{item.word} {item.meaning}".lower()
            if needle in haystack:
                result.append(item)
        return result

    def add(
        self,
        word: str,
        meaning: str,
        *,
        permanent: bool = False,
        stage: int = 0,
        next_review: date | None = None,
    ) -> Word:
        word = str(word).strip()
        if not word:
            raise ValueError("单词不能为空")
        if self.get(word) is not None:
            raise DuplicateWord(f"单词 “{word}” 已经存在")
        item = Word(
            word=word,
            meaning=str(meaning).strip(),
            stage=max(0, int(stage)),
            next_review=next_review,
            permanent=bool(permanent),
        )
        self.words.append(item)
        return item

    def update(self, original: Word, **changes) -> Word:
        new_word = str(changes.get("word", original.word)).strip()
        if not new_word:
            raise ValueError("单词不能为空")
        if new_word.lower() != original.key and self.get(new_word) is not None:
            raise DuplicateWord(f"单词 “{new_word}” 已经存在")
        original.word = new_word
        if "meaning" in changes:
            original.meaning = str(changes["meaning"]).strip()
        if "stage" in changes:
            original.stage = max(0, int(changes["stage"]))
        if "next_review" in changes:
            original.next_review = changes["next_review"]
        if "permanent" in changes:
            original.permanent = bool(changes["permanent"])
        return original

    def delete(self, word: Word) -> None:
        try:
            self.words.remove(word)
        except ValueError:
            pass

    def count_due(self, today: date, scheduler: "Scheduler") -> int:
        return sum(1 for item in self.words if scheduler.is_due(item, today))

    def done_today(self, today: date) -> set[str]:
        return {
            item.key
            for item in self.words
            if item.record_date == today and item.today_correct
        }


# --------------------------------------------------------------------------- #
# 间隔重复（沿用 V1 的规则）
# --------------------------------------------------------------------------- #

class Scheduler:
    """阶段 0~6，越往后间隔越长；阶段 6 再答对就标记永久掌握。

    答对：阶段 +1，下次复习 = 今天 + 间隔[新阶段]；
          已经在阶段 6 的词答对 → permanent = True（和 V1 一致）；
    答错：阶段回到 0，下次复习 = 明天，permanent 取消。
    """

    def __init__(self, intervals: list[int] | None = None):
        self.intervals = list(intervals or DEFAULT_INTERVALS)
        if len(self.intervals) < 2:
            self.intervals = list(DEFAULT_INTERVALS)

    def is_due(self, word: Word, today: date) -> bool:
        if word.permanent:
            return False
        if word.next_review is None:
            return True
        return word.next_review <= today

    def due_words(self, words: list[Word], today: date) -> list[Word]:
        return [item for item in words if self.is_due(item, today)]

    def grade(self, word: Word, correct: bool, today: date) -> int:
        """更新阶段与下次复习日期，返回新阶段。"""
        last = len(self.intervals) - 1
        if correct:
            if int(word.stage or 0) >= last:
                word.permanent = True
                word.next_review = today + timedelta(days=int(self.intervals[last]))
            else:
                word.stage = min(int(word.stage or 0) + 1, last)
                word.next_review = today + timedelta(days=int(self.intervals[word.stage]))
        else:
            word.stage = 0
            word.next_review = today + timedelta(days=1)
            word.permanent = False
        word.today_correct = bool(correct)
        word.record_date = today
        return word.stage

    def describe(self, word: Word) -> str:
        if word.permanent:
            return "永久掌握"
        stage = max(0, min(int(word.stage or 0), len(self.intervals) - 1))
        return f"阶段 {word.stage} · 间隔 {self.intervals[stage]} 天"


# --------------------------------------------------------------------------- #
# 释义比对（V1 的三种结果 + V2 的模糊匹配）
# --------------------------------------------------------------------------- #

@dataclass
class Verdict:
    status: str  # correct / incomplete / wrong
    user_tags: list[str]
    stored_tags: list[str]
    matched_user: list[str]
    matched_stored: list[str]
    missing: list[str]

    @property
    def correct(self) -> bool:
        return self.status == "correct"

    @property
    def hit_text(self) -> str:
        return "、".join(self.matched_stored)

    @property
    def missing_text(self) -> str:
        return "、".join(self.missing)


def judge(user_input: str, meaning: str, threshold: float = 0.75) -> Verdict:
    """比对用户输入与标准释义。

    把两边都按标点切成语项逐个模糊匹配：
    - 用户的每个义项都命中，且标准义项全部答出 → correct
    - 用户的义项都命中，但漏了标准里的某些义项   → incomplete（缺少的部分会提示）
    - 有义项完全对不上                             → wrong
    """
    stored_tags = split_meanings(meaning)
    user_tags = split_meanings(user_input)
    matched_user: list[str] = []
    matched_stored: list[str] = []
    used: set[int] = set()

    for tag in user_tags:
        best_score, best_index = 0.0, -1
        for i, stored in enumerate(stored_tags):
            score = similarity(tag, stored)
            if score > best_score:
                best_score, best_index = score, i
        if best_index >= 0 and best_score >= threshold:
            matched_user.append(tag)
            if best_index not in used:
                used.add(best_index)
                matched_stored.append(stored_tags[best_index])

    missing = [tag for i, tag in enumerate(stored_tags) if i not in used]
    if not user_tags:
        status = "wrong"
    elif len(matched_user) == len(user_tags):
        status = "correct" if not missing else "incomplete"
    else:
        status = "wrong"

    return Verdict(
        status=status,
        user_tags=user_tags,
        stored_tags=stored_tags,
        matched_user=matched_user,
        matched_stored=matched_stored,
        missing=missing,
    )


def find_word_by_meaning(store: WordStore, meaning: str, exclude: str | None = None,
                         limit: int = 3) -> list[str]:
    """V1 的“你输入的意思其实是哪个词”——整句释义完全相同的其它单词。"""
    target = {normalize_text(tag) for tag in split_meanings(meaning)}
    if not target:
        return []
    excluded = (exclude or "").strip().lower()
    hits: list[str] = []
    for word in store.words:
        if excluded and word.key == excluded:
            continue
        tags = {normalize_text(tag) for tag in split_meanings(word.meaning)}
        if tags and tags == target:
            hits.append(word.word)
            if len(hits) >= limit:
                break
    return hits


# --------------------------------------------------------------------------- #
# 每日计划（沿用 V1 的 daily_plan.json）
# --------------------------------------------------------------------------- #

class DailyPlan:
    """当天要背的单词列表，一天只生成一次并持久化。

    文件格式与 V1 相同：{"20261026": ["word1", "word2", ...], ...}
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.data: dict[str, list[str]] = {}
        self.load()

    def load(self) -> None:
        self.data = {}
        if not self.path.exists():
            return
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return
        if not isinstance(parsed, dict):
            return
        for key, value in parsed.items():
            if isinstance(value, list):
                self.data[str(key)] = [str(item) for item in value if str(item).strip()]

    def save(self) -> None:
        cutoff = (date.today() - timedelta(days=PLAN_RETAIN_DAYS)).strftime("%Y%m%d")
        self.data = {key: value for key, value in self.data.items() if key >= cutoff}
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def words(self, day: date | None = None) -> list[str]:
        return list(self.data.get(date_key(day), []))

    def has(self, day: date | None = None) -> bool:
        return date_key(day) in self.data

    def set_words(self, day: date, words: list[str]) -> None:
        self.data[date_key(day)] = list(words)

    def insert(self, day: date, word: str) -> None:
        key = date_key(day)
        words = self.data.setdefault(key, [])
        if word not in words:
            words.insert(random.randint(0, len(words)), word)
        self.save()

    def remove(self, day: date, word: str) -> None:
        key = date_key(day)
        if key in self.data and word in self.data[key]:
            self.data[key].remove(word)
            self.save()

    def remaining(self, store: WordStore, day: date) -> list[Word]:
        """按计划顺序返回今天还没答对、且词库里仍然存在的单词。"""
        done = store.done_today(day)
        result: list[Word] = []
        seen: set[str] = set()
        for name in self.words(day):
            word = store.get(name)
            if word is None or word.key in seen or word.key in done:
                continue
            seen.add(word.key)
            result.append(word)
        return result

    def done_count(self, store: WordStore, day: date) -> int:
        planned = {name.strip().lower() for name in self.words(day)}
        return len(planned & store.done_today(day))

    def generate(self, store: WordStore, scheduler: Scheduler, day: date,
                 permanent_sample: int = DEFAULT_PERMANENT_SAMPLE) -> list[str]:
        """生成当天计划：新词 + 到期复习 + 随机抽查的永久词（V1 的做法）。"""
        done = store.done_today(day)
        new_words = [
            word.word
            for word in store.words
            if int(word.stage or 0) == 0 and word.key not in done
        ]
        review = [
            word.word
            for word in store.words
            if (not word.permanent)
            and int(word.stage or 0) > 0
            and scheduler.is_due(word, day)
            and word.key not in done
        ]
        pool = [
            word.word
            for word in store.words
            if word.permanent and word.key not in done
        ]
        random.shuffle(pool)
        sample = pool[: max(0, int(permanent_sample))]

        merged = list(dict.fromkeys(new_words + review + sample))
        random.shuffle(merged)
        self.set_words(day, merged)
        self.save()
        return merged


# --------------------------------------------------------------------------- #
# 学习日志（V1 的字段与正确率算法）
# --------------------------------------------------------------------------- #

class StudyLog:
    """study_log.txt（JSON 文本），按日期累计。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.data: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        self.data = {}
        if not self.path.exists():
            return
        try:
            raw = self.path.read_text(encoding="utf-8-sig")
            parsed = json.loads(raw) if raw.strip() else {}
            if isinstance(parsed, dict):
                self.data = parsed
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def record(
        self,
        day: date,
        *,
        new: int = 0,
        review: int = 0,
        correct: int = 0,
        wrong: int = 0,
        incomplete: int = 0,
    ) -> dict:
        key = date_key(day)
        entry = self.data.get(key) or {}
        entry["date"] = key
        entry["new_words"] = int(entry.get("new_words", 0)) + int(new)
        entry["review_words"] = int(entry.get("review_words", 0)) + int(review)
        entry["correct_count"] = int(entry.get("correct_count", 0)) + int(correct)
        entry["wrong_count"] = int(entry.get("wrong_count", 0)) + int(wrong)
        entry["incomplete_count"] = int(entry.get("incomplete_count", 0)) + int(incomplete)
        entry["total_words"] = entry["new_words"] + entry["review_words"]
        answered = entry["correct_count"] + entry["wrong_count"] + entry["incomplete_count"]
        entry["accuracy_rate"] = round(entry["correct_count"] / answered, 2) if answered else 0.0
        self.data[key] = entry
        self.save()
        return entry

    def today(self, day: date | None = None) -> dict:
        return self.data.get(date_key(day), {})

    def recent(self, limit: int = 14) -> list[dict]:
        keys = sorted(self.data.keys(), reverse=True)[:limit]
        return [self.data[key] for key in keys]


# --------------------------------------------------------------------------- #
# 设置
# --------------------------------------------------------------------------- #

DEFAULT_SETTINGS = {
    "csv_path": "",
    "accent": 2,          # 1=英式 2=美式
    "autoplay": True,
    "shuffle": False,     # 每日计划已经打乱过
    "session_limit": 0,   # 0 = 全部
    "intervals": list(DEFAULT_INTERVALS),
    "new_word_due_today": True,
    "tts_fallback": True,
    "permanent_sample": DEFAULT_PERMANENT_SAMPLE,
    "audio_dir": "",      # 留空 = 自动找词库旁边的 READ 文件夹
}


class Settings:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.values: dict = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> "Settings":
        self.values = dict(DEFAULT_SETTINGS)
        if self.path.exists():
            try:
                parsed = json.loads(self.path.read_text(encoding="utf-8-sig"))
                if isinstance(parsed, dict):
                    self.values.update(parsed)
            except (OSError, ValueError):
                pass
        return self

    def save(self) -> None:
        try:
            self.path.write_text(
                json.dumps(self.values, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def __getitem__(self, key):
        return self.values.get(key, DEFAULT_SETTINGS.get(key))

    def __setitem__(self, key, value):
        self.values[key] = value

    def get(self, key, default=None):
        return self.values.get(key, DEFAULT_SETTINGS.get(key, default))
