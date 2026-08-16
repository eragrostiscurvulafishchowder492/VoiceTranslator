"""ASR 引擎统一接口。第一版：FunASR paraformer-zh-streaming。"""
from abc import ABC, abstractmethod

import numpy as np


class ASREngine(ABC):
    """统一接口：start / push_audio / get_partial_text / finalize_segment / reset。"""

    name: str = "base"

    @abstractmethod
    def start(self) -> None:
        """加载模型，进入就绪。"""

    @abstractmethod
    def push_audio(self, audio: np.ndarray) -> None:
        """送入 16k 音频帧（VAD 段内增量）。"""

    @abstractmethod
    def get_partial_text(self) -> str:
        """当前 partial 文本（增量、未稳定）。"""

    @abstractmethod
    def finalize_segment(self) -> str:
        """强制输出当前段最终文本并重置段状态。"""

    @abstractmethod
    def reset(self) -> None:
        """放弃当前段。"""

    def unload(self) -> None:
        """释放模型（引擎切换/退出时）。"""