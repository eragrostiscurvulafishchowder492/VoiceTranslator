"""TTS 音频输出：播放队列 + 重采样 + crossfade + underrun 统计。"""
import queue
import threading
import time

import numpy as np
import sounddevice as sd
import soxr

from app.audio.dsp import AudioProc
from app.common import get_logger

log = get_logger("audio.output")


class PlaybackWorker:
    """Playback 线程。接收 (audio:np.ndarray, is_last) 帧。

    行为：
    - 队列累积音频块；当队列深度 >= chunk 时开始播放（保证生成间隙不吞音）。
    - 块间 5ms crossfade；块尾 fade-out 防 click。
    - 支持 interrupt（清空队列并停止当前块）、mute、音量。
    """

    def __init__(self, device_index: int, sample_rate: int = 48000):
        self.device_index = device_index
        self.out_sr = sample_rate
        self.chunk_gap_ms = 40.0        # 攒够再播，避免生成间隙导致爆音
        self.q: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._interrupt = threading.Event()
        self._muted = threading.Event()
        self._thread: threading.Thread | None = None
        self.volume = 1.0
        self.underruns = 0
        self.started_chunks = 0
        self._pending = np.zeros(0, dtype=np.float32)
        self._last_chunk_t = 0.0
        self._playing = False
        self.device_sr = sample_rate
        self._lock = threading.Lock()

    def _open_stream(self):
        info = sd.query_devices(self.device_index)
        self.device_sr = int(info.get("default_samplerate") or self.out_sr)
        self._stream = sd.OutputStream(
            samplerate=self.device_sr, channels=1, dtype="float32",
            device=self.device_index, latency="low",
        )
        self._stream.start()
        self._resampler = None
        log.info("output stream opened: dev=%d sr=%d", self.device_index, self.device_sr)

    def _resample(self, x: np.ndarray, src_sr: int) -> np.ndarray:
        if src_sr == self.device_sr:
            return x
        if self._resampler is None or getattr(self._resampler, "_src", None) != src_sr:
            self._resampler = soxr.ResampleStream(src_sr, self.device_sr, 1, dtype="float32", quality="HQ")
            self._resampler._src = src_sr
        try:
            return self._resampler.resample_chunk(x)
        except Exception:
            self._resampler = soxr.ResampleStream(src_sr, self.device_sr, 1, dtype="float32", quality="HQ")
            self._resampler._src = src_sr
            return self._resampler.resample_chunk(x)

    def enqueue(self, audio: np.ndarray, src_sr: int, flush: bool = False) -> None:
        self.q.put((audio.astype(np.float32), int(src_sr), bool(flush)))

    def interrupt(self) -> None:
        self._interrupt.set()
        self.clear_queue()

    def clear_queue(self) -> None:
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def set_muted(self, m: bool) -> None:
        if m:
            self._muted.set()
            self.clear_queue()
            self._pending = np.zeros(0, dtype=np.float32)
        else:
            self._muted.clear()

    def set_volume(self, v: float) -> None:
        self.volume = max(0.0, min(2.0, v))

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="Playback")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.clear_queue()
        self._interrupt.set()
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        try:
            if getattr(self, "_stream", None):
                self._stream.stop()
                self._stream.close()
                self._stream = None
        except Exception:
            pass

    def _run(self) -> None:
        try:
            self._open_stream()
        except Exception as e:
            log.error("playback stream open failed: %s", e)
            self._stop.set()
            return
        buf = np.zeros(0, dtype=np.float32)
        try:
            while not self._stop.is_set():
                if self._interrupt.is_set():
                    self._interrupt.clear()
                    self._pending = np.zeros(0, dtype=np.float32)
                    try:
                        self._stream.stop()
                        self._stream.start()
                    except Exception:
                        pass
                try:
                    audio, src_sr, flush = self.q.get(timeout=0.05)
                except queue.Empty:
                    if buf.size == 0:
                        continue
                    # 队列空但仍有残余缓冲：直接播完
                    buf = self._drain(buf)
                else:
                    self.started_chunks += 1
                    x = self._resample(audio, src_sr)
                    if flush:
                        x = AudioProc.fade_in_out(x, 32)
                    if buf.size:
                        fade = int(min(0.005 * self.device_sr, len(buf), len(x)))
                        buf, x = AudioProc.crossfade(buf, x, fade)
                    buf = np.concatenate([buf, x])
                    self._drain(buf)
        except Exception as e:
            log.error("playback thread error: %s", e)
        finally:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass

    def _drain(self, buf: np.ndarray) -> np.ndarray:
        if self._muted.is_set():
            return np.zeros(0, dtype=np.float32)
        x = AudioProc.normalize(buf) * self.volume
        try:
            self._stream.write(x)
        except Exception as e:
            log.error("stream write error: %s", e)
            self.underruns += 1
        return np.zeros(0, dtype=np.float32)

    @property
    def queue_depth(self) -> int:
        return self.q.qsize()