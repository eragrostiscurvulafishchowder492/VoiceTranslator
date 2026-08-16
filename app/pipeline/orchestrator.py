"""管线编排：Capture → VAD → ASR Worker → Segmenter → TTS Queue → Playback。

线程：
- GUI 主线程（外部）
- Capture 回调（sounddevice 线程内做 DSP+VAD，开销小）
- ASR Worker：流式推理（GPU）
- Segmenter：在 ASR 回调中执行（纯 CPU 字符串操作，足够快）
- TTS Worker（TTSQueue 内）
- Playback 线程（PlaybackWorker 内）
- 监控定时器：超时 flush、设备健康检查
"""
import queue
import threading
import time
from dataclasses import dataclass, field

import numpy as np

from app.audio.capture import AudioCapture
from app.audio.output import PlaybackWorker
from app.common import get_logger, now_ms
from app.pipeline.chunker import Segmenter
from app.pipeline.tts_queue import TTSQueue
from app.pipeline.vad import VoiceActivityDetector

log = get_logger("pipeline.orchestrator")

RATE_ASR = 16000
FRAME = 960  # 600ms @16k


@dataclass
class PipelineStats:
    segments: int = 0
    asr_partial_latency_ms: list = field(default_factory=list)
    asr_finalize_ms: list = field(default_factory=list)
    tts_ttfa_ms: list = field(default_factory=list)
    total_latency_ms: list = field(default_factory=list)
    underruns: int = 0
    dropped_frames: int = 0
    overflows: int = 0
    gpu_vram_mb: int = 0
    running: bool = False
    last_partial: str = ""
    last_stable: str = ""
    last_submitted: str = ""
    last_error: str = ""

    def snapshot(self) -> dict:
        def avg(x):
            return round(sum(x) / len(x), 0) if x else 0
        return {
            "segments": self.segments,
            "asr_partial_ms": avg(self.asr_partial_latency_ms[-50:]),
            "asr_finalize_ms": avg(self.asr_finalize_ms[-20:]),
            "tts_ttfa_ms": avg(self.tts_ttfa_ms[-20:]),
            "total_ms": avg(self.total_latency_ms[-20:]),
            "underruns": self.underruns,
            "overflows": self.overflows,
            "dropped_frames": self.dropped_frames,
            "gpu_vram_mb": self.gpu_vram_mb,
            "running": self.running,
            "last_partial": self.last_partial,
            "last_stable": self.last_stable,
            "last_submitted": self.last_submitted,
            "last_error": self.last_error,
        }


