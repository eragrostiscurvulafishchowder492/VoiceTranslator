# tests/probe_llm_config.py — 打印 Qwen2-0.5B 配置
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.tts.cosyvoice import CosyVoiceEngine


def main():
    eng = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=10)
    eng.load_reference(str(Path(r"data/test_zh.wav")), "今天天气不错，我们一起去公园散步吧。")
    qwen = eng._model.model.llm.llm.model
    c = qwen.config
    print("arch:", c.architectures)
    for k in ["hidden_size", "num_hidden_layers", "num_attention_heads", "num_key_value_heads",
              "head_dim", "intermediate_size", "vocab_size", "rms_norm_eps", "rope_theta",
              "sliding_window", "use_sliding_window", "max_position_embeddings", "tie_word_embeddings",
              "qkv_bias", "hidden_act", "attn_implementation", "model_type"]:
        print(f"{k}: {getattr(c, k, None)}")
    m = qwen.model
    layer = m.layers[0]
    print("layer0 modules:", [n for n, _ in layer.named_children()])
    attn = layer.self_attn
    print("attn attrs:", [a for a in dir(attn) if not a.startswith("_") and a in ("q_norm", "k_norm", "rotary_emb", "q_proj", "k_proj", "v_proj", "o_proj")])
    print("q_proj bias:", attn.q_proj.bias is not None, " head_dim:", attn.head_dim)
    print("rope class:", type(m.rotary_emb).__name__, "inv_freq shape:", tuple(m.rotary_emb.inv_freq.shape) if hasattr(m.rotary_emb, "inv_freq") else None)
    print("norm class:", type(m.norm).__name__)
    eng.unload()


if __name__ == "__main__":
    main()