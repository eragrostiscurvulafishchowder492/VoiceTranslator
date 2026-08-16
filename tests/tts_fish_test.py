# tests/tts_fish_test.py — fish-speech 1.5 引擎加载 + 合成测试（验证 einx 0.4.3 兼容性）
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from app.tts.fishspeech import FishSpeechEngine
from app.tts.base import TTSStyle


def main():
    ref = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"data/test_zh.wav")
    ref_text = sys.argv[2] if len(sys.argv) > 2 else "今天天气不错，我们一起去公园散步吧。"
    eng = FishSpeechEngine(device="cuda", fp16=True)
    eng.load_reference(str(ref), ref_text)
    style = TTSStyle(speed=1.0)
    t0 = time.perf_counter()
    wav = eng.synthesize("你好，这是目标音色测试。请多关照。", style)
    dt = time.perf_counter() - t0
    wav = np.asarray(wav)
    dur = len(wav) / eng.sample_rate
    rms = float(np.sqrt(np.mean(wav.astype(np.float64) ** 2)))
    out = ROOT / "logs" / "fish_test.wav"
    out.parent.mkdir(exist_ok=True)
    import soundfile as sf
    sf.write(str(out), wav, eng.sample_rate)
    print(f"fish synth: {dt * 1000:.0f} ms  dur={dur:.2f}s  rms={rms:.4f}  sr={eng.sample_rate}  saved={out}")
    eng.unload()


if __name__ == "__main__":
    main()