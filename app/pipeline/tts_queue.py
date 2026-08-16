"""TTS 调度队列：GENERATING/PLAYING/INTERRUPTED/FLUSHING 状态机。

- 句子入队 → TTS Worker 逐个生成（streaming chunks 直接进播放）
- 自然停顿：按句末标点注入 pause
- interrupt / clear / mute 支持
"""
import queue
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from app.common import get_logger, now_ms

log = get_logger("pipeline.tts_queue")

PAUSE_MS = {"，": 0, "。": 1, "？": 1, "！": 1, "…": 2, "；": 0}  # 索引


@dataclass
class QueueItem:
    text: str
    seq: int
    created_ms: int = field(default_factory=now_ms)
    enqueued_ms: int = 0
    started_ms: int = 0
    finished_ms: int = 0
    status: str = "queued"   # queued | generating | done | interrupted | failed


class TTSQueue:
    IDLE = "IDLE"
    GENERATING = "GENERATING"
    PLAYING = "PLAYING"
    FLUSHING = "FLUSHING"
    INTERRUPTED = "INTERRUPTED"

    def __init__(self, engine, playback, pauses: dict | None = None,
                 on_state=None, on_item_done=None):
        """
        engine: TTSEngine 实例
        playback: PlaybackWorker
        pauses: {"comma": s, "sentence": s, "question": s, "ellipsis": s, "between": s}
        """
        self.engine = engine
        self.playback = playback
        self.pauses = pauses or {"comma": 0.15, "sentence": 0.35, "question": 0.4,
                                 "ellipsis": 0.6, "between": 0.5}
        self.on_state = on_state
        self.on_item_done = on_item_done
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._interrupt = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = self.IDLE
        self._seq = 0
        self._current: QueueItem | None = None
        self.stats = {"generated": 0, "failed": 0, "interrupted": 0, "total_chunks": 0}

    # ---------- control ----------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="TTSWorker")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.interrupt()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def push(self, text: str) -> None:
        with self._lock:
            self._seq += 1
            item = QueueItem(text=text, seq=self._seq)
            item.enqueued_ms = now_ms()
        self._q.put(item)

    def interrupt(self) -> None:
        self._interrupt.set()
        self.engine.interrupt()
        self.playback.interrupt()

    def clear(self) -> None:
        """清空队列（保留当前正在生成的，让其自然结束或丢弃）。"""
        while not self._q.empty():
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

    def emergency_mute(self, muted: bool) -> None:
        self.playback.set_muted(muted)

    def _set_state(self, s: str) -> None:
        with self._lock:
            self.state = s
        if self.on_state:
            try:
                self.on_state(s)
            except Exception:
                pass

    def _pause_for(self, text: str) -> float:
        last = text[-1] if text else ""
        if last == "…":
            return self.pauses.get("ellipsis", 0.6)
        if last in "？":
            return self.pauses.get("question", 0.4)
        if last in "。！":
            return self.pauses.get("sentence", 0.35)
        if last in "，、；":
            return self.pauses.get("comma", 0.15)
        return self.pauses.get("between", 0.5)

    # ---------- worker ----------
    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.1)
            except queue.Empty:
                continue
            self._current = item
            item.started_ms = now_ms()
            self._set_state(self.GENERATING)
            self._interrupt.clear()
            try:
                chunks = []
                ok = False
                try:
                    for chunk in self.engine.synthesize_stream(item.text):
                        if self._interrupt.is_set():
                            item.status = "interrupted"
                            self.stats["interrupted"] += 1
                            break
                        chunks.append(chunk)
                    else:
                        ok = True
                except Exception as e:
                    log.error("TTS generate failed for %r: %s", item.text, e)
                    item.status = "failed"
                    self.stats["failed"] += 1
                if ok and chunks:
                    audio = np.concatenate(chunks)
                    self.stats["generated"] += 1
                    self.stats["total_chunks"] += len(chunks)
                    # 句末自然停顿
                    pause = self._pause_for(item.text)
                    if pause > 0:
                        sil = np.zeros(int(pause * self.engine.sample_rate), dtype=np.float32)
                        audio = np.concatenate([audio, sil])
                    self._set_state(self.PLAYING)
                    self.playback.enqueue(audio, self.engine.sample_rate, flush=True)
                    item.finished_ms = now_ms()
                    item.status = "done"
            finally:
                if item.status not in ("done", "failed", "interrupted"):
                    item.status = "done"
                if self.on_item_done:
                    try:
                        self.on_item_done(item)
                    except Exception:
                        pass
                self._current = None
                self._set_state(self.IDLE)

    # ---------- stats ----------
    def queue_depth(self) -> int:
        return self._q.qsize()

    def current_text(self) -> str:
        return self._current.text if self._current else ""