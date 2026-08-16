# tests/tts_cosyvoice_steady.py — CosyVoice3 稳态延迟测量（连续 3 句，忽略首句预热）
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import torch
import torchaudio

from app.tts.cosyvoice import CosyVoiceEngine
from app.tts.base import TTSStyle
from app.diagnostics.gpu import query_vram_mb, query_gpu_total_used_mb

SENTS = [
    "我不知道应该怎么回答你。",
    "这个办法听起来好像不错。",
    "你先坐下来慢慢说，我们再想想别的办法。",
]


def main():
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"data/test_zh.wav")
    ref_text = sys.argv[2] if len(sys.argv) > 2 else "今天天气不错，我们一起去公园散步吧。"

    eng = CosyVoiceEngine(device="cuda", fp16=True)
    eng.load_reference(str(wav), ref_text)
    style = TTSStyle(speed=1.0, emotion="calm")

    out_dir = Path(r"D:\_agents\VoiceTranslator\logs")
    for i, text in enumerate(SENTS):
        t0 = time.perf_counter()
        eng.ttfa_ms = 0
        chunks = list(eng.synthesize_stream(text, style))
        total = (time.perf_counter() - t0) * 1000
        audio = np.concatenate(chunks)
        dur = len(audio) / eng.sample_rate
        torchaudio.save(str(out_dir / f"steady_{i}.wav"),
                        torch.from_numpy(audio).unsqueeze(0), eng.sample_rate)
        print(f"[{i}] {text[:14]}... TTFA={eng.ttfa_ms}ms total={total:.0f}ms "
              f"audio={dur:.2f}s rtf={total/1000/dur:.2f} VRAM={query_vram_mb()}MB "
              f"card={query_gpu_total_used_mb()}MB")
    eng.unload()
    print("STEADY_DONE")


if __name__ == "__main__":
    main()