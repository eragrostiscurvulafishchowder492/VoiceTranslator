"""示例插件 5：外部命令包装。text.final → 运行命令 → stdout 首行 → text.segment。
演示 process_spawn 权限声明（安装时 GUI 必须高亮提示）。"""
import asyncio

from voice_plugin_sdk import PluginContext, TextEvent, VoicePlugin

NODE = {
    "node_type": "extcmd.run",
    "display_name": "外部命令",
    "category": "文本",
    "inputs": [{"name": "in", "port_type": "text.final", "required": True}],
    "outputs": [{"name": "out", "port_type": "text.segment"}],
    "default_params": {"command": "echo", "timeout_s": 10.0},
    "params_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "命令；{text} 占位符替换输入文本"},
            "timeout_s": {"type": "number", "default": 10, "minimum": 1, "maximum": 120},
        },
    },
    "estimated_vram_mb": 0,
}


class ExtCmdPlugin(VoicePlugin):
    def manifest(self):
        return {"node_types": [NODE]}

    async def process_text(self, instance_id: str, event: TextEvent, ctx: PluginContext):
        if not event.is_final:
            return
        p = ctx.params(instance_id)
        cmd = str(p.get("command", "echo")).format(text=event.text)
        timeout = float(p.get("timeout_s", 10.0))
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            first = out.decode("utf-8", "replace").strip().splitlines()
            result = first[0] if first else ""
        except Exception as e:
            result = f"<command failed: {e}>"
        await ctx.emit_text(instance_id, result, is_final=True, segment_id=event.segment_id)


def create_plugin() -> VoicePlugin:
    return ExtCmdPlugin()
