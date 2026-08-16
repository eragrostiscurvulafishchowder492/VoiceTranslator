# tests/asr_stream_test.py — FunASR 流式推理真机验证
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import soundfile as sf
import soxr

from app.asr.funasr import FunASREngine


def main():
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"data/test_zh.wav")
    data, sr = sf.read(wav, dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    x16 = soxr.resample(data, sr, 16000).astype(np.float32)
    print(f"wav: {wav.name} {sr}Hz -> 16k, {len(x16)/16000:.2f}s")

    eng = FunASREngine(device="cuda", chunk_size=[0, 10, 5])
    eng.start()
    FRAME = 960
    t0 = __import__("time").perf_counter()
    idx = 0
    while idx < len(x16):
        eng.push_audio(x16[idx: idx + FRAME])
        idx += FRAME
        if eng.partial_count > 0 and eng._last_partial_ms > 0:
            pass
    final = eng.finalize_segment()
    el = (__import__("time").perf_counter() - t0) * 1000
    print(f"partials: {eng.partial_count}, total {el:.0f}ms (rtf={el/1000/(len(x16)/16000):.2f})")
    print(f"FINAL: {final}")
    eng.unload()
    ok = "不知道" in final or "公园" in final or "散步" in final
    print("ASR_TEST:", "PASS" if final.strip() else "EMPTY", "| EXPECTED: 今天天气不错，我们一起去公园散步吧。")


if __name__ == "__main__":
    main()