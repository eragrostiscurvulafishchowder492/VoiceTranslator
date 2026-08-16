"""麦克风前置 DSP：HPF + Noise Gate + Limiter + Gain（轻度，不破坏 ASR）。"""
import numpy as np
from scipy.signal import butter, sosfilt, sosfiltfilt


class MicDSP:
    """默认：HPF ~80Hz、Noise gate light、Limiter ON。"""

    def __init__(self, sample_rate: int = 48000,
                 gain_db: float = 0.0,
                 hpf_hz: float = 80.0,
                 gate_threshold: float = 0.004,
                 gate_attack_ms: float = 10.0,
                 gate_release_ms: float = 250.0,
                 limiter_db: float = -1.0):
        self.sr = sample_rate
        self.gain = 10.0 ** (gain_db / 20.0)
        self.gate_thr = gate_threshold
        self.limiter = 10.0 ** (limiter_db / 20.0)
        self._env = 0.0
        self._open = False
        self._att = np.exp(-1.0 / (gate_attack_ms / 1000.0 * sr))
        self._rel = np.exp(-1.0 / (gate_release_ms / 1000.0 * sr))
        sos = butter(2, hpf_hz, btype="highpass", fs=sr, output="sos")
        self._sos = sos

    def set_gain_db(self, db: float) -> None:
        self.gain = 10.0 ** (db / 20.0)

    def process(self, x: np.ndarray) -> np.ndarray:
        """x: float32 1D。返回处理后信号。"""
        y = sosfilt(self._sos, x)
        y = y * self.gain
        # noise gate with envelope follower
        peak = np.abs(y)
        out = np.empty_like(y)
        for i in range(len(y)):
            a = self._att if self._open else self._rel
            self._env = max(peak[i], self._env * a)
            if self._env > self.gate_thr:
                self._open = True
            elif self._env < self.gate_thr * 0.5:
                self._open = False
            out[i] = y[i] if self._open else 0.0
        # soft limiter
        out = np.tanh(out / self.limiter) * self.limiter
        return out.astype(np.float32)


class AudioProc:
    """播放端后处理：归一化、limiter、crossfade 工具。"""

    @staticmethod
    def normalize(x: np.ndarray, peak: float = 0.89) -> np.ndarray:
        m = np.max(np.abs(x)) if x.size else 0.0
        if m > 1e-6:
            g = min(peak / m, 4.0)
            x = x * g
        return np.tanh(x * 0.9).astype(np.float32)

    @staticmethod
    def crossfade(a: np.ndarray, b: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
        """返回 a 尾部淡出、b 头部淡入后的两段（便于拼接）。"""
        n = min(n, len(a), len(b))
        if n <= 0:
            return a, b
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        a = a.copy()
        b = b.copy()
        a[-n:] *= (1.0 - ramp)
        b[:n] *= ramp
        return a, b

    @staticmethod
    def fade_in_out(x: np.ndarray, n: int = 64) -> np.ndarray:
        n = min(n, len(x) // 2)
        if n <= 0:
            return x
        x = x.copy()
        ramp = np.linspace(0.0, 1.0, n, dtype=np.float32)
        x[:n] *= ramp
        x[-n:] *= ramp[::-1]
        return x