# tests/probe_asr_semantics.py — 裸模型 generate 语义：累积 or 差分
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deps" / "CosyVoice" / "third_party" / "Matcha-TTS"))

import numpy as np
import soundfile as sf

from app.asr.funasr import FunASREngine

out = Path("logs/probe_asr3.txt")
lines = []

real, sr = sf.read(r"data/test_zh.wav", dtype="float32")
if sr != 16000:
    import scipy.signal
    real = scipy.signal.resample_poly(real, 16000, sr)
real = (real * 32768).astype(np.int16)

asr = FunASREngine(device="cuda", chunk_size=[0, 10, 5])
asr.start()
m = asr._model
cache = {}
stride = asr.chunk_size[1] * 960
idx = 0
while idx < len(real):
    chunk = real[idx: idx + stride]
    idx += stride
    res = m.generate(input=chunk, cache=cache, is_final=False,
                     chunk_size=asr.chunk_size,
                     encoder_chunk_look_back=asr.enc_lb,
                     decoder_chunk_look_back=asr.dec_lb)
    lines.append(f"chunk{idx//stride}: {res[0]['text']!r}")
res = m.generate(input=np.zeros(960, dtype=np.float32), cache=cache, is_final=True,
                 chunk_size=asr.chunk_size,
                 encoder_chunk_look_back=asr.enc_lb,
                 decoder_chunk_look_back=asr.dec_lb)
lines.append(f"final-flush: {res[0]['text']!r}")

asr.unload()
out.write_text("\n".join(lines), encoding="utf-8")
print(f"written {out}")