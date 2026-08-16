"""中文文本工具插件（复用仓库已验证的 app.pipeline.chunker / app.textnorm）。

节点类型：
- textkit.segmenter        : text.partial → text.segment（稳定前缀 + 智能断句）
- textkit.to_tts           : text.segment → tts.request
- textkit.normalizer       : text.segment → text.segment（数字/日期/游戏模式标准化）
- textkit.replacement_dict : text.segment → text.segment（用户词典）
"""
from __future__ import annotations

import asyncio

from voice_plugin_sdk import PluginContext, TextEvent, VoicePlugin

SEG_NODE = {
    "node_type": "textkit.segmenter",
    "display_name": "稳定前缀+断句",
    "category": "文本",
    "inputs": [{"name": "in", "port_type": "text.partial", "required": True}],
    "outputs": [{"name": "out", "port_type": "text.segment"}],
    "default_params": {"stable_rounds": 4, "max_chars": 26, "flush_timeout_ms": 1500},
    "params_schema": {
        "type": "object",
        "properties": {
            "stable_rounds": {"type": "integer", "minimum": 2, "maximum": 8, "default": 4,
                              "description": "连续 N 轮不变的公共前缀才算稳定"},
            "max_chars": {"type": "integer", "minimum": 10, "maximum": 60, "default": 26},
            "flush_timeout_ms": {"type": "integer", "minimum": 300, "maximum": 5000, "default": 1500},
        },
    },
    "estimated_vram_mb": 0,
}

TO_TTS_NODE = {
    "node_type": "textkit.to_tts",
    "display_name": "文本→TTS请求",
    "category": "文本",
    "inputs": [{"name": "in", "port_type": "text.segment", "required": True}],
    "outputs": [{"name": "out", "port_type": "tts.request"}],
    "default_params": {"voice_profile": "default", "speed": 1.0, "style": "calm",
                       "interrupt_mode": "QUEUE"},
    "params_schema": {
        "type": "object",
        "properties": {
            "voice_profile": {"type": "string", "default": "default"},
            "speed": {"type": "number", "minimum": 0.5, "maximum": 1.5, "default": 1.0,
                      "ui:widget": "slider"},
            "interrupt_mode": {"type": "string", "default": "QUEUE", "ui:widget": "select",
                               "enum": ["QUEUE", "INTERRUPT", "REPLACE_PENDING", "DROP_IF_BUSY"]},
        },
    },
    "estimated_vram_mb": 0,
}

NORM_NODE = {
    "node_type": "textkit.normalizer",
    "display_name": "中文标准化",
    "category": "文本",
    "inputs": [{"name": "in", "port_type": "text.segment", "required": True}],
    "outputs": [{"name": "out", "port_type": "text.segment"}],
    "default_params": {"mode": "gaming"},
    "params_schema": {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "default": "gaming", "ui:widget": "select",
                     "enum": ["normal", "gaming", "literal"]},
        },
    },
    "estimated_vram_mb": 0,
}

DICT_NODE = {
    "node_type": "textkit.replacement_dict",
    "display_name": "替换词典",
    "category": "文本",
    "inputs": [{"name": "in", "port_type": "text.segment", "required": True}],
    "outputs": [{"name": "out", "port_type": "text.segment"}],
    "default_params": {"dict_json": "{}"},
    "params_schema": {
        "type": "object",
        "properties": {
            "dict_json": {"type": "string", "ui:widget": "textarea",
                          "description": '{"源": "目标", ...}'},
        },
    },
    "estimated_vram_mb": 0,
}


class TextKitPlugin(VoicePlugin):
    def __init__(self):
        self._segmenters: dict[str, object] = {}

    def manifest(self):
        return {"node_types": [SEG_NODE, TO_TTS_NODE, NORM_NODE, DICT_NODE]}

    def _get_segmenter(self, instance_id: str, ctx: PluginContext):
        from app.pipeline.chunker import Segmenter
        p = ctx.params(instance_id)
        key = (int(p.get("stable_rounds", 4)), int(p.get("max_chars", 26)),
               int(p.get("flush_timeout_ms", 1500)))
        st = self._segmenters.get(instance_id)
        if st is None or getattr(st, "_cfg", None) != key:
            def on_sentence(text):
                ctx.emit_threadsafe(ctx.emit_text(
                    instance_id, text, is_final=True, segment_id=f"{instance_id}"))
            st = Segmenter(stable_rounds=key[0], max_chars=key[1],
                           flush_timeout_ms=key[2], on_sentence=on_sentence)
            st._cfg = key
            self._segmenters[instance_id] = st
        return st

    async def process_text(self, instance_id: str, event: TextEvent, ctx: PluginContext):
        node_type = ctx.params(instance_id).get("__node_type__", "")
        p = ctx.params(instance_id)

        if node_type == "textkit.segmenter":
            st = self._get_segmenter(instance_id, ctx)
            if event.is_final:
                st.sentence_ended()
                st.reset()
            else:
                st.update_partial(event.text)
            st.check_timeout()

        elif node_type == "textkit.to_tts":
            if event.text.strip():
                from voice_plugin_sdk import TtsRequest
                await ctx._emit(instance_id, TtsRequest(
                    text=event.text, voice_profile=p.get("voice_profile", "default"),
                    speed=float(p.get("speed", 1.0)), style=p.get("style", "calm"),
                    interrupt_mode=p.get("interrupt_mode", "QUEUE"),
                ))

        elif node_type == "textkit.normalizer":
            from app.textnorm import normalize_chinese_text
            out = normalize_chinese_text(event.text, mode=p.get("mode", "gaming"))
            await ctx.emit_text(instance_id, out, is_final=True, segment_id=event.segment_id)

        elif node_type == "textkit.replacement_dict":
            import json as _json
            try:
                d = _json.loads(p.get("dict_json", "{}"))
            except Exception:
                d = {}
            out = event.text
            for k, v in d.items():
                out = out.replace(k, v)
            await ctx.emit_text(instance_id, out, is_final=True, segment_id=event.segment_id)

    async def on_control(self, instance_id, signal, ctx):
        if signal.signal in ("ptt_up", "vad_end", "flush"):
            st = self._segmenters.get(instance_id)
            if st is not None:
                st.force_flush()


def create_plugin() -> VoicePlugin:
    return TextKitPlugin()
