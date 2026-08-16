# tests/probe_stream_tokens.py — 流式合成 token 数统计：eager vs fast LLM
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
    style = TTSStyle(speed=1.0)
    chunks = list(eng.synthesize_stream(TEXT, style))
    dur = sum(len(c) / eng.sample_rate for c in chunks)
    d = eng._model.model.tts_speech_token_dict
    keys = list(d.keys())
    toks = len(d[keys[-1]]) if keys else -1
    print(f"fast_llm={fast_llm}: audio={dur:.2f}s tokens={toks} chunks={len(chunks)} keys={keys}")
    eng.unload()
    return toks, dur


if __name__ == "__main__":
    a = run(True)
    b = run(False)
    print(f"diff tokens: eager={b[0]} fast={a[0]}  audio eager={b[1]:.2f}s fast={a[1]:.2f}s")