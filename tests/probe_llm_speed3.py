# tests/probe_llm_speed3.py — torch.profiler 定位每步开销
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
    m1 = torch.tril(torch.ones((1, 1, 1), device=dev)).to(torch.bool)

    cache = None
    with torch.inference_mode(), torch.cuda.amp.autocast(True):
        for _ in range(5):
            outs = qwen(inputs_embeds=emb(torch.tensor([[7]], device=dev)), attention_mask=m1,
                        output_hidden_states=True, use_cache=True, past_key_values=cache)
            cache = outs.past_key_values
        torch.cuda.synchronize()
        from torch.profiler import profile, ProfilerActivity
        with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA], record_shapes=False) as prof:
            cache = None
            for _ in range(5):
                outs = qwen(inputs_embeds=emb(torch.tensor([[7]], device=dev)), attention_mask=m1,
                            output_hidden_states=True, use_cache=True, past_key_values=cache)
                cache = outs.past_key_values
            torch.cuda.synchronize()
    print(prof.key_averages().table(sort_by="self_cuda_time_total", row_limit=15))
    print(prof.key_averages().table(sort_by="self_cpu_time_total", row_limit=15))
    eng.unload()


if __name__ == "__main__":
    main()