class Orchestrator:
    def __init__(self, settings, asr_engine_factory=None, tts_engine_factory=None,
                 gui_events=None):
        self.s = settings
        self.gui_events = gui_events or {}   # 回调集合：on_*, GUI 填充
        self.stats = PipelineStats()
        self._asr_factory = asr_engine_factory
        self._tts_factory = tts_engine_factory
        self._lock = threading.Lock()
        self._running = False

        # 组件（运行时创建）
        self.capture: AudioCapture | None = None
        self.vad: VoiceActivityDetector | None = None
        self.asr = None
        self.chunker: Segmenter | None = None
        self.tts_queue: TTSQueue | None = None
        self.playback: PlaybackWorker | None = None
        self._asr_thread: threading.Thread | None = None
        self._asr_q: queue.Queue = queue.Queue()
        self._asr_stop = threading.Event()
        self._watch_thread: threading.Thread | None = None
        self._ptt_active = False
        self._muted = False
        self._seg_start_ms = 0

    # ---------------- public control ----------------
    def start(self, mic_index: int, out_index: int, monitor_index: int | None) -> None:
        if self._running:
            return
        from app.asr.funasr import FunASREngine
        from app.tts.cosyvoice import CosyVoiceEngine
        from app.tts.fishspeech import FishSpeechEngine

        self._running = True
        self._asr_stop.clear()

        # ASR
        self.asr = FunASREngine(
            device=self.s.asr_device if self.s.vram_mode != "asr_cpu" else "cpu",
            model_dir="",
            chunk_size=self.s.asr_chunk_size,
            hotwords=self.s.asr_hotwords,
            punc_model=self.s.asr_punc_model,
            on_partial=self._on_partial,
            on_final=self._on_asr_final,
        )
        try:
            self.asr.start()
        except Exception as e:
            log.error("ASR start failed: %s", e)
            self._emit("on_error", f"ASR 加载失败: {e}")
            self._running = False
            return

        # 断句
        self.chunker = Segmenter(
            stable_rounds=self.s.stable_rounds,
            max_chars=self.s.max_segment_chars,
            flush_timeout_ms=self.s.flush_timeout_ms,
            on_sentence=self._on_sentence,
            on_partial=self._on_chunker_partial,
        )

        # TTS
        engine = self._create_engine(self.s.tts_engine)
        self.playback = PlaybackWorker(out_index, self.s.output_sample_rate)
        self.playback.start()
        self.tts_queue = TTSQueue(
            engine, self.playback, pauses=self.s.punctuation_pause,
            on_state=lambda st: self._emit("on_tts_state", st),
            on_item_done=self._on_tts_done,
        )
        self.tts_queue.start()

        # VAD
        self.vad = VoiceActivityDetector(
            threshold=self.s.vad_threshold,
            min_speech_ms=self.s.vad_min_speech_ms,
            silence_end_ms=self.s.vad_silence_end_ms,
            pre_speech_ms=self.s.vad_pre_speech_ms,
            on_segment=self._on_vad_segment,
            on_level=lambda lv: self._emit("on_level", lv),
            on_vad_change=lambda sp: self._emit("on_vad", sp),
        )

        # 采集
        self.capture = AudioCapture(
            mic_index, block_ms=self.s.input_block_ms,
            gain_db=self.s.input_gain_db,
            on_frame=self._on_frame,
            on_error=lambda msg: self._emit("on_error", msg),
        )
        self.capture.start()

        # worker + watchdog
        self._asr_thread = threading.Thread(target=self._asr_worker, daemon=True, name="ASRWorker")
        self._asr_thread.start()
        self._watch_thread = threading.Thread(target=self._watchdog, daemon=True, name="Watchdog")
        self._watch_thread.start()

        self.stats.running = True
        self._emit("on_state", "running")
        log.info("pipeline started: mic=%d out=%d", mic_index, out_index)

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._asr_stop.set()
        if self.capture:
            self.capture.stop()
        if self.tts_queue:
            self.tts_queue.stop()
        if self.playback:
            self.playback.stop()
        if self._asr_thread:
            self._asr_thread.join(timeout=3)
        if self.asr:
            self.asr.unload()
        self.stats.running = False
        self._emit("on_state", "stopped")
        log.info("pipeline stopped")

    # ---------------- PTT / mute ----------------
    def ptt_down(self) -> None:
        self._ptt_active = True
        if self.vad:
            self.vad.reset()
        self._emit("on_ptt", True)

    def ptt_up(self) -> None:
        self._ptt_active = False
        if self.vad:
            self.vad.force_end()
        if self.chunker:
            self.chunker.force_flush()
        if self.asr:
            try:
                self.asr.finalize_segment()
            except Exception as e:
                log.error("finalize on ptt_up: %s", e)
        self._emit("on_ptt", False)

    def toggle_mute(self) -> bool:
        self._muted = not self._muted
        if self.playback:
            self.playback.set_muted(self._muted)
        self._emit("on_mute", self._muted)
        return self._muted

    def interrupt(self) -> None:
        if self.tts_queue:
            self.tts_queue.interrupt()
        self._emit("on_interrupt", True)

    def clear_queue(self) -> None:
        if self.tts_queue:
            self.tts_queue.clear()
        self._emit("on_clear", True)

    def emergency_mute(self, m: bool) -> None:
        self._muted = m
        if self.playback:
            self.playback.set_muted(m)

    # ---------------- callbacks ----------------
    def _on_frame(self, frame: np.ndarray, level: float) -> None:
        if not self._running or self.vad is None:
            return
        try:
            self.vad.process(frame, level)
        except Exception as e:
            log.error("vad process: %s", e)

    def _on_vad_segment(self, segment: np.ndarray) -> None:
        """完整语音段：逐帧推给 ASR worker，段尾标记 finalize。"""
        if not self._running:
            return
        self.stats.segments += 1
        self._seg_start_ms = now_ms()
        self._asr_q.put(("audio", segment))

    def _on_partial(self, text: str) -> None:
        if self.chunker:
            self.chunker.update_partial(text)

    def _on_asr_final(self, text: str) -> None:
        if self.chunker:
            self.chunker.sentence_ended()
        self._emit("on_asr_final", text)

    def _on_chunker_partial(self, text: str, is_stable: bool, stable_part: str) -> None:
        self.stats.last_partial = text
        self.stats.last_stable = stable_part
        self._emit("on_text", {"partial": text, "stable": stable_part})

    def _on_sentence(self, text: str) -> None:
        from app.textnorm import normalize_chinese_text
        norm = normalize_chinese_text(text, mode=self.s.text_mode)
        self.stats.last_submitted = norm
        if self.tts_queue:
            self.tts_queue.push(norm)
        self._emit("on_sentence", norm)

    def _on_tts_done(self, item) -> None:
        if item.status == "done":
            # 总延迟：句子提交 → 开始播放（近似 = 生成时间 + 播放缓冲）
            total = item.finished_ms - item.created_ms if item.finished_ms else 0
            self.stats.total_latency_ms.append(total)
            self.stats.tts_ttfa_ms.append(getattr(self.tts_queue.engine, "ttfa_ms", 0))
        self._emit("on_tts_done", {"text": item.text, "status": item.status})

    # ---------------- ASR worker ----------------
    def _asr_worker(self) -> None:
        while not self._asr_stop.is_set():
            try:
                kind, data = self._asr_q.get(timeout=0.1)
            except queue.Empty:
                continue
            if not self._running:
                break
            try:
                if kind == "audio":
                    self._feed_asr(data)
                elif kind == "finalize":
                    t0 = now_ms()
                    final = self.asr.finalize_segment()
                    self.stats.asr_finalize_ms.append(now_ms() - t0)
            except Exception as e:
                log.error("ASR worker error: %s", e)
                self._emit("on_error", f"ASR worker: {e}")
                # 尝试重启 ASR
                try:
                    self.asr.unload()
                    self.asr.start()
                except Exception as e2:
                    log.error("ASR restart failed: %s", e2)

    def _feed_asr(self, segment: np.ndarray) -> None:
        if self.asr is None:
            return
        # 段内以 960 帧（600ms）为单位推
        idx = 0
        while idx + FRAME <= len(segment):
            t0 = now_ms()
            self.asr.push_audio(segment[idx: idx + FRAME])
            self.stats.asr_partial_latency_ms.append(now_ms() - t0)
            idx += FRAME
        if idx < len(segment):
            self.asr.push_audio(segment[idx:])
        # 段结束
        try:
            self.asr.finalize_segment()
        except Exception as e:
            log.error("finalize: %s", e)

    # ---------------- engine switching ----------------
    def _create_engine(self, name: str):
        from app.tts.cosyvoice import CosyVoiceEngine
        from app.tts.fishspeech import FishSpeechEngine
        if name == "fish":
            return FishSpeechEngine(device=self.s.tts_device)
        return CosyVoiceEngine(model_dir=self.s.tts_model_dir or "",
                               device=self.s.tts_device, fp16=True)

    def switch_tts_engine(self, name: str) -> None:
        if self.tts_queue is None:
            self.s.tts_engine = name
            return
        self.tts_queue.stop()
        self.tts_queue.engine.unload()
        engine = self._create_engine(name)
        ref = self.get_active_reference()
        if ref:
            engine.load_reference(ref["path"], ref.get("text", ""))
        self.tts_queue.engine = engine
        self.tts_queue.start()
        self.s.tts_engine = name
        log.info("TTS engine switched to %s", name)

    def get_active_reference(self) -> dict | None:
        from app.profiles.reference import ReferenceManager
        mgr = ReferenceManager()
        return mgr.get_profile(self.s.reference_profile)

    # ---------------- watchdog ----------------
    def _watchdog(self) -> None:
        while self._running:
            try:
                if self.chunker:
                    self.chunker.check_timeout()
                if self.playback:
                    self.stats.underruns = self.playback.underruns
                    self.stats.overflows = self.capture.overflows if self.capture else 0
                self._emit("on_tick", None)
            except Exception as e:
                log.error("watchdog: %s", e)
            time.sleep(0.2)

    # ---------------- helpers ----------------
    def _emit(self, name: str, payload):
        cb = self.gui_events.get(name)
        if cb:
            try:
                cb(payload)
            except Exception as e:
                log.error("gui callback %s: %s", name, e)