"""示例插件 2：Text Replace（替换词典）。"""
import re

from voice_plugin_sdk import PluginContext, TextEvent, VoicePlugin

NODE = {
    "node_type": "textreplace.replace",
    "display_name": "文本替换",
    "category": "文本",
    "inputs": [{"name": "in", "port_type": "text.final", "required": True},
               {"name": "partial", "port_type": "text.partial", "required": False}],
    "outputs": [{"name": "out", "port_type": "text.segment"}],
    "default_params": {"rules_json": '[["好耶", "好呀"]]'},
    "params_schema": {
        "type": "object",
        "properties": {
            "rules_json": {"type": "string", "ui:widget": "textarea",
                           "description": 'JSON 数组：[["源","目标"], ...]，源支持正则'},
        },
    },
    "estimated_vram_mb": 0,
}


class TextReplacePlugin(VoicePlugin):
    def manifest(self):
        return {"node_types": [NODE]}

    async def process_text(self, instance_id: str, event: TextEvent, ctx: PluginContext):
        params = ctx.params(instance_id)
        try:
            rules = __import__("json").loads(params.get("rules_json", "[]"))
        except Exception:
            rules = []
        text = event.text
        for src, dst in rules:
            try:
                text = re.sub(src, dst, text)
            except re.error:
                text = text.replace(src, dst)
        await ctx.emit_text(instance_id, text, is_final=True, segment_id=event.segment_id,
                            sequence=event.sequence)


def create_plugin() -> VoicePlugin:
    return TextReplacePlugin()
