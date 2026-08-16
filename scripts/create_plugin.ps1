# create_plugin.ps1 — 插件模板生成
# 用法：.\scripts\create_plugin.ps1 my-plugin -Type tts
param(
    [Parameter(Mandatory=$true)][string]$Name,
    [ValidateSet("dsp","text","tts","asr","vc","external")][string]$Type = "dsp"
)
$Root = Split-Path -Parent $PSScriptRoot
$id = "org.voicestudio.$($Name -replace '[^a-z0-9]', ''')"
$dir = Join-Path $Root "plugins\examples\$Name"
New-Item -ItemType Directory -Force -Path "$dir\python" | Out-Null

$nodeType = "$($Name -replace '[^a-z0-9]', '_').process"
$categoryMap = @{ dsp="音频效果"; text="文本"; tts="TTS"; asr="ASR"; vc="变声"; external="外部" }

@"
id = "$id"
name = "$Name"
version = "0.1.0"
api_version = "1.0"
runtime = "python"
entrypoint = "plugin_impl:create_plugin"
description = "$($Type) 类插件（模板生成）"

[runtime_requirements]
python_env = "main"
"@ | Out-File "$dir\plugin.toml" -Encoding utf8

@"
"""$Name — $($Type) 插件（scripts/create_plugin.ps1 生成）。"""
from voice_plugin_sdk import (AudioFrame, EmitAudio, PluginContext, TextEvent,
                              TtsRequest, VoicePlugin)

NODE = {
    "node_type": "$nodeType",
    "display_name": "$Name",
    "category": "$($categoryMap[$Type])",
    "inputs": [{"name": "in", "port_type": "audio.pcm", "required": True}],
    "outputs": [{"name": "out", "port_type": "audio.pcm"}],
    "default_params": {},
    "params_schema": {"type": "object", "properties": {}},
    "estimated_vram_mb": 0,
}


class MyPlugin(VoicePlugin):
    def manifest(self):
        return {"node_types": [NODE]}

    async def process_audio(self, instance_id, frame: AudioFrame, ctx: PluginContext):
        await ctx.emit_audio(instance_id, frame.samples, frame.sample_rate, frame.channels)


def create_plugin() -> VoicePlugin:
    return MyPlugin()
"@ | Out-File "$dir\python\plugin_impl.py" -Encoding utf8

Write-Host "插件模板已生成：$dir" -ForegroundColor Green
Write-Host "下一步：编辑 python/plugin_impl.py，复制到 app-data\plugins\$Name，在 GUI 插件页启动。"
