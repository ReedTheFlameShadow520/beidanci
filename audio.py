# -*- coding: utf-8 -*-
"""发音：本地 READ 文件夹优先，其次缓存，最后从有道下载。

播放用 Kivy 的 SoundLoader（内部是 SDL2_mixer，安卓上支持 mp3）；
如果 SoundLoader 打不开文件，再退回 Android 的 MediaPlayer。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from kivy.core.audio import SoundLoader

AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")

__all__ = ["Speaker"]


class Speaker:
    def __init__(self, cache_dir: Path | str, local_dirs=None, accent: int = 2,
                 timeout: float = 8.0):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.local_dirs = [Path(p) for p in (local_dirs or []) if p]
        self.accent = 2 if int(accent or 2) == 2 else 1
        self.timeout = timeout
        self._lock = threading.Lock()
        self._sound = None
        self._media_player = None
        self.last_error = ""
        self.play_count = 0
        self._spoken: dict[str, float] = {}

    # ---- 配置 ---------------------------------------------------------- #

    def set_accent(self, accent: int) -> None:
        self.accent = 2 if int(accent or 2) == 2 else 1

    def set_local_dirs(self, dirs) -> None:
        self.local_dirs = [Path(p) for p in (dirs or []) if p]

    # ---- 对外 ---------------------------------------------------------- #

    def speak(self, word: str) -> None:
        """后台线程里发音，不阻塞界面。"""
        word = str(word or "").strip()
        if not word:
            return
        now = time.time()
        with self._lock:
            last = self._spoken.get(word.lower(), 0.0)
            if now - last < 0.3:   # 连点去重
                return
            self._spoken[word.lower()] = now
        threading.Thread(target=self._speak_sync, args=(word,), daemon=True).start()

    def stop(self) -> None:
        sound = self._sound
        self._sound = None
        if sound is not None:
            try:
                sound.stop()
            except Exception:
                pass
        player = self._media_player
        self._media_player = None
        if player is not None:
            try:
                player.stop()
                player.release()
            except Exception:
                pass

    def prefetch(self, words) -> None:
        """预先下载一批词的音频（后台线程）。"""
        names = [str(w).strip() for w in words if str(w).strip()]
        if not names:
            return

        def worker():
            for name in names[:8]:
                try:
                    self._ensure_audio(name)
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    # ---- 内部 ---------------------------------------------------------- #

    def _speak_sync(self, word: str) -> None:
        try:
            path = self._ensure_audio(word)
            if path is None:
                self.last_error = f"没有找到 “{word}” 的音频，也无法下载"
                return
            self._play(path)
            self.last_error = ""
            self.play_count += 1
        except Exception as exc:
            self.last_error = str(exc)

    def _ensure_audio(self, word: str) -> Path | None:
        found = self._find_local(word)
        if found is not None:
            return found
        cached = self._find_cached(word)
        if cached is not None:
            return cached
        return self._download(word)

    def _find_local(self, word: str) -> Path | None:
        key = word.strip().lower()
        for folder in self.local_dirs:
            if not folder.exists():
                continue
            for ext in AUDIO_EXTS:
                candidate = folder / f"{word}{ext}"
                if candidate.exists():
                    return candidate
            # 模糊：忽略大小写 / 前缀
            try:
                for candidate in folder.iterdir():
                    if not candidate.is_file():
                        continue
                    stem = candidate.stem.lower()
                    if stem == key or (len(key) > 3 and stem.startswith(key)):
                        return candidate
            except OSError:
                continue
        return None

    def _find_cached(self, word: str) -> Path | None:
        key = word.strip().lower()
        try:
            for candidate in self.cache_dir.iterdir():
                if candidate.is_file() and candidate.stem.lower() == key:
                    return candidate
        except OSError:
            return None
        return None

    def _download(self, word: str) -> Path | None:
        url = (
            "https://dict.youdao.com/dictvoice?audio="
            f"{quote(word.strip())}&type={self.accent}"
        )
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                data = response.read()
        except Exception as exc:
            self.last_error = f"下载失败：{exc}"
            return None
        if len(data) < 200:
            self.last_error = "下载到的音频太小，可能不可用"
            return None
        target_dir = self.local_dirs[0] if self.local_dirs else self.cache_dir
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            target_dir = self.cache_dir
        target = target_dir / f"{word.strip()}.mp3"
        try:
            target.write_bytes(data)
            return target
        except OSError:
            fallback = self.cache_dir / f"{word.strip()}.mp3"
            try:
                fallback.write_bytes(data)
                return fallback
            except OSError:
                return None

    def _play(self, path: Path) -> None:
        self.stop()
        sound = None
        try:
            sound = SoundLoader.load(str(path))
        except Exception:
            sound = None
        if sound is not None:
            self._sound = sound
            sound.play()
            return
        if self._android_play(path):
            return
        raise RuntimeError(f"无法播放：{path.name}")

    def _android_play(self, path: Path) -> bool:
        try:
            from jnius import autoclass  # 只有安卓上才有
        except Exception:
            return False
        try:
            media_player = autoclass("android.media.MediaPlayer")
            player = media_player()
            player.setDataSource(str(path))
            player.prepare()
            player.start()
            self._media_player = player
            return True
        except Exception as exc:
            self.last_error = f"MediaPlayer 播放失败：{exc}"
            return False
