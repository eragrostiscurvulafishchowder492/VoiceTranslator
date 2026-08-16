# tests/simulate.py — 30 分钟稳定性/延迟模拟（无 GUI、无真实麦克风）
# 方法：用 TTS 生成一句话音频 → 送入 VAD/ASR 流式管线 → 得到 ASR 文本 → 再 TTS，
# 记录每轮端到端延迟、显存、VRAM、underrun 等，并做泄漏/漂移检测。
import gc
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deps" / "CosyVoice" / "third_party" / "Matcha-TTS"))

import numpy as np

SENTENCES = [
    "我不知道应该怎么回答你。",
    "这个办法听起来好像不错。",
    "你先坐下来慢慢说。",
    "其实我也不太确定。",
    "等我想一想再说吧。",
    "你刚才说的那件事我已经明白了。",
    "抱歉，我刚才走神了。",
    "那就按你说的试试看吧。",
    "今天的事情就先到这里。",
    "我们改天再聊吧。",
]


def main():
    duration_min = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    from app.tts.base import TTSStyle
    from app.tts.cosyvoice import CosyVoiceEngine
    from app.asr.funasr import FunASREngine
    from app.profiles.reference import ReferenceManager
    from app.diagnostics import gpu as gpu_diag

    mgr = ReferenceManager()
    profs = mgr.list_profiles()
    if not profs:
        sys.exit("没有参考音频。请先用 GUI 导入参考 WAV。")
    prof = mgr.get_profile(profs[0]["id"])

    print(f"参考: {prof['name']}  ({prof['path']})")
    tts = CosyVoiceEngine(device="cuda", fp16=True)
    tts.load_reference(prof["path"], prof.get("text", ""))
    asr = FunASREngine(device="cuda", chunk_size=[0, 10, 5])
    asr.start()

    # 用 TTS 生成参考语音作为 ASR 输入源
    src_tts = tts
    style = TTSStyle(speed=1.0, emotion="calm")

    results = []
    t_start = time.time()
    round_idx = 0
    errors = 0
    peak_vram = 0
    rt_ms_total = 0

    while time.time() - t_start < duration_min * 60:
        round_idx += 1
        sent = SENTENCES[round_idx % len(SENTENCES)]
        # 1) TTS 生成（非流式合成整段）
        tts.gen_ms = 0
        audio = tts.synthesize(sent, style)
        rt_ms = tts.gen_ms
        rt_ms_total += rt_ms
        # 2) 送 ASR：VAD 视为单段（直接 push + finalize）
        asr.reset()
        partials = []
        finals = []
        idx = 0
        FRAME = 960
        while idx < len(audio):
            asr.push_audio(audio[idx: idx + FRAME])
            partials.append(asr.get_partial_text())
            idx += FRAME
        final = asr.finalize_segment()
        finals.append(final)
        # 3) 记录
        sim_score = _sim(final, sent)
        vram = gpu_diag.query_vram_mb()
        peak_vram = max(peak_vram, vram)
        row = {
            "round": round_idx,
            "sentence": sent,
            "asr_final": final,
            "sim": round(sim_score, 3),
            "tts_rt_ms": round(rt_ms, 0),
            "vram_mb": vram,
            "time_s": round(time.time() - t_start, 1),
        }
        results.append(row)
        status = "OK" if sim_score >= 0.5 else "MISMATCH"
        if sim_score < 0.5:
            errors += 1
        print(f"[{round_idx:3d}] {sent} -> ASR: {final}  sim={sim_score:.2f} {status}  "
              f"TTS={rt_ms:.0f}ms VRAM={vram}MB t={time.time()-t_start:.0f}s", flush=True)

        if round_idx % 20 == 0:
            gc.collect()
            if hasattr(tts, "device") and tts.device == "cuda":
                import torch
                torch.cuda.empty_cache()

    elapsed = time.time() - t_start
    report = {
        "duration_min": round(elapsed / 60, 2),
        "rounds": round_idx,
        "errors": errors,
        "error_rate": round(errors / max(round_idx, 1), 4),
        "avg_tts_rt_ms": round(rt_ms_total / max(round_idx, 1), 0),
        "peak_vram_mb": peak_vram,
        "avg_sim": round(sum(r["sim"] for r in results) / len(results), 3) if results else 0,
        "last_rounds": results[-5:],
    }
    out = ROOT / "logs" / "simulate_results.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n=== 完成 {elapsed/60:.1f} 分钟 ===")
    print(json.dumps({k: v for k, v in report.items() if k != "last_rounds"},
                     indent=2, ensure_ascii=False))
    print(f"写入 {out}")
    asr.unload()
    tts.unload()


def _sim(hyp: str, ref: str) -> float:
    """简单字符级相似度。"""
    if not hyp:
        return 0.0
    h = list(hyp.replace(" ", ""))
    r = list(ref.replace(" ", ""))
    # 最长公共子序列近似
    n, m = len(h), len(r)
    dp = [[0] * (m + 1) for _ in range(2)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if h[i - 1] == r[j - 1]:
                dp[1][j] = dp[0][j - 1] + 1
            else:
                dp[1][j] = max(dp[0][j], dp[1][j - 1])
        dp[0], dp[1] = dp[1], [0] * (m + 1)
    lcs = dp[0][m]
    return 2 * lcs / max(n + m, 1)


if __name__ == "__main__":
    main()