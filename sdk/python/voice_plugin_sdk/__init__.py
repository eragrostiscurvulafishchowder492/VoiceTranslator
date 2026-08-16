"""Voice Studio Python Plugin SDK。

插件开发者继承 VoicePlugin 并实现需要的处理方法；用
`python -m voice_plugin_sdk.server --manifest-dir <dir> --port <port>` 启动 worker。
"""

from .base import (
    VoicePlugin, PluginContext, AudioFrame, TextEvent, TtsRequest, ControlSignal,
    EmitAudio,
)

__version__ = "1.0.0"
PROTOCOL_VERSION = "1.0"

__all__ = [
    "VoicePlugin", "PluginContext", "AudioFrame", "TextEvent",
    "TtsRequest", "ControlSignal", "EmitAudio", "PROTOCOL_VERSION",
]
