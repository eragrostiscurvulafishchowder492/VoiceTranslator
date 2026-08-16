"""示例插件 1：Audio Gain。"""
import math
import struct

from voice_plugin_sdk import AudioFrame, PluginContext, VoicePlugin

NODE = {
    "node_type": "gain.audio_gain",
    "display_name": "增益 (插件)",
    "category": "音频效果",
    "inputs": [{"name": "in", "port_type": "audio.pcm", "required": True}],
    "outputs": [{"name": "out", "port_type": "audio.pcm"}],
    "default_params": {"gain_db": 0.0},
    "params_schema": {
        "type": "object",
        "properties": {
            "gain_db": {"type": "number", "minimum": -40, "maximum": 40,
                        "default": 0, "ui:widget": "slider", "unit": "dB",
                        "ui:group": "基本", "runtime_modifiable": True},
        },
    },
    "estimated_vram_mb": 0,
}


class GainPlugin(VoicePlugin):
    def manifest(self):
        return {"node_types": [NODE]}

    async def process_audio(self, instance_id: str, frame: AudioFrame, ctx: PluginContext):
        params = ctx.params(instance_id)
        gain_db = float(params.get("gain_db", 0.0))
        if abs(gain_db) < 0.01:
            await ctx.emit_audio(instance_id, frame.samples, frame.sample_rate, frame.channels,
                                 end_of_utterance=frame.end_of_utterance)
            return
        g = 10.0 ** (gain_db / 20.0)
        n = len(frame.samples) // 4
        vals = struct.unpack(f"<{n}f", frame.samples)
        out = struct.pack(f"<{n}f", *(max(-1.0, min(1.0, v * g)) for v in vals))
        await ctx.emit_audio(instance_id, out, frame.sample_rate, frame.channels,
                             end_of_utterance=frame.end_of_utterance)


def create_plugin() -> VoicePlugin:
    return GainPlugin()
