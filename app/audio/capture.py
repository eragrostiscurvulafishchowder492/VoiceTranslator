"""实时音频采集：sounddevice (WASAPI) 回调 → RingBuffer + DSP + VAD 推送。"""
import threading
import time

import numpy as np
import sounddevice as sd
import soxr

from app.audio.dsp import MicDSP
from app.audio.ringbuffer import RingBuffer
from app.common import get_logger

log = get_logger("audio.capture")

RATE_IN = 48000
RATE_ASR = 16000


class AudioCapture:
    """回调线程内做 DSP + VAD，音频帧推给回调 on_frame(frame16k, level)。"""

    def __init__(self, device_index: int, block_ms: int = 20,
                 gain_db: float = 0.0, on_frame=None, on_error=None):
        self.device_index = device_index
        self.block = max(10, int(block_ms))
        self.on_frame = on_frame          # fn(frame_16k: np.ndarray) 分帧给 VAD
        self.on_error = on_error
        self.stream: sd.InputStream | None = None
        self._running = False
        self._lock = threading.Lock()
        self._dsp = MicDSP(RATE_IN, gain_db=gain_db)
        self._resampler = None
        self._resampler_lock = threading.Lock()
        self.frames_dropped = 0
        self.overflows = 0
        self._last_block_t = 0.0
        self.level = 0.0

    def set_gain_db(self, db: float) -> None:
        self._dsp.set_gain_db(db)

    def _resample(self, x: np.ndarray) -> np.ndarray:
        with self._resampler_lock:
            if self._resampler is None:
                self._resampler = soxr.ResampleStream(RATE_IN, RATE_ASR, 1, dtype="float32", quality="HQ")
            try:
                out = self._resampler.resample_chunk(x)
            except Exception:
                # 重采样器异常时重建
                self._resampler = soxr.ResampleStream(RATE_IN, RATE_ASR, 1, dtype="float32", quality="HQ")
                out = self._resampler.resample_chunk(x)
        return out

    def _callback(self, indata: np.ndarray, frames: int, time_info, status) -> None:
        if status:
            if status.input_overflow:
                self.overflows += 1
            return
        if not self._running:
            return
        x = indata[:, 0].astype(np.float32)
        self.level = float(np.max(np.abs(x)))
        try:
            x = self._dsp.process(x)
        except Exception as e:
            log.error("dsp error: %s", e)
            return
        try:
            frame16 = self._resample(x)
        except Exception as e:
            log.error("resample error: %s", e)
            return
        if frame16.size and self.on_frame is not None:
            try:
                self.on_frame(frame16, float(np.max(np.abs(x))))
            except Exception as e:
                log.error("on_frame error: %s", e)

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            info = sd.query_devices(self.device_index)
            sr = int(info["default_samplerate"]) or RATE_IN
            block = int(sr * self.block / 1000.0)
            try:
                self.stream = sd.InputStream(
                    samplerate=sr, channels=1, dtype="float32",
                    blocksize=block, device=self.device_index,
                    latency="low", callback=self._callback,
                )
                self.stream.start()
            except Exception as e:
                log.error("open input stream failed: %s", e)
                if self.on_error:
                    self.on_error(f"麦克风打开失败: {e}")
                return
            self._running = True
            log.info("capture started: dev=%s sr=%d block=%d", self.device_index, sr, block)

    def stop(self) -> None:
        with self._lock:
            if not self._running:
                return
            try:
                self.stream.stop()
                self.stream.close()
            except Exception as e:
                log.warning("stop capture: %s", e)
            self.stream = None
            self._running = False
            log.info("capture stopped")

    @property
    def running(self) -> bool:
        return self._running


class FakeCapture:
    """测试用：从 wav 循环喂入（模拟麦克风）。"""

    def __init__(self, wav_path: str, on_frame=None, speed: float = 1.0, loop: bool = True):
        import soundfile as sf
        self.data, sr = sf.read(wav_path, dtype="float32")
        if self.data.ndim > 1:
            self.data = self.data.mean(axis=1)
        self.sr = int(sr)
        self.on_frame = on_frame
        self.speed = speed
        self.loop = loop
        self._running = False
        self._thread = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        idx = 0
        while self._running:
            if self.sr != RATE_ASR:
                block = int(960 * self.sr / RATE_ASR)
            else:
                block = 960
            if idx + block > len(self.data):
                if not self.loop:
                    break
                idx = 0
                continue
            chunk = self.data[idx: idx + block]
            idx += block
            if self.on_frame:
                self.on_frame(chunk.astype(np.float32), float(np.max(np.abs(chunk))))
            time.sleep(960 / RATE_ASR / self.speed)

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)