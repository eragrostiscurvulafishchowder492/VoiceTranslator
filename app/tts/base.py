"""TTS 引擎统一接口。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np


@dataclass
class TTSStyle:
    """风格参数（Mutsumi-like 默认）。"""
    speed: float = 1.0          # 语速倍率（0.85~1.15）
    emotion: str = "calm"       # calm | neutral | soft
    energy: float = 1.0         # 能量/响度
    pitch: float = 0.0          # 音高偏移（semitones，尽力而为）
    breathiness: float = 0.0    # 气声（模型不支持时忽略）

    def to_dict(self) -> dict:
        return {"speed": self.speed, "emotion": self.emotion,
                "energy": self.energy, "pitch": self.pitch,
                "breathiness": self.breathiness}


class TTSEngine(ABC):
    """统一接口：load_reference / synthesize_stream / interrupt / unload。"""

    name: str = "base"
    sample_rate: int = 24000
    streaming: bool = False     # 是否支持 chunk 流式生成

    @abstractmethod
    def load_reference(self, ref_path: str, ref_text: str = "", profile: str = "default") -> None:
        """预计算并缓存参考音频 embedding。profile 用于缓存 key。"""

    @abstractmethod
    def synthesize_stream(self, text: str, style: TTSStyle | None = None) -> Iterator[np.ndarray]:
        """生成音频 chunk（float32 mono）。若引擎不支持流式，则 yield 整段。"""

    def synthesize(self, text: str, style: TTSStyle | None = None) -> np.ndarray:
        """非流式：拼接全部 chunk 返回。"""
        chunks = list(self.synthesize_stream(text, style))
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks).astype(np.float32)

    @abstractmethod
    def interrupt(self) -> None:
        """中止当前生成。"""

    def unload(self) -> None:
        """释放模型/显存。"""

    def reload_reference(self) -> None:
        """切换引擎或重启后重新加载 reference（子类缓存丢失时调用）。"""