# tests/probe_llm_speed.py — 直接基准 Qwen2 forward_one_step 每 token 耗时
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import torch

from app.tts.cosyvoice import CosyVoiceEngine


def main():
    eng = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=10)
    eng.load_reference(str(Path(r"data/test_zh.wav")), "今天天气不错，我们一起去公园散步吧。")
    qwen = eng._model.model.llm.llm.model
    emb = qwen.model.embed_tokens
    dev = next(qwen.parameters()).device
    print("dtype:", emb.weight.dtype, "params:", sum(p.numel() for p in qwen.parameters()) / 1e6, "M")

    tok = torch.tensor([[123, 45, 67, 89, 151646, 2, 3, 4, 5]], device=dev)
    xs = emb(tok)
    mask = torch.tril(torch.ones((1, xs.shape[1], xs.shape[1]), device=dev)).to(torch.bool)

    def fwd_step(xs1, m1, cache):
        outs = qwen(inputs_embeds=xs1, attention_mask=m1, output_hidden_states=True, use_cache=True, past_key_values=cache)
        return outs.hidden_states[-1], outs.past_key_values

    with torch.inference_mode(), torch.cuda.amp.autocast(True):
        for w in range(3):
            cache = None
            for _ in range(2):
                xs1 = emb(torch.tensor([[7]], device=dev))
                m1 = torch.tril(torch.ones((1, 1, 1), device=dev)).to(torch.bool)
                _, cache = fwd_step(xs1, m1, cache)
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        cache = None
        for _ in range(20):
            xs1 = emb(torch.tensor([[7]], device=dev))
            m1 = torch.tril(torch.ones((1, 1, 1), device=dev)).to(torch.bool)
            _, cache = fwd_step(xs1, m1, cache)
        torch.cuda.synchronize()
        print(f"single-token step (KV cached): {(time.perf_counter() - t0) / 20 * 1000:.1f} ms/step")
        print("cuda mem:", torch.cuda.memory_allocated() / 1e9, "GB")
    eng.unload()


if __name__ == "__main__":
    main()