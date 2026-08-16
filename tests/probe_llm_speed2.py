# tests/probe_llm_speed2.py — 对照实验：fp16 vs fp32、hidden_states 开销、triton
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import torch

from app.tts.cosyvoice import CosyVoiceEngine


def bench(qwen, emb, dev, n=30, hidden=True, label=""):
    def fwd_step(xs1, m1, cache):
        outs = qwen(inputs_embeds=xs1, attention_mask=m1, output_hidden_states=hidden, use_cache=True, past_key_values=cache)
        if hidden:
            return outs.hidden_states[-1], outs.past_key_values
        return outs, outs.past_key_values

    m1 = torch.tril(torch.ones((1, 1, 1), device=dev)).to(torch.bool)
    with torch.inference_mode(), torch.cuda.amp.autocast(True):
        cache = None
        for _ in range(5):
            _, cache = fwd_step(emb(torch.tensor([[7]], device=dev)), m1, cache)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        cache = None
        for _ in range(n):
            _, cache = fwd_step(emb(torch.tensor([[7]], device=dev)), m1, cache)
        torch.cuda.synchronize()
        print(f"{label}: {(time.perf_counter() - t0) / n * 1000:.1f} ms/step")


def main():
    eng = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=10)
    eng.load_reference(str(Path(r"data/test_zh.wav")), "今天天气不错，我们一起去公园散步吧。")
    qwen = eng._model.model.llm.llm.model
    emb = qwen.model.embed_tokens
    dev = next(qwen.parameters()).device
    print("base dtype:", emb.weight.dtype)
    bench(qwen, emb, dev, hidden=True, label="fp32 + hidden_states")
    bench(qwen, emb, dev, hidden=False, label="fp32 + no hidden_states")
    qwen.half()
    emb = qwen.model.embed_tokens
    bench(qwen, emb, dev, hidden=True, label="fp16 + hidden_states")
    bench(qwen, emb, dev, hidden=False, label="fp16 + no hidden_states")
    try:
        import triton
        print("triton available:", triton.__version__)
    except Exception as e:
        print("triton NOT available:", type(e).__name__)
    eng.unload()


if __name__ == "__main__":
    main()