# tests/probe_asr_quality2.py — dump 码点精确定位乱码来源
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deps" / "CosyVoice" / "third_party" / "Matcha-TTS"))

import numpy as np
import soundfile as sf

from app.asr.funasr import FunASREngine
from app.tts.base import TTSStyle
from app.tts.cosyvoice import CosyVoiceEngine
from app.profiles.reference import ReferenceManager

out = Path("logs/probe_asr2.txt")
lines = []


def dump(label, s):
    lines.append(f"[{label}] len={len(s)} codepoints={[hex(ord(c)) for c in s]} repr={s!r}")


def run_asr(asr: FunASREngine, audio, label: str):
    asr.reset()
    partials = []
    idx = 0
    FRAME = 960
    while idx < len(audio):
        asr.push_audio(audio[idx: idx + FRAME])
        p = asr.get_partial_text()
        if not partials or p != partials[-1]:
            partials.append(p)
        idx += FRAME
    final = asr.finalize_segment()
    dump(label + "-final", final)
    for i, p in enumerate(partials):
        dump(f"{label}-partial{i}", p)


if __name__ == "__main__":
    asr = FunASREngine(device="cuda", chunk_size=[0, 10, 5])
    asr.start()

    mgr = ReferenceManager()
    prof = mgr.get_profile(mgr.list_profiles()[0]["id"])
    tts = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=10, fast_llm=True)
    tts.load_reference(prof["path"], prof.get("text", ""))
    audio = tts.synthesize(SENT := "我不知道应该怎么回答你。", TTSStyle(speed=1.0, emotion="calm"))
    lines.append(f"TTS 音频 {len(audio)/tts.sample_rate:.2f}s")
    run_asr(asr, audio, "TTS")

    real, sr = sf.read(r"data/test_zh.wav", dtype="float32")
    if sr != 16000:
        import scipy.signal
        real = scipy.signal.resample_poly(real, 16000, sr)
    real = (real * 32768).astype(np.int16)
    run_asr(asr, real, "REAL")

    asr.unload()
    tts.unload()
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"written {out}")