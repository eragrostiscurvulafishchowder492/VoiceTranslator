"""真实 AI 插件：FunASR 流式中文识别 + silero VAD。

复用仓库 app/asr/funasr.py 引擎（增量重叠合并已在其中实现并验证）。
节点类型：
- funasr.streaming_asr : audio.pcm → text.partial / text.final
- funasr.vad           : audio.pcm → speech.vad_event(control) + 分段 audio.pcm
"""
from __future__ import annotations

import asyncio
import gc
import time

import numpy as np

from voice_plugin_sdk import AudioFrame, ControlSignal, PluginContext, VoicePlugin

ASR_NODE = {
    "node_type": "funasr.streaming_asr",
    "display_name": "流式中文识别",
    "category": "ASR",
    "inputs": [{"name": "in", "port_type": "audio.pcm", "required": True}],
    "outputs": [{"name": "partial", "port_type": "text.partial"},
                {"name": "final", "port_type": "text.final"}],
    "default_params": {"hotwords": ""},
    "params_schema": {
        "type": "object",
        "properties": {
            "hotwords": {"type": "string", "default": "",
                         "description": "热词（空格分隔），缓解同音字误差"},
        },
    },
    "estimated_vram_mb": 900,
}

VAD_NODE = {
    "node_type": "funasr.vad",
    "display_name": "VAD 语音检测",
    "category": "ASR",
    "inputs": [{"name": "in", "port_type": "audio.pcm", "required": True}],
    "outputs": [{"name": "control", "port_type": "control.signal"},
                {"name": "segment", "port_type": "audio.pcm"}],
    "default_params": {"threshold": 0.5},
    "params_schema": {
        "type": "object",
        "properties": {
            "threshold": {"type": "number", "minimum": 0.1, "maximum": 0.9, "default": 0.5,
                          "ui:widget": "slider", "runtime_modifiable": True},
        },
    },
    "estimated_vram_mb": 50,
}


def _resample_to_16k(audio: np.ndarray, rate: int) -> np.ndarray:
    if rate == 16000:
        return audio
    import soxr
    return soxr.resample(audio, rate, 16000)


