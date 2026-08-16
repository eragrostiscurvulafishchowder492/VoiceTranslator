"""VoicePlugin 基类与数据类型（十一.）。

生命周期：discover → validate → install → prepare_runtime → start_worker →
handshake → load → ready → process → interrupt → unload → shutdown。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Awaitable, Optional


@dataclass
class AudioFrame:
    """PCM 帧（内部 f32le；sample_rate/channels 标注原始格式）。"""
    stream_id: str = ""
    sequence: int = 0
    timestamp_ns: int = 0
    sample_rate: int = 48000
    channels: int = 1
    samples: bytes = b""          # f32le little-endian
    frame_count: int = 0
    end_of_stream: bool = False
    end_of_utterance: bool = False


@dataclass
class TextEvent:
    stream_id: str = ""
    segment_id: str = ""
    sequence: int = 0
    text: str = ""
    language: str = "zh"
    is_partial: bool = False
    is_final: bool = False
    stability: float = 1.0
    start_time: float = 0.0
    end_time: float = 0.0
    confidence: float = 1.0


@dataclass
class TtsRequest:
    request_id: str = ""
    text: str = ""
    language: str = "zh"
    voice_profile: str = ""
    style: str = ""
    speed: float = 1.0
    pitch: float = 1.0
    energy: float = 1.0
    priority: int = 0
    interrupt_mode: str = "QUEUE"


@dataclass
class ControlSignal:
    signal: str = ""      # vad_start / vad_end / ptt_down / ptt_up / flush / eos
    payload: dict = field(default_factory=dict)


@dataclass
class EmitAudio:
    samples: bytes        # f32le
    sample_rate: int
    channels: int = 1
    end_of_utterance: bool = False


class PluginContext:
    """每个 worker 进程一个；提供参数读取与输出发射。"""

    def __init__(self, emit: Callable[[str, object], Awaitable[None]]):
        self._emit = emit
        self.started_at = time.time()
        self.node_params: dict[str, dict] = {}   # instance_id -> params
        self.data_dir: str = ""
        self.loop: object = None                 # 主 asyncio loop（线程池回投用）

    def params(self, instance_id: str) -> dict:
        return self.node_params.get(instance_id, {})

    async def emit_audio(self, instance_id: str, samples: bytes, sample_rate: int,
                         channels: int = 1, end_of_utterance: bool = False) -> None:
        await self._emit(instance_id, EmitAudio(samples, sample_rate, channels, end_of_utterance))

    async def emit_text(self, instance_id: str, text: str, *, is_partial: bool = False,
                        is_final: bool = False, stability: float = 1.0,
                        confidence: float = 1.0, segment_id: str = "", sequence: int = 0) -> None:
        ev = TextEvent(text=text, is_partial=is_partial, is_final=is_final,
                       stability=stability, confidence=confidence,
                       segment_id=segment_id, sequence=sequence)
        await self._emit(instance_id, ev)

    async def emit_control(self, instance_id: str, signal: str, payload: dict | None = None) -> None:
        await self._emit(instance_id, ControlSignal(signal=signal, payload=payload or {}))

    def emit_threadsafe(self, coro) -> None:
        """工作线程（run_in_executor）中安全发射：ctx.emit_threadsafe(ctx.emit_audio(...))"""
        import asyncio as _a
        assert self.loop is not None, "ctx.loop 未设置"
        _a.run_coroutine_threadsafe(coro, self.loop)


class VoicePlugin:
    """插件基类。所有方法都有默认实现，按需覆盖。"""

    def manifest(self) -> dict:
        """运行时补充声明：node_types / models（TOML 已声明的部分会被合并覆盖）。"""
        return {}

    async def initialize(self, ctx: PluginContext) -> None:
        """worker 启动后、握手前调用一次。"""

    async def load_model(self, instance_id: str, model_id: str, model_path: str) -> dict:
        """加载/切换模型。返回 {"ok": bool, "error": str, "load_ms": int, "vram_mb": int}。"""
        return {"ok": True, "error": "", "load_ms": 0, "vram_mb": 0}

    async def process_audio(self, instance_id: str, frame: AudioFrame, ctx: PluginContext):
        """处理一帧音频。可用 await ctx.emit_* 发射输出（生成器形式也支持）。"""

    async def process_text(self, instance_id: str, event: TextEvent, ctx: PluginContext):
        """处理文本事件。"""

    async def process_tts(self, instance_id: str, request: TtsRequest, ctx: PluginContext) -> AsyncIterator[EmitAudio]:
        """流式 TTS：yield EmitAudio(...)。"""
        yield EmitAudio(samples=b"", sample_rate=48000)

    async def on_control(self, instance_id: str, signal: ControlSignal, ctx: PluginContext) -> None:
        """控制信号（PTT/flush/interrupt…）。"""

    async def interrupt(self, instance_id: str) -> None:
        """中断当前生成（尽快返回）。"""

    async def health(self) -> dict:
        """{"status": "ok"/"degraded"/"error", "detail": str}"""
        return {"status": "ok", "detail": ""}

    async def shutdown(self) -> None:
        """优雅停止。"""
