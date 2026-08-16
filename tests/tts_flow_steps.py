# tests/tts_flow_steps.py — flow 步数敏感性：10 vs 6 步（延迟/质量客观对比）
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

TEXT = "我不知道应该怎么回答你，这个办法听起来好像还不错。"


def main():
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"data/test_zh.wav")
    ref_text = sys.argv[2] if len(sys.argv) > 2 else "今天天气不错，我们一起去公园散步吧。"
    style = TTSStyle(speed=1.0, emotion="calm")
    out_dir = ROOT / "logs"
    audios = {}
    for steps in (10, 6):
        eng = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=steps)
        eng.load_reference(str(wav), ref_text)
        run(eng, TEXT, style)  # 预热
        ttfa, total, audio = run(eng, TEXT, style)
        audios[steps] = audio
        torchaudio.save(str(out_dir / f"flow_{steps}_steps.wav"),
                        torch.from_numpy(audio).unsqueeze(0), eng.sample_rate)
        print(f"steps={steps}: ttfa={ttfa}ms total={total:.0f}ms audio={len(audio)/24000:.2f}s")
        eng.unload()

    a10, a6 = audios[10], audios[6]
    n = min(len(a10), len(a6))
    diff = np.abs(a10[:n] - a6[:n])
    print(f"max_abs_diff={diff.max():.4f} mean_abs_diff={diff.mean():.4f} "
          f"corr={np.corrcoef(a10[:n], a6[:n])[0, 1]:.3f}")
    print("saved: logs/flow_10_steps.wav, logs/flow_6_steps.wav")


def run(eng, text, style):
    t0 = time.perf_counter()
    eng.ttfa_ms = 0
    chunks = list(eng.synthesize_stream(text, style))
    total = (time.perf_counter() - t0) * 1000
    audio = np.concatenate(chunks)
    return eng.ttfa_ms, total, audio


if __name__ == "__main__":
    main()