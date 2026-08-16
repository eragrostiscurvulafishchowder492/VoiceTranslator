# tests/probe_fast_llm4.py — 循环内分块计时（CPU wall，同步后）
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import torch

from app.tts.cosyvoice import CosyVoiceEngine
from app.tts.fast_llm import install_fast_llm


def main():
    eng = CosyVoiceEngine(device="cuda", fp16=True, flow_steps=10)
    eng.load_reference(str(Path(r"data/test_zh.wav")), "今天天气不错，我们一起去公园散步吧。")
    encoder = eng._model.model.llm.llm
    install_fast_llm(encoder, fp16=True)
    dev = next(encoder.parameters()).device
    emb = encoder.model.model.embed_tokens

    # 复刻 fast 循环，分块计时
    m = encoder.model
    model = m.model
    layers = list(model.layers)
    norm = model.norm
    rotary = model.rotary_emb
    n_heads = m.config.num_attention_heads
    n_kv = m.config.num_key_value_heads
    head_dim = getattr(m.config, "head_dim", None) or (m.config.hidden_size // n_heads)
    dtype = model.embed_tokens.weight.dtype
    import torch.nn.functional as F

    def rotate_half(x):
        x1, x2 = x.chunk(2, dim=-1)
        return torch.cat((-x2, x1), dim=-1)

    def step(h, cache):
        t_rope0 = time.perf_counter()
        if cache is None:
            cache = [None] * len(layers)
        pos = cache[0][0].size(2) if cache[0] is not None else 0
        t = h.size(1)
        position_ids = torch.arange(pos, pos + t, device=dev).unsqueeze(0)
        cos, sin = rotary(h, position_ids)
        cos = cos.to(dtype=dtype).unsqueeze(1)
        sin = sin.to(dtype=dtype).unsqueeze(1)
        t_rope = time.perf_counter() - t_rope0
        t_lay0 = time.perf_counter()
        for i, layer in enumerate(layers):
            residual = h
            x = layer.input_layernorm(h)
            q = layer.self_attn.q_proj(x).view(1, t, n_heads, head_dim).transpose(1, 2)
            k = layer.self_attn.k_proj(x).view(1, t, n_kv, head_dim).transpose(1, 2)
            v = layer.self_attn.v_proj(x).view(1, t, n_kv, head_dim).transpose(1, 2)
            q = (q * cos + rotate_half(q) * sin).to(dtype)
            k = (k * cos + rotate_half(k) * sin).to(dtype)
            if cache[i] is None:
                cache[i] = (k, v)
            else:
                kk, vv = cache[i]
                cache[i] = (torch.cat([kk, k], dim=2), torch.cat([vv, v], dim=2))
            kk, vv = cache[i]
            if n_kv != n_heads:
                kk = kk.repeat_interleave(n_heads // n_kv, dim=1)
                vv = vv.repeat_interleave(n_heads // n_kv, dim=1)
            o = F.scaled_dot_product_attention(q, kk, vv)
            o = o.transpose(1, 2).reshape(1, t, -1)
            h = (residual + layer.self_attn.o_proj(o)).to(dtype)
            residual = h
            x = layer.post_attention_layernorm(h)
            h = (residual + layer.mlp.down_proj(F.silu(layer.mlp.gate_proj(x)) * layer.mlp.up_proj(x))).to(dtype)
        t_lay = time.perf_counter() - t_lay0
        return h, cache, t_rope, t_lay

    with torch.inference_mode():
        cache = None
        ro, la = [], []
        for _ in range(3):
            h, cache, r, l = step(emb(torch.tensor([[7]], device=dev)), cache)
            ro.append(r)
            la.append(l)
        torch.cuda.synchronize()
        print(f"rope: {sum(ro) / len(ro) * 1000:.2f} ms  layers: {sum(la) / len(la) * 1000:.2f} ms")
        cache = None
        t0 = time.perf_counter()
        for _ in range(30):
            h, cache, _, _ = step(emb(torch.tensor([[7]], device=dev)), cache)
        torch.cuda.synchronize()
        print(f"total: {(time.perf_counter() - t0) / 30 * 1000:.1f} ms/step")
    eng.unload()


if __name__ == "__main__":
    main()