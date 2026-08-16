"""智能断句：Stable Prefix 算法 + 语义切分。

输入：ASR partial 更新（每 600ms）与 VAD 段结束事件。
输出：稳定的完整句子（推入 TTS Queue）。

核心：连续 stable_rounds 轮保持不变的前缀才视为稳定；
     句子结束标点 / VAD 结束 / 字符上限 / 超时 任一触发即提交。
"""
import re
import threading
import time
from collections import deque

from app.common import get_logger

log = get_logger("pipeline.chunker")

END_PUNC = "。！？；…"
COMMA_PUNC = "，、：；"


class Segmenter:
    def __init__(self, stable_rounds: int = 4, max_chars: int = 26,
                 flush_timeout_ms: int = 1500,
                 on_sentence=None, on_partial=None, on_stable=None):
        """
        on_sentence(text)        提交完整句子
        on_partial(text, is_stable, stable_part)
        """
        self.stable_rounds = stable_rounds
        self.max_chars = max_chars
        self.flush_timeout_ms = flush_timeout_ms
        self.on_sentence = on_sentence
        self.on_partial = on_partial
        self.on_stable = on_stable
        self._history: deque[str] = deque(maxlen=20)
        self._committed = ""       # 已提交给 TTS 的文本（段内累计）
        self._stable = ""
        self._lock = threading.Lock()
        self._last_update = time.time()
        self.sentences = 0

    # ---------- public ----------
    def reset(self) -> None:
        with self._lock:
            self._history.clear()
            self._committed = ""
            self._stable = ""

    def update_partial(self, text: str) -> None:
        with self._lock:
            text = text.strip()
            if not text:
                return
            self._history.append(text)
            self._last_update = time.time()
            # 从历史中计算稳定前缀：出现在最近 N 轮中的公共前缀
            hist = list(self._history)
            if len(hist) >= self.stable_rounds:
                recent = hist[-self.stable_rounds:]
                common = recent[0]
                for s in recent[1:]:
                    i = 0
                    while i < min(len(common), len(s)) and common[i] == s[i]:
                        i += 1
                    common = common[:i]
                self._stable = common
            self._maybe_emit(hist)

    def sentence_ended(self) -> None:
        """VAD 语音段结束：整段强制提交。"""
        with self._lock:
            self._force_flush()

    def check_timeout(self) -> None:
        """定时器：超时强制 flush 当前稳定文本。"""
        with self._lock:
            if time.time() - self._last_update > self.flush_timeout_ms / 1000.0:
                self._force_flush()

    def force_flush(self) -> str:
        """PTT 松开/手动：立即提交。返回提交文本。"""
        with self._lock:
            return self._force_flush()

    # ---------- internal ----------
    def _maybe_emit(self, hist: list[str]) -> None:
        cur = hist[-1]
        # 去掉已提交部分
        new_part = self._drop_committed(cur)
        if not new_part:
            return
        # 1) 句子结束标点出现
        if any(p in new_part for p in END_PUNC):
            idx = _first_end_punc_idx(new_part)
            self._submit(new_part[: idx + 1])
            return
        # 2) 稳定前缀超过最大长度 → 在逗号或稳定边界切
        if len(self._stable) - len(self._committed) >= self.max_chars:
            seg = self._stable[len(self._committed):]
            cut = _last_comma_cut(seg) or len(seg)
            self._submit(seg[:cut])
            return
        self._emit_partial()

    def _force_flush(self) -> str:
        if not self._history:
            return ""
        cur = self._history[-1]
        new_part = self._drop_committed(cur)
        if new_part:
            self._submit(new_part, forced=True)
            return new_part
        return ""

    def _drop_committed(self, cur: str) -> str:
        c = self._committed
        if not c:
            return cur
        if cur.startswith(c):
            return cur[len(c):]
        # partial 修正导致前缀不一致 → 丢弃本段剩余
        log.debug("partial revised, dropping rest: committed=%r cur=%r", c, cur)
        self._committed = cur
        return ""

    def _submit(self, seg: str, forced: bool = False) -> None:
        seg = seg.strip()
        if not seg:
            return
        # 过滤纯标点
        if re.fullmatch(r"[，。！？；、…\s]+", seg):
            return
        self._committed += seg
        self.sentences += 1
        if self.on_sentence:
            try:
                self.on_sentence(seg)
            except Exception as e:
                log.error("on_sentence error: %s", e)
        self._emit_partial()

    def _emit_partial(self) -> None:
        if self.on_partial:
            try:
                stable = self._stable[len(self._committed):] if self._stable.startswith(self._committed) else ""
                self.on_partial(self._history[-1], bool(stable), stable)
            except Exception as e:
                log.error("on_partial error: %s", e)


def _first_end_punc_idx(s: str) -> int:
    for i, ch in enumerate(s):
        if ch in END_PUNC:
            return i
    return len(s) - 1


def _last_comma_cut(s: str) -> int | None:
    for i in range(len(s) - 1, -1, -1):
        if s[i] in COMMA_PUNC:
            return i + 1
    return None