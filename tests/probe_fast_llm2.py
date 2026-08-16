# tests/probe_fast_llm2.py — CUDA 事件分步计时 + 无 autocast/inference_mode 对照
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
    dev = next(encoder.parameters()).device
    emb = encoder.model.model.embed_tokens

    def run(n=30, sync_each=False):
        cache = None
        with torch.inference_mode():
            for _ in range(5):
                h, cache = encoder.forward_one_step(emb(torch.tensor([[7]], device=dev)), None, cache)
            if sync_each:
                torch.cuda.synchronize()
            e0, e1 = torch.cuda.Event(True), torch.cuda.Event(True)
            torch.cuda.synchronize()
            e0.record()
            cache = None
            for _ in range(n):
                h, cache = encoder.forward_one_step(emb(torch.tensor([[7]], device=dev)), None, cache)
                if sync_each:
                    torch.cuda.synchronize()
            e1.record()
            torch.cuda.synchronize()
            cuda_ms = e0.elapsed_time(e1) / n
            print(f"sync_each={sync_each}: cuda={cuda_ms:.1f} ms/step")

    run(30, sync_each=False)
    run(30, sync_each=True)


if __name__ == "__main__":
    main()