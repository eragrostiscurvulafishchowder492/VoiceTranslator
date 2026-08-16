"""精简版 Qwen2 流式解码器：绕过 transformers eager 的 Python 开销（CPU 每步 ~80ms -> 目标 <10ms）。

用法：安装到 Qwen2Encoder 实例上替换 forward_one_step，权重就地 fp16 化。
接口兼容原方法：forward_one_step(xs, masks=None, cache=None) -> (hidden, new_cache)。
"""
import torch
import torch.nn.functional as F


def _rotate_half(x):
    x1, x2 = x.chunk(2, dim=-1)
    return torch.cat((-x2, x1), dim=-1)


def install_fast_llm(encoder, fp16=True):
    """encoder: cosyvoice.llm.llm.Qwen2Encoder 实例（含 .model = Qwen2ForCausalLM）"""
    m = encoder.model
    model = m.model
    layers = list(model.layers)
    norm = model.norm
    rotary = model.rotary_emb
    n_heads = m.config.num_attention_heads
    n_kv = m.config.num_key_value_heads
    head_dim = getattr(m.config, "head_dim", None) or (m.config.hidden_size // n_heads)
    dev = model.embed_tokens.weight.device

    if fp16:
        m.half()
    dtype = model.embed_tokens.weight.dtype

    @torch.inference_mode()
    def forward_one_step(xs, masks=None, cache=None):
        h = xs.to(device=dev, dtype=dtype)
        if cache is None:
            cache = [None] * len(layers)
        pos = cache[0][0].size(2) if cache[0] is not None else 0
        t = h.size(1)
        position_ids = torch.arange(pos, pos + t, device=dev).unsqueeze(0)
        cos, sin = rotary(h, position_ids)
        cos = cos.unsqueeze(1)
        sin = sin.unsqueeze(1)
        attn_mask = None
        if t > 1:
            attn_mask = torch.tril(torch.ones(t, t, device=dev, dtype=torch.bool))
        for i, layer in enumerate(layers):
            residual = h
            x = layer.input_layernorm(h.float()).to(dtype)
            q = layer.self_attn.q_proj(x).view(1, t, n_heads, head_dim).transpose(1, 2)
            k = layer.self_attn.k_proj(x).view(1, t, n_kv, head_dim).transpose(1, 2)
            v = layer.self_attn.v_proj(x).view(1, t, n_kv, head_dim).transpose(1, 2)
            qf, kf = q.float(), k.float()
            q = (qf * cos + _rotate_half(qf) * sin).to(dtype)
            k = (kf * cos + _rotate_half(kf) * sin).to(dtype)
            if cache[i] is None:
                cache[i] = (k, v)
            else:
                kk, vv = cache[i]
                cache[i] = (torch.cat([kk, k], dim=2), torch.cat([vv, v], dim=2))
            kk, vv = cache[i]
            if n_kv != n_heads:
                kk = kk.repeat_interleave(n_heads // n_kv, dim=1)
                vv = vv.repeat_interleave(n_heads // n_kv, dim=1)
            o = F.scaled_dot_product_attention(q, kk, vv, attn_mask=attn_mask)
            o = o.transpose(1, 2).reshape(1, t, -1)
            h = (residual + layer.self_attn.o_proj(o)).to(dtype)
            residual = h
            x = layer.post_attention_layernorm(h.float()).to(dtype)
            h = (residual + layer.mlp.down_proj(F.silu(layer.mlp.gate_proj(x)) * layer.mlp.up_proj(x))).to(dtype)
        return norm(h.float()).to(dtype), cache

    encoder.forward_one_step = forward_one_step
    return encoder