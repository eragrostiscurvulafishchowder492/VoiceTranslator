"""VAD 层：silero-vad（CPU）语音段检测 + 预缓冲。"""
import threading

import numpy as np

from app.common import get_logger

log = get_logger("pipeline.vad")

RATE = 16000
FRAME = 480  # 30ms @16k


class VoiceActivityDetector:
    """帧级 VAD。将连续语音帧组装为"语音段"。

    事件回调：
      on_segment(segment: np.ndarray[16k])   —— 完整语音段（含 pre-speech 缓冲）
      on_level(level)                        —— 当前帧电平（GUI 显示）
      on_vad_change(speaking: bool)
    """

    def __init__(self, threshold: float = 0.5,
                 min_speech_ms: int = 180,
                 silence_end_ms: int = 700,
                 pre_speech_ms: int = 250,
                 on_segment=None, on_level=None, on_vad_change=None):
        self.threshold = threshold
        self.min_speech_frames = max(1, int(min_speech_ms / 30))
        self.silence_end_frames = max(1, int(silence_end_ms / 30))
        self.pre_speech_frames = int(pre_speech_ms / 30)
        self.on_segment = on_segment
        self.on_level = on_level
        self.on_vad_change = on_vad_change
        self._model = None
        self._model_lock = threading.Lock()
        self.speaking = False
        self._collecting = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._segment: list[np.ndarray] = []
        self._pre_buf: list[np.ndarray] = []
        self._pre_total = 0
        self.segments = 0

    def _get_model(self):
        if self._model is None:
            with self._model_lock:
                if self._model is None:
                    import torch
                    torch.set_num_threads(1)
                    from silero_vad import load_silero_vad
                    self._model = load_silero_vad()
                    self._model.reset_states()
                    log.info("silero-vad loaded")
        return self._model

    def set_threshold(self, t: float) -> None:
        self.threshold = t

    def force_end(self) -> None:
        """PTT 松开 / 用户强制断句：立即结束当前段（含不足 min 长度的）。"""
        self._flush_segment(force=True)

    def reset(self) -> None:
        self._collecting = False
        self._speech_frames = 0
        self._silence_frames = 0
        self._segment = []
        self._pre_buf = []
        self._pre_total = 0
        self.speaking = False

    def _push_pre(self, frame: np.ndarray) -> None:
        self._pre_buf.append(frame)
        self._pre_total += 1
        while self._pre_total > self.pre_speech_frames:
            self._pre_buf.pop(0)
            self._pre_total -= 1

    def _pop_pre(self) -> list[np.ndarray]:
        out = self._pre_buf
        self._pre_buf = []
        self._pre_total = 0
        return out

    def process(self, frame: np.ndarray, level: float = 0.0) -> None:
        if self.on_level:
            self.on_level(level)
        if len(frame) < FRAME:
            return
        try:
            model = self._get_model()
            prob = float(model(frame, 16000).item())
        except Exception as e:
            log.error("vad error: %s", e)
            return
        if prob >= self.threshold:
            if not self._collecting:
                self._collecting = True
                self._speech_frames = 0
                self._silence_frames = 0
                self._segment = self._pop_pre()
                self.speaking = True
                if self.on_vad_change:
                    self.on_vad_change(True)
            self._speech_frames += 1
            self._silence_frames = 0
            self._segment.append(frame)
        else:
            if self._collecting:
                self._silence_frames += 1
                self._segment.append(frame)
                if self._silence_frames >= self.silence_end_frames:
                    self._flush_segment()
            else:
                self._push_pre(frame)

    def _flush_segment(self, force: bool = False) -> None:
        frames = self._segment
        self._segment = []
        self._silence_frames = 0
        was_collecting = self._collecting
        self._collecting = False
        if was_collecting:
            self.speaking = False
            if self.on_vad_change:
                self.on_vad_change(False)
        if not frames:
            return
        if not force and self._speech_frames < self.min_speech_frames:
            return
        audio = np.concatenate(frames).astype(np.float32)
        self._speech_frames = 0
        self.segments += 1
        if self.on_segment:
            try:
                self.on_segment(audio)
            except Exception as e:
                log.error("on_segment error: %s", e)