# tests/tts_compare.py — 流式 vs 非流式延迟对比 + flow steps 敏感性
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from app.tts.cosyvoice import CosyVoiceEngine
from app.tts.base import TTSStyle

SENTS = [
    "我不知道应该怎么回答你。",
    "你先坐下来慢慢说，我们再想想别的办法。",
]


def run(eng, text, stream):
    t0 = time.perf_counter()
    eng.ttfa_ms = 0
    chunks = list(eng.synthesize_stream(text, TTSStyle(speed=1.0), _force_stream=stream))
    total = (time.perf_counter() - t0) * 1000
    dur = sum(len(c) / eng.sample_rate for c in chunks)
    return eng.ttfa_ms, total, dur


def main():
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"data/test_zh.wav")
    ref_text = sys.argv[2] if len(sys.argv) > 2 else "今天天气不错，我们一起去公园散步吧。"
    eng = CosyVoiceEngine(device="cuda", fp16=True)
    eng.load_reference(str(wav), ref_text)
    # 预热
    run(eng, SENTS[0], stream=True)
    for text in SENTS:
        for stream in (True, False):
            ttfa, total, dur = run(eng, text, stream)
            print(f"stream={stream} {text[:12]}... ttfa={ttfa}ms total={total:.0f}ms "
                  f"audio={dur:.2f}s rtf={total/1000/max(dur,1e-6):.2f}")
    eng.unload()


if __name__ == "__main__":
    main()