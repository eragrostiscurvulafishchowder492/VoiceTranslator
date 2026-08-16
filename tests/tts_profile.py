# tests/tts_profile.py — 阶段耗时剖析：LLM token 生成 vs flow 生成（非流式，2 轮取稳态）
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from app.tts.cosyvoice import CosyVoiceEngine
from app.tts.base import TTSStyle

TEXT = "我不知道应该怎么回答你。"


def main():
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"data/test_zh.wav")
    ref_text = sys.argv[2] if len(sys.argv) > 2 else "今天天气不错，我们一起去公园散步吧。"
    eng = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=10)
    eng.load_reference(str(wav), ref_text)
    style = TTSStyle(speed=1.0)
    model = eng._model.model

    times = {"llm": [], "flow": [], "total": []}
    orig_llm_job = model.llm_job
    orig_token2wav = model.token2wav

    def llm_job(*a, **k):
        t0 = time.perf_counter()
        r = orig_llm_job(*a, **k)
        times["llm"].append((time.perf_counter() - t0) * 1000)
        return r

    def token2wav(*a, **k):
        t0 = time.perf_counter()
        r = orig_token2wav(*a, **k)
        times["flow"].append((time.perf_counter() - t0) * 1000)
        return r

    model.llm_job = llm_job
    model.token2wav = token2wav

    for i in range(3):
        times["llm"].clear()
        times["flow"].clear()
        t0 = time.perf_counter()
        chunks = list(eng.synthesize_stream(TEXT, style, _force_stream=False))
        times["total"].append((time.perf_counter() - t0) * 1000)
        if i == 0:
            print("(warmup)")
            continue
        print(f"round{i}: total={times['total'][-1]:.0f}ms "
              f"llm={sum(times['llm']):.0f}ms flow={sum(times['flow']):.0f}ms")
    eng.unload()


if __name__ == "__main__":
    main()