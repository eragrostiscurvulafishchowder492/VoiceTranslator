# tests/probe_steps.py — 探针：引擎补丁实际拦截到的 n_timesteps
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deps" / "CosyVoice" / "third_party" / "Matcha-TTS"))
sys.path.insert(0, str(ROOT / "deps" / "CosyVoice"))

import numpy as np
import torch
import torchaudio

import cosyvoice.flow.flow_matching as fm
from app.tts.cosyvoice import CosyVoiceEngine
from app.tts.base import TTSStyle

SEEN = []


def main():
    wav = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r"data/test_zh.wav")
    ref_text = sys.argv[2] if len(sys.argv) > 2 else "今天天气不错，我们一起去公园散步吧。"
    orig = fm.CausalConditionalCFM.forward  # 引擎补丁前的原始 forward

    eng = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=6)
    eng.load_reference(str(wav), ref_text)
    print("engine patched:", eng._patched)
    print("decoder steps attr:", getattr(eng._model.model.flow.decoder, "_mcp_flow_steps", None))

    def probe(self_cfm, *a, **k):
        k2 = dict(k)
        if "n_timesteps" in k2:
            SEEN.append((k2["n_timesteps"], getattr(self_cfm, "_mcp_flow_steps", None)))
            k2["n_timesteps"] = 4
        return orig(self_cfm, *a, **k2)

    fm.CausalConditionalCFM.forward = probe
    chunks = list(eng.synthesize_stream("我不知道应该怎么回答你。", TTSStyle(speed=1.0)))
    audio = np.concatenate(chunks)
    torchaudio.save(str(ROOT / "logs" / "probe.wav"), torch.from_numpy(audio).unsqueeze(0), eng.sample_rate)
    print("seen (n_timesteps, _mcp_flow_steps):", SEEN)
    print("audio dur:", len(audio) / 24000, "s")


if __name__ == "__main__":
    main()