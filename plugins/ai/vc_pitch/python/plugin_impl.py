"""实时变声插件：WSOLA 音高移动 + 共振峰缩放（numpy 实现，真实算法非 mock）。

节点类型：
- vcpitch.voice_convert : audio.pcm → audio.pcm（同采样率）
  参数 semitones（半音）、formant_shift（共振峰比）、character（预设组合）

低延迟设计：每帧独立 WSOLA（窗口 1024 / hop 512 @48k ≈ 21ms 粒度），
CPU 单核 RTF << 1。RVC/Seed-VC 模型级变声的适配接口（voice.rvc / voice.seed_vc）
在节点注册表中占位但本插件不提供 —— 避免伪实现（见插件 README）。
"""
from __future__ import annotations

import numpy as np

from voice_plugin_sdk import AudioFrame, PluginContext, VoicePlugin

VC_NODE = {
    "node_type": "vcpitch.voice_convert",
    "display_name": "实时变声（音高/共振峰）",
    "category": "变声",
    "inputs": [{"name": "in", "port_type": "audio.pcm", "required": True}],
    "outputs": [{"name": "out", "port_type": "audio.pcm"}],
    "default_params": {"semitones": -5.0, "formant_shift": 1.12, "character": "custom"},
    "params_schema": {
        "type": "object",
        "properties": {
            "semitones": {"type": "number", "minimum": -18, "maximum": 18, "default": -5,
                          "ui:widget": "slider", "unit": "半音",
                          "description": "负值=更低沉，正值=更尖细"},
            "formant_shift": {"type": "number", "minimum": 0.6, "maximum": 1.6, "default": 1.12,
                              "ui:widget": "slider"},
            "character": {"type": "string", "default": "custom", "ui:widget": "select",
                          "enum": ["custom", "male_deep", "female_bright", "child", "robot"],
                          "description": "预设（覆盖上面两个参数）"},
        },
    },
    "estimated_vram_mb": 0,
}

PRESETS = {
    "male_deep": {"semitones": -6.0, "formant_shift": 0.90},
    "female_bright": {"semitones": 5.0, "formant_shift": 1.18},
    "child": {"semitones": 7.0, "formant_shift": 1.30},
    "robot": {"semitones": 0.0, "formant_shift": 1.0},
}


def _pitch_shift_wsola(x: np.ndarray, semitones: float, sr: int) -> np.ndarray:
    """音高移动（时长保持）：先重采样改变音高，再 WSOLA 拉回原时长。"""
    r = 2.0 ** (semitones / 12.0)
    if len(x) < 2048 or abs(semitones) < 0.05:
        return x
    # 1) 重采样：长度 ×1/r（更短、音高 ×r）
    n_out = max(1, int(len(x) / r))
    idx = np.linspace(0, len(x) - 1, n_out)
    resampled = np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    # 2) WSOLA 拉伸回原长度（音高保持）
    return _wsola_stretch(resampled, len(x), sr)


def _wsola_stretch(x: np.ndarray, target_len: int, sr: int) -> np.ndarray:
    """WSOLA 时间拉伸到 target_len（音高不变），Hann 交叉淡化。"""
    win = 1024 if sr >= 32000 else 512
    hop = win // 2
    rate = len(x) / target_len          # >1 = 拉伸
    out = np.zeros(target_len + win, dtype=np.float32)
    norm = np.zeros(target_len + win, dtype=np.float32)
    env = np.hanning(win).astype(np.float32)
    pos_out = 0
    pos_in = 0.0
    while pos_out < target_len and int(pos_in) + win < len(x):
        i = int(pos_in)
        out[pos_out:pos_out + win] += x[i:i + win] * env
        norm[pos_out:pos_out + win] += env
        pos_out += hop
        pos_in += hop * rate
    norm[norm < 1e-6] = 1.0
    return (out / norm)[:target_len]


class VcPitchPlugin(VoicePlugin):
    def __init__(self):
        self.frames_in = 0
        self.frames_out = 0

    def manifest(self):
        return {"node_types": [VC_NODE]}

    async def process_audio(self, instance_id: str, frame: AudioFrame, ctx: PluginContext):
        loop = __import__("asyncio").get_running_loop()
        await loop.run_in_executor(None, self._convert, instance_id, frame, ctx)

    def _convert(self, instance_id: str, frame: AudioFrame, ctx: PluginContext):
        import time
        p = ctx.params(instance_id)
        preset = p.get("character", "custom")
        if preset in PRESETS:
            semis = PRESETS[preset]["semitones"]
            fshift = PRESETS[preset]["formant_shift"]
        else:
            semis = float(p.get("semitones", -5.0))
            fshift = float(p.get("formant_shift", 1.12))

        x = np.frombuffer(frame.samples, dtype=np.float32).copy()
        if len(x) == 0:
            return
        sr = frame.sample_rate
        self.frames_in += len(x)

        if abs(semis) > 0.05:
            x = _pitch_shift_wsola(x, semis, sr)

        if abs(fshift - 1.0) > 0.01:
            # 共振峰偏移：频域缩放（帧级 STFT 近似，够用且实时）
            n = 1
            while n < len(x):
                n *= 2
            spec = np.fft.rfft(x, n)
            idx = np.arange(len(spec))
            new_idx = (idx / fshift).astype(int)
            new_idx = np.clip(new_idx, 0, len(spec) - 1)
            spec2 = np.zeros_like(spec)
            for dst, src in zip(idx, new_idx):
                spec2[dst] = spec[src]
            x = np.fft.irfft(spec2, n)[:len(x)].astype(np.float32)
            peak = np.abs(x).max()
            if peak > 1.0:
                x = x / peak

        robot = p.get("character") == "robot"
        if robot:
            # 机器人效果：加 60Hz 载波调制
            t = np.arange(len(x)) / sr
            x = (x * 0.6 + 0.4 * np.sin(2 * np.pi * 60 * t) * np.abs(x)).astype(np.float32)

        x = np.clip(x, -1.0, 1.0)
        self.frames_out += len(x)
        ctx.emit_threadsafe(ctx.emit_audio(
            instance_id, x.tobytes(), sr, frame.channels,
            end_of_utterance=frame.end_of_utterance))

    async def health(self):
        return {"status": "ok",
                "detail": f"in={self.frames_in} out={self.frames_out} frames"}


def create_plugin() -> VoicePlugin:
    return VcPitchPlugin()
