# tests/probe_asr_quality.py — 隔离 ASR 识别问题：TTS 音频 vs 真实音频
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deps" / "CosyVoice" / "third_party" / "Matcha-TTS"))

from app.asr.funasr import FunASREngine
from app.tts.base import TTSStyle
from app.tts.cosyvoice import CosyVoiceEngine
from app.profiles.reference import ReferenceManager

SENT = "我不知道应该怎么回答你。"


def run_asr(asr: FunASREngine, audio, label: str):
    asr.reset()
    partials = []
    idx = 0
    FRAME = 960
    while idx < len(audio):
        asr.push_audio(audio[idx: idx + FRAME])
        partials.append(asr.get_partial_text())
        idx += FRAME
    final = asr.finalize_segment()
    print(f"[{label}] final={final!r}  last_partial={partials[-1]!r}")
    return final


if __name__ == "__main__":
    asr = FunASREngine(device="cuda", chunk_size=[0, 10, 5])
    asr.start()

    mgr = ReferenceManager()
    prof = mgr.get_profile(mgr.list_profiles()[0]["id"])
    tts = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=10, fast_llm=True)
    tts.load_reference(prof["path"], prof.get("text", ""))
    audio = tts.synthesize(SENT, TTSStyle(speed=1.0, emotion="calm"))
    print(f"TTS 音频 {len(audio)/tts.sample_rate:.2f}s")
    run_asr(asr, audio, "TTS-audio")

    import numpy as np
    import soundfile as sf
    real, sr = sf.read(r"data/test_zh.wav", dtype="float32")
    if sr != 16000:
        import scipy.signal
        real = scipy.signal.resample_poly(real, 16000, sr)
    real = (real * 32768).astype(np.int16)
    run_asr(asr, real, "real-audio")

    asr.unload()
    tts.unload()