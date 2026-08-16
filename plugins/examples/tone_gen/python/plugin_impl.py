"""示例插件 3：测试音发生器（仅标准库；演示独立 venv 隔离环境）。"""
import asyncio
import math
import struct
import time

from voice_plugin_sdk import PluginContext, VoicePlugin

NODE = {
    "node_type": "tone.generator",
    "display_name": "测试音发生器",
    "category": "输入",
    "inputs": [],
    "outputs": [{"name": "out", "port_type": "audio.pcm", "sample_rate": 48000, "channels": 1}],
    "default_params": {"freq": 440.0, "duration_s": 10.0, "interval_s": 3.0, "amplitude": 0.3},
    "params_schema": {
        "type": "object",
        "properties": {
            "freq": {"type": "number", "minimum": 20, "maximum": 20000, "default": 440,
                     "ui:widget": "slider", "unit": "Hz"},
            "duration_s": {"type": "number", "minimum": 0.1, "maximum": 60, "default": 10},
            "interval_s": {"type": "number", "minimum": 0.5, "maximum": 60, "default": 3},
            "amplitude": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.3},
        },
    },
    "estimated_vram_mb": 0,
}


class ToneGenPlugin(VoicePlugin):
    def __init__(self):
        self._running = {}
        self._tasks = {}

    def manifest(self):
        return {"node_types": [NODE]}

    async def on_control(self, instance_id, signal, ctx):
        if signal.signal == "ptt_down" or signal.signal == "tone_start":
            if instance_id not in self._tasks:
                self._tasks[instance_id] = asyncio.create_task(self._loop(instance_id, ctx))
        elif signal.signal in ("ptt_up", "tone_stop", "flush"):
            t = self._tasks.pop(instance_id, None)
            if t:
                t.cancel()

    async def _loop(self, instance_id, ctx):
        p = ctx.params(instance_id)
        freq = float(p.get("freq", 440.0))
        dur = float(p.get("duration_s", 10.0))
        interval = float(p.get("interval_s", 3.0))
        amp = float(p.get("amplitude", 0.3))
        try:
            while True:
                t0 = time.perf_counter()
                phase = 0.0
                while time.perf_counter() - t0 < dur:
                    n = 480  # 10ms
                    chunk = bytearray()
                    two_pi = 2 * math.pi
                    for _ in range(n):
                        phase = (phase + two_pi * freq / 48000.0) % two_pi
                        chunk += struct.pack("<f", amp * math.sin(phase))
                    await ctx.emit_audio(instance_id, bytes(chunk), 48000)
                    await asyncio.sleep(0.009)
                await ctx.emit_audio(instance_id, b"", 48000, end_of_utterance=True)
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def shutdown(self):
        for t in self._tasks.values():
            t.cancel()


def create_plugin() -> VoicePlugin:
    return ToneGenPlugin()
