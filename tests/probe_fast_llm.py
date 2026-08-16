# tests/probe_fast_llm.py — 验证 fast_llm 与原生 forward_one_step 输出一致性 + 提速（同一 fp16 权重下对比）
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import torch

from app.tts.cosyvoice import CosyVoiceEngine
from app.tts.fast_llm import install_fast_llm


def main():
    eng = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=10)
    eng.load_reference(str(Path(r"data/test_zh.wav")), "今天天气不错，我们一起去公园散步吧。")
    encoder = eng._model.model.llm.llm
    install_fast_llm(encoder, fp16=True)
    orig = encoder.forward_one_step.__self__.forward_one_step if hasattr(encoder.forward_one_step, "__self__") else None
    orig = encoder.__class__.forward_one_step.__get__(encoder)  # original method (class-level, bound)
    dev = next(encoder.parameters()).device
    emb = encoder.model.model.embed_tokens

    def run(fn, tokens, masks):
        cache = None
        outs = []
        with torch.inference_mode():
            for tok in tokens:
                h, cache = fn(emb(torch.tensor([[tok]], device=dev)), masks, cache)
                outs.append(h.float().cpu())
        return torch.stack(outs, dim=1)

    tokens = [7, 21, 33, 45, 99, 150, 200, 300]
    mask3d = torch.tril(torch.ones((1, 1, 1), device=dev)).to(torch.bool)
    print("orig type:", type(orig))
    r1 = orig(emb(torch.tensor([[7]], device=dev)), mask3d, None)
    print("orig first call ->", type(r1))
    ref = run(orig, tokens, mask3d)
    fast = run(encoder.forward_one_step, tokens, None)
    diff = (ref - fast).abs()
    print(f"same-dtype hidden: max_abs_diff={diff.max().item():.5f} mean={diff.mean().item():.6f}")

    m1 = torch.tril(torch.ones((1, 1, 1), device=dev)).to(torch.bool)
    with torch.inference_mode():
        for fn, label in ((orig, "orig"), (encoder.forward_one_step, "fast")):
            cache = None
            for _ in range(5):
                h, cache = fn(emb(torch.tensor([[7]], device=dev)), m1, cache)
            torch.cuda.synchronize()
            t0 = time.perf_counter()
            cache = None
            for _ in range(50):
                h, cache = fn(emb(torch.tensor([[7]], device=dev)), m1, cache)
            torch.cuda.synchronize()
            print(f"{label} single-token step: {(time.perf_counter() - t0) / 50 * 1000:.1f} ms/step")
    eng.unload()


if __name__ == "__main__":
    main()