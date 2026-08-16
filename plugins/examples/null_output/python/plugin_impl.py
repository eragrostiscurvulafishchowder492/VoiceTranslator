"""示例插件 4：Null Audio Output（丢弃所有输入帧，统计帧数）。"""
from voice_plugin_sdk import AudioFrame, PluginContext, VoicePlugin

NODE = {
    "node_type": "null.audio_output",
    "display_name": "空输出",
    "category": "输出",
    "inputs": [{"name": "in", "port_type": "audio.pcm", "required": True}],
    "outputs": [],
    "default_params": {},
    "estimated_vram_mb": 0,
}


class NullOutputPlugin(VoicePlugin):
    def __init__(self):
        self.frames = 0
        self.bytes_total = 0

    def manifest(self):
        return {"node_types": [NODE]}

    async def process_audio(self, instance_id: str, frame: AudioFrame, ctx: PluginContext):
        self.frames += 1
        self.bytes_total += len(frame.samples)

    async def health(self):
        return {"status": "ok", "detail": f"dropped {self.frames} frames / {self.bytes_total} bytes"}


def create_plugin() -> VoicePlugin:
    return NullOutputPlugin()