class FunASRPlugin(VoicePlugin):
    def __init__(self):
        self._asr_engine = None
        self._asr_buf = np.zeros(0, dtype=np.float32)
        self._asr_seq = 0
        self._last_partial = ""
        self._recv_frames = 0
        self._vad = None
        self.in_speech = False
        self._device = "cpu"
        self._load_ms = 0

    def manifest(self):
        return {"node_types": [ASR_NODE, VAD_NODE]}

    async def initialize(self, ctx: PluginContext):
        try:
            import torch
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            self._device = "cpu"

    async def load_model(self, instance_id, model_id, model_path):
        t0 = time.perf_counter()
        try:
            if self._asr_engine is None:
                from app.asr.funasr import FunASREngine
                self._asr_engine = FunASREngine(device=self._device, chunk_size=[0, 10, 5])
                self._asr_engine.start()
                gc.collect()
            self._load_ms = int((time.perf_counter() - t0) * 1000)
            return {"ok": True, "error": "", "load_ms": self._load_ms, "vram_mb": 0}
        except Exception as e:
            import traceback
            return {"ok": False, "error": f"{e}\n{traceback.format_exc()}"}

    def _ensure_vad(self):
        if self._vad is None:
            import torch
            model, _utils = torch.hub.load(repo_or_dir="snakers4/silero-vad",
                                           model="silero_vad", trust_repo=True)
            self._vad = {"model": model, "buf": np.zeros(0, dtype=np.float32)}
        return self._vad

    async def process_audio(self, instance_id: str, frame: AudioFrame, ctx: PluginContext):
        node_type = ctx.params(instance_id).get("__node_type__", "")
        loop = asyncio.get_running_loop()
        if node_type == "funasr.vad":
            await loop.run_in_executor(None, self._vad_step, instance_id, frame, ctx)
        else:
            await loop.run_in_executor(None, self._asr_step, instance_id, frame, ctx)

    # ---------- ASR（线程池，阻塞推理不卡 gRPC 循环） ----------
    def _asr_step(self, instance_id, frame: AudioFrame, ctx: PluginContext):
        self._recv_frames = getattr(self, "_recv_frames", 0) + 1
        if self._recv_frames % 10 == 1:
            print(f"[funasr] recv #{self._recv_frames} frames, eos={frame.end_of_stream}", flush=True)
        if self._asr_engine is None:
            try:
                from app.asr.funasr import FunASREngine
                self._asr_engine = FunASREngine(device=self._device, chunk_size=[0, 10, 5])
                self._asr_engine.start()
                print(f"[funasr] engine ready after {self._recv_frames} frames", flush=True)
            except Exception as e:
                print(f"[funasr] engine load failed: {e}", flush=True)
                return
        audio = _resample_to_16k(np.frombuffer(frame.samples, dtype=np.float32), frame.sample_rate)
        self._asr_buf = np.concatenate([self._asr_buf, audio])
        stride = 960  # 600ms @16k
        while len(self._asr_buf) >= stride:
            chunk = self._asr_buf[:stride]
            self._asr_buf = self._asr_buf[stride:]
            self._asr_engine.push_audio(chunk)
            partial = self._asr_engine.get_partial_text()
            if partial and partial != self._last_partial:
                self._last_partial = partial
                self._asr_seq += 1
                print(f"[funasr] partial#{self._asr_seq}: {partial}", flush=True)
                ctx.emit_threadsafe(ctx.emit_text(
                    instance_id, partial, is_partial=True, sequence=self._asr_seq))
        if frame.end_of_utterance or frame.end_of_stream:
            print(f"[funasr] finalize on eos (recv={self._recv_frames})", flush=True)
            final = self._asr_engine.finalize_segment()
            print(f"[funasr] final={final!r}", flush=True)
            if final:
                self._asr_seq += 1
                ctx.emit_threadsafe(ctx.emit_text(
                    instance_id, final, is_final=True, sequence=self._asr_seq))

    # ---------- VAD ----------
    def _vad_step(self, instance_id, frame: AudioFrame, ctx: PluginContext):
        v = self._ensure_vad()
        import torch
        audio = _resample_to_16k(np.frombuffer(frame.samples, dtype=np.float32), frame.sample_rate)
        v["buf"] = np.concatenate([v["buf"], audio])
        thr = float(ctx.params(instance_id).get("threshold", 0.5))
        model = v["model"]
        while len(v["buf"]) >= 512:
            win = v["buf"][:512].copy()
            v["buf"] = v["buf"][512:]
            with torch.no_grad():
                conf = float(model(torch.from_numpy(win), 16000).item())
            was = self.in_speech
            self.in_speech = conf > thr
            if self.in_speech and not was:
                ctx.emit_threadsafe(ctx.emit_control(instance_id, "vad_start", {"confidence": conf}))
            elif not self.in_speech and was:
                ctx.emit_threadsafe(ctx.emit_control(instance_id, "vad_end", {"confidence": conf}))
            ctx.emit_threadsafe(ctx.emit_audio(instance_id, win.tobytes(), 16000))

    async def on_control(self, instance_id, signal: ControlSignal, ctx):
        if signal.signal in ("ptt_up", "flush") and self._asr_engine is not None:
            loop = asyncio.get_running_loop()
            final = await loop.run_in_executor(None, self._asr_engine.finalize_segment)
            if final:
                self._asr_seq += 1
                await ctx.emit_text(instance_id, final, is_final=True, sequence=self._asr_seq)

    async def health(self):
        st = "ok"
        detail = f"asr={'loaded' if self._asr_engine else 'lazy'} on {self._device}"
        return {"status": st, "detail": detail}

    async def shutdown(self):
        if self._asr_engine is not None:
            self._asr_engine.unload()
            self._asr_engine = None
        gc.collect()


def create_plugin() -> VoicePlugin:
    return FunASRPlugin()
