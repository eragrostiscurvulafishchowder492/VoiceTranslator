# tests/probe_tokens3.py — 真实轨迹中逐 token 的 y_pred 对比（eager vs fast）
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import torch

from app.tts.base import TTSStyle
from app.tts.cosyvoice import CosyVoiceEngine

TEXT = "我不知道应该怎么回答你。"


def run(fast_llm: bool, n_keep: int = 6):
    eng = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=10, fast_llm=fast_llm)
    eng.load_reference(str(Path(r"data/test_zh.wav")), "今天天气不错，我们一起去公园散步吧。")
    llm = eng._model.model.llm
    orig_dec = llm.llm_decoder
    captured = []

    def spy_dec(x):
        captured.append(x.detach().clone())
        return orig_dec(x)

    llm.__dict__["llm_decoder"] = spy_dec
    style = TTSStyle(speed=1.0)
    chunks = list(eng.synthesize_stream(TEXT, style))
    dur = sum(len(c) / eng.sample_rate for c in chunks)
    h = torch.stack([c[0, -1] for c in captured[:n_keep]]).cpu()
    eng.unload()
    return dur, h


if __name__ == "__main__":
    d_e, h_e = run(False)
    d_f, h_f = run(True)
    print(f"eager audio={d_e:.2f}s  fast audio={d_f:.2f}s")
    for i in range(min(h_e.shape[0], h_f.shape[0])):
        diff = (h_e[i] - h_f[i]).abs()
        print(f"step{i}: max_abs_diff={diff.max().item():.8f}  same={torch.equal(h_e[i], h_f[i])}")