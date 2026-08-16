# tests/tts_cosyvoice_test.py — CosyVoice3 真机验证（加载/参考/流式 TTFA/保存）
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.tts.cosyvoice import CosyVoiceEngine
from app.tts.base import TTSStyle
from app.diagnostics.gpu import query_vram_mb, query_gpu_total_used_mb


def main():
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"data/test_zh.wav")
    ref_text = sys.argv[2] if len(sys.argv) > 2 else "今天天气不错，我们一起去公园散步吧。"
    out = Path(r"D:\_agents\VoiceTranslator\logs\test_cosyvoice3.wav")
    out.parent.mkdir(exist_ok=True)

    eng = CosyVoiceEngine(device="cuda", fp16=True)
    t0 = time.perf_counter()
    eng.load_reference(str(wav), ref_text)
    print(f"load_reference: {(time.perf_counter()-t0)*1000:.0f}ms  spk_id={eng._spk_id!r}")
    print(f"VRAM: process={query_vram_mb()}MB card={query_gpu_total_used_mb()}MB")

    text = "我不知道应该怎么回答你。"
    t0 = time.perf_counter()
    eng.ttfa_ms = 0
    chunks = []
    for c in eng.synthesize_stream(text, TTSStyle(speed=1.0, emotion="calm")):
        chunks.append(c)
    total = (time.perf_counter() - t0) * 1000
    audio = __import__("numpy").concatenate(chunks)
    dur = len(audio) / eng.sample_rate
    print(f"TTFA={eng.ttfa_ms}ms total={total:.0f}ms audio={dur:.2f}s "
          f"rtf={total/1000/dur:.2f} VRAM={query_vram_mb()}MB")
    import torchaudio
    torchaudio.save(str(out), __import__("torch").from_numpy(audio).unsqueeze(0), eng.sample_rate)
    print(f"saved: {out}")
    eng.unload()
    print("TTS_COSYVOICE_TEST: DONE")


if __name__ == "__main__":
    main()