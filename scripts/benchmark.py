# benchmark.py — 性能基准（写 benchmark_results.json）
# 用例：
#  1) 短句流式 TTFA（CosyVoice3 streaming, speed=1.0）
#  2) 长句 TTFA + 整句生成时长
#  3) Fish Speech 1.5 整句生成（对照，非流式）
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deps" / "CosyVoice" / "third_party" / "Matcha-TTS"))

from app.tts.base import TTSStyle
from app.tts.cosyvoice import CosyVoiceEngine
from app.tts.fishspeech import FishSpeechEngine

SHORT = "我不知道应该怎么回答你。"
LONG = ("今天天气不错，我们一起去公园散步吧。你知道吗，我昨天看了一部很好看的电影，"
        "里面的主角特别勇敢，最后他用自己的智慧解决了所有问题。")

RESULTS = {}


def bench_engine(name, engine, style, texts, cases):
    for case, text in texts.items():
        t0 = time.perf_counter()
        engine.ttfa_ms = 0
        chunks = list(engine.synthesize_stream(text, style))
        total = (time.perf_counter() - t0) * 1000
        dur = sum(len(c) / engine.sample_rate for c in chunks)
        RESULTS[f"{name}_{case}"] = {
            "ttfa_ms": round(engine.ttfa_ms, 0),
            "total_ms": round(total, 0),
            "audio_dur_s": round(dur, 2),
            "rtf": round(total / 1000 / max(dur, 1e-6), 3),
        }
        print(f"  [{name}|{case}] TTFA={RESULTS[f'{name}_{case}']['ttfa_ms']}ms "
              f"total={RESULTS[f'{name}_{case}']['total_ms']}ms audio={dur:.2f}s "
              f"rtf={RESULTS[f'{name}_{case}']['rtf']}")


def main():
    from app.profiles.reference import ReferenceManager
    mgr = ReferenceManager()
    profs = mgr.list_profiles()
    if not profs:
        print("没有参考音频。请先用 GUI 导入，或用 python scripts/benchmark.py --wav <file> [--text <ref转写>]")
        # 允许从命令行传入
        wav = None
        for i, a in enumerate(sys.argv):
            if a == "--wav" and i + 1 < len(sys.argv):
                wav = sys.argv[i + 1]
            if a == "--text" and i + 1 < len(sys.argv):
                ref_text = sys.argv[i + 1]
        if wav:
            p = mgr.import_reference(wav, name="bench", ref_text=locals().get("ref_text", ""))
            prof = mgr.get_profile(p["id"])
        else:
            sys.exit("用法: python scripts/benchmark.py --wav <ref.wav> [--text <ref转写>]")
    else:
        prof = mgr.get_profile(profs[0]["id"])
    ref_path, ref_text = prof["path"], prof.get("text", "")

    style = TTSStyle(speed=1.0, emotion="calm", energy=0.9)

    print("== CosyVoice3 流式 (short/long) ==")
    cv = CosyVoiceEngine(device="cuda", fp16=True)
    cv.load_reference(ref_path, ref_text)
    bench_engine("cosyvoice", cv, style, {"short": SHORT, "long": LONG}, None)
    cv.unload()

    print("== Fish Speech 1.5 (short) ==")
    fs = FishSpeechEngine(device="cuda")
    fs.load_reference(ref_path, ref_text)
    bench_engine("fish", fs, style, {"short": SHORT}, None)
    fs.unload()

    out = ROOT / "logs" / "benchmark_results.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n写入 {out}")


if __name__ == "__main__":
    main()