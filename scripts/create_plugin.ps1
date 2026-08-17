# create_plugin.ps1 — 插件模板生成
# 用法：.\scripts\create_plugin.ps1 my-plugin -Type tts
param(
    [Parameter(Mandatory=$true)][string]$Name,
    [ValidateSet("dsp","text","tts","asr","vc","external")][string]$Type = "dsp",
    [string]$OutputRoot = "",
    [string]$Category = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$displayName = $Name.Trim()
if ([string]::IsNullOrWhiteSpace($Name) -or [string]::IsNullOrWhiteSpace($displayName)) {
    throw "Name 不能为空或仅含空白"
}
if ($Name -cne $displayName) {
    throw "Name 不能包含前导或尾随空白"
}
if ($displayName -match '[/\\]' -or $displayName -match '\.\.' -or $displayName -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]*$') {
    throw "Name 只能包含字母、数字、连字符和下划线，且不能包含路径分隔符或路径穿越"
}
$normalizedId = (($displayName.ToLowerInvariant() -replace '_', '-') -replace '-+', '-').Trim('-')
if ([string]::IsNullOrWhiteSpace($normalizedId) -or $normalizedId -notmatch '^[a-z0-9][a-z0-9-]*$') {
    throw "Name 规范化后不能生成有效插件 ID"
}
$id = "org.voicestudio.$normalizedId"
if ([string]::IsNullOrWhiteSpace($OutputRoot)) {
    $OutputRoot = Join-Path $Root "plugins\examples"
}
$outputBase = [IO.Path]::GetFullPath($OutputRoot)
$dir = Join-Path $outputBase $displayName
if (Test-Path -LiteralPath $dir) {
    throw "目标插件已存在，拒绝覆盖：$dir"
}
New-Item -ItemType Directory -Path (Join-Path $dir "python") | Out-Null

$nodeName = (($displayName.ToLowerInvariant() -replace '[^a-z0-9]+', '_').Trim('_'))
if ([string]::IsNullOrWhiteSpace($nodeName)) { throw "Name 规范化后不能生成有效节点类型" }
$nodeType = "$nodeName.process"
$categoryMap = @{ dsp="音频效果"; text="文本"; tts="TTS"; asr="ASR"; vc="变声"; external="外部" }
if ([string]::IsNullOrWhiteSpace($Category)) { $Category = $categoryMap[$Type] }
if ($Category -match '["\\\r\n]') { throw "Category 不能包含引号、反斜杠或换行" }

@"
id = "$id"
name = "$displayName"
version = "0.1.0"
license = "Apache-2.0"
api_version = "1.0"
runtime = "python"
entrypoint = "plugin_impl:create_plugin"
description = "$($Type) 类插件（模板生成）"

[runtime_requirements]
python_env = "main"
"@ | Out-File "$dir\plugin.toml" -Encoding utf8

@"
"""$displayName — $($Type) 插件（scripts/create_plugin.ps1 生成）。"""
from voice_plugin_sdk import (AudioFrame, EmitAudio, PluginContext, TextEvent,
                              TtsRequest, VoicePlugin)

NODE = {
    "node_type": "$nodeType",
    "display_name": "$displayName",
    "category": "$Category",
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
Write-Host "下一步：编辑 python/plugin_impl.py，复制到 app-data\plugins\$displayName，在 GUI 插件页启动。"
