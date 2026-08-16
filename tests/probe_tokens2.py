# tests/probe_tokens2.py — 包住 inference 生成器统计 token 序列
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from app.tts.base import TTSStyle
from app.tts.cosyvoice import CosyVoiceEngine

TEXT = "我不知道应该怎么回答你。"


def run(fast_llm: bool):
    eng = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=10, fast_llm=fast_llm)
    eng.load_reference(str(Path(r"data/test_zh.wav")), "今天天气不错，我们一起去公园散步吧。")
    llm = eng._model.model.llm
    orig = llm.inference
    info = {}

    def wrapped(*a, **k):
        gen = orig(*a, **k)
        toks = []

        def counter():
            for t in gen:
                toks.append(int(t))
                yield t
        info["counter"] = toks
        return counter()

    llm.inference = wrapped
    style = TTSStyle(speed=1.0)
    chunks = list(eng.synthesize_stream(TEXT, style))
    dur = sum(len(c) / eng.sample_rate for c in chunks)
    toks = info.get("counter", [])
    print(f"fast_llm={fast_llm}: audio={dur:.2f}s tokens={len(toks)} head={toks[:12]} tail={toks[-6:]}")
    eng.unload()


if __name__ == "__main__":
    for i in range(3):
        run(False)
    run(True)
    run(True)