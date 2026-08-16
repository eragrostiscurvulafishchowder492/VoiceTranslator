# tests/probe_fast_llm3.py — CPU 剖析 fast 循环
import sys
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
    dev = next(encoder.parameters()).device
    emb = encoder.model.model.embed_tokens

    from torch.profiler import profile, ProfilerActivity
    with torch.inference_mode():
        cache = None
        for _ in range(3):
            h, cache = encoder.forward_one_step(emb(torch.tensor([[7]], device=dev)), None, cache)
        torch.cuda.synchronize()
        with profile(activities=[ProfilerActivity.CPU]) as prof:
            cache = None
            for _ in range(10):
                h, cache = encoder.forward_one_step(emb(torch.tensor([[7]], device=dev)), None, cache)
            torch.cuda.synchronize()
    print(prof.key_averages().table(sort_by="self_cpu_time_total", row_limit=18))
    eng.unload()


if __name__ == "__main__":
    main()