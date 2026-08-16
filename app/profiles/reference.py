"""参考音频管理 + 自动质量检测。

- 导入：复制到 data/references/，分析质量（时长/RMS/clipping/SNR/silence/采样率/声道/BGM 提示）
- 多 profile：data/references/profiles.json
- 参考音频绝不联网上传。
"""
import json
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.common import ROOT, get_logger

log = get_logger("profiles")

REF_DIR = ROOT / "data" / "references"
PROFILES_JSON = REF_DIR / "profiles.json"


@dataclass
class RefAnalysis:
    duration_s: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    rms: float = 0.0
    peak: float = 0.0
    clipping_pct: float = 0.0
    silence_ratio: float = 0.0
    snr_db: float = 0.0
    bgm_suspected: bool = False
    warnings: list = field(default_factory=list)

    def score(self) -> tuple[str, str]:
        """返回 (overall, 说明)。"""
        ok = True
        notes = []
        if not (5.0 <= self.duration_s <= 30.0):
            ok = False
            notes.append(f"时长 {self.duration_s:.1f}s（推荐 5~30s）")
        if self.clipping_pct > 1.0:
            ok = False
            notes.append(f"削波 {self.clipping_pct:.1f}%")
        if self.silence_ratio > 0.3:
            notes.append(f"静音占 {self.silence_ratio * 100:.0f}%")
        if self.rms < 0.02:
            notes.append(f"音量偏低 RMS={self.rms:.3f}")
        if self.snr_db < 15:
            ok = False
            notes.append(f"信噪比低 {self.snr_db:.0f}dB")
        if self.bgm_suspected:
            notes.append("疑似有背景音乐/混响")
        if not notes:
            return "Excellent", "推荐直接使用"
        if ok:
            return "Good", "；".join(notes)
        return "Poor", "；".join(notes)


def analyze_reference(path: Path) -> RefAnalysis:
    """WAV 质量分析（本地）。"""
    import soundfile as sf
    a = RefAnalysis()
    try:
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        a.sample_rate = int(sr)
        a.channels = data.shape[1]
        mono = data.mean(axis=1) if data.shape[1] > 1 else data[:, 0]
        a.duration_s = len(mono) / sr
        a.peak = float(np.max(np.abs(mono)))
        a.rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
        # clipping: 接近 ±1 的样本比例
        if a.peak > 0:
            a.clipping_pct = float(np.mean(np.abs(mono) > 0.995) * 100)
        # silence ratio: 30ms 窗能量 < -60dB
        win = 0.03
        n = max(1, int(sr * win))
        nwin = len(mono) // n
        if nwin > 0:
            energy = mono[: nwin * n].reshape(nwin, n)
            rms_win = np.sqrt(np.mean(energy ** 2, axis=1))
            a.silence_ratio = float(np.mean(rms_win < 10 ** (-60 / 20)))
        # SNR 近似：top 10% 能量窗 vs bottom 10%
        if nwin > 20:
            rms_win = np.sort(rms_win)
            sig = rms_win[int(nwin * 0.9):]
            noi = rms_win[: int(nwin * 0.1)]
            sp = np.mean(sig) ** 2 + 1e-12
            np_ = np.mean(noi) ** 2 + 1e-12
            a.snr_db = float(10 * np.log10(sp / np_))
        # BGM 提示：峰度/频谱调制粗略检测（低可信度，仅提示）
        if len(mono) > sr * 5:
            spec = np.abs(np.fft.rfft(mono[: sr * 5]))
            freqs = np.fft.rfftfreq(sr * 5, 1 / sr)
            voice_band = np.sum(spec[(freqs > 300) & (freqs < 3400)]) + 1e-12
            low_band = np.sum(spec[(freqs > 60) & (freqs < 300)]) + 1e-12
            high_band = np.sum(spec[freqs > 6000]) + 1e-12
            if low_band / voice_band > 0.6 or high_band / voice_band > 0.15:
                a.bgm_suspected = True
    except Exception as e:
        log.error("analyze reference failed: %s", e)
        a.warnings.append(str(e))
    return a


class ReferenceManager:
    def __init__(self, ref_dir: Path | None = None):
        self.ref_dir = Path(ref_dir or REF_DIR)
        self.ref_dir.mkdir(parents=True, exist_ok=True)
        self.json_path = self.ref_dir / "profiles.json"
        self._profiles: dict = {}
        self.load()

    def load(self) -> dict:
        try:
            if self.json_path.exists():
                self._profiles = json.loads(self.json_path.read_text(encoding="utf-8"))
        except Exception as e:
            log.error("load profiles failed: %s", e)
            self._profiles = {}
        return self._profiles

    def save(self) -> None:
        self.json_path.write_text(
            json.dumps(self._profiles, ensure_ascii=False, indent=2), encoding="utf-8")

    def import_reference(self, src: str, name: str = "", ref_text: str = "") -> dict:
        """复制 wav 到 data/references/ 并注册 profile。返回 profile dict。"""
        src = Path(src)
        if not src.exists():
            raise FileNotFoundError(f"文件不存在: {src}")
        if not name:
            name = src.stem
        uid = uuid.uuid4().hex[:8]
        fname = f"{name}_{uid}.wav"
        dst = self.ref_dir / fname
        shutil.copy2(src, dst)
        analysis = analyze_reference(dst)
        overall, note = analysis.score()
        prof = {
            "id": uid,
            "name": name,
            "path": str(dst.relative_to(ROOT)),
            "text": ref_text,
            "analysis": {
                "duration_s": round(analysis.duration_s, 2),
                "sample_rate": analysis.sample_rate,
                "channels": analysis.channels,
                "rms": round(analysis.rms, 4),
                "clipping_pct": round(analysis.clipping_pct, 3),
                "silence_ratio": round(analysis.silence_ratio, 3),
                "snr_db": round(analysis.snr_db, 1),
                "bgm_suspected": analysis.bgm_suspected,
                "overall": overall,
                "note": note,
            },
        }
        self._profiles[uid] = prof
        self.save()
        log.info("reference imported: %s (%s)", dst, overall)
        return prof

    def list_profiles(self) -> list[dict]:
        return list(self._profiles.values())

    def get_profile(self, uid: str) -> dict | None:
        p = self._profiles.get(uid)
        if not p:
            return None
        return {**p, "path": str(ROOT / p["path"])}

    def delete_profile(self, uid: str) -> None:
        p = self._profiles.pop(uid, None)
        if p:
            try:
                (ROOT / p["path"]).unlink(missing_ok=True)
            except Exception:
                pass
            self.save()

    def update_text(self, uid: str, ref_text: str) -> None:
        if uid in self._profiles:
            self._profiles[uid]["text"] = ref_text
            self.save()