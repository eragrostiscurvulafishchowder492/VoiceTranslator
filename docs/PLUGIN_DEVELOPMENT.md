# Python Plugin SDK 开发指南

5 分钟写一个插件。SDK 位于 `sdk/python/voice_plugin_sdk`，
由宿主 spawn 时自动注入 `PYTHONPATH`（也可手动调试）。

## 最小插件

```
plugins/examples/myecho/
├─ plugin.toml
└─ python/plugin_impl.py
```

`plugin.toml`：

```toml
id = "org.voicestudio.myecho"
name = "My Echo"
version = "0.1.0"
api_version = "1.0"
runtime = "python"
entrypoint = "plugin_impl:create_plugin"

[runtime_requirements]
python_env = "main"
```

`python/plugin_impl.py`：

```python
from voice_plugin_sdk import AudioFrame, PluginContext, VoicePlugin

NODE = {
    "node_type": "myecho.pass",
    "display_name": "回声（直通）",
    "category": "音频效果",
    "inputs": [{"name": "in", "port_type": "audio.pcm", "required": True}],
    "outputs": [{"name": "out", "port_type": "audio.pcm"}],
    "default_params": {},
    "params_schema": {"type": "object", "properties": {}},
    "estimated_vram_mb": 0,
}

class MyEchoPlugin(VoicePlugin):
    def manifest(self):
        return {"node_types": [NODE]}

    async def process_audio(self, instance_id: str, frame: AudioFrame, ctx: PluginContext):
        await ctx.emit_audio(instance_id, frame.samples, frame.sample_rate, frame.channels)

def create_plugin() -> VoicePlugin:
    return MyEchoPlugin()
```

## 可覆盖的方法（十一.）

```python
class VoicePlugin:
    def manifest(self) -> dict: ...                    # 声明 node_types / models
    async def initialize(self, ctx): ...               # worker 启动后一次
    async def load_model(self, instance_id, model_id, model_path) -> dict: ...
    async def process_audio(self, instance_id, frame, ctx): ...
    async def process_text(self, instance_id, event, ctx): ...
    async def process_tts(self, instance_id, request, ctx) -> AsyncIterator[EmitAudio]: ...
    async def on_control(self, instance_id, signal, ctx): ...
    async def interrupt(self, instance_id): ...
    async def health(self) -> dict: ...
    async def shutdown(self): ...
```

## 输出发射

```python
await ctx.emit_audio(instance_id, samples_bytes, sample_rate, channels=1, end_of_utterance=False)
await ctx.emit_text(instance_id, text, is_partial=True, is_final=False, stability=0.8)
await ctx.emit_control(instance_id, "vad_end", {"confidence": 0.9})
# 工作线程（run_in_executor）中安全发射：
ctx.emit_threadsafe(ctx.emit_audio(...))
```

## 参数 UI：JSON Schema（十八.）

`params_schema` 自动生成 GUI 控件，无需改前端：

```json
{
  "type": "object",
  "properties": {
    "speed": {"type": "number", "minimum": 0.5, "maximum": 1.5, "default": 1.0,
              "ui:widget": "slider", "unit": "x"},
    "mode": {"type": "string", "ui:widget": "select", "enum": ["a", "b"]},
    "note": {"type": "string", "ui:widget": "textarea"},
    "path": {"type": "string", "ui:widget": "file"}
  }
}
```

额外注解：`ui:group`（分组）、`requires_model_reload`、`runtime_modifiable`。
`Configure` RPC 会把实例参数写入 `ctx.params(instance_id)`（含 `__node_type__`）。

## 阻塞推理的正确姿势

CPU/GPU 推理放进线程池，避免卡死 gRPC 循环：

```python
loop = asyncio.get_running_loop()
await loop.run_in_executor(None, self._heavy_step, instance_id, frame, ctx)
```

参考实现：`plugins/ai/funasr/python/plugin_impl.py`。

## 调试

```powershell
# 手动起 worker
$env:PYTHONPATH = "sdk/python"
.venv\Scripts\python.exe -m voice_plugin_sdk.server --manifest-dir plugins\examples\myecho --port 5900

# 官方回环冒烟（gain 插件，验证环境）
.venv\Scripts\python.exe tests\smoke_plugin_sdk.py
```

## 模板生成

```powershell
.\scripts\create_plugin.ps1 my-plugin -Type tts   # dsp/text/tts/asr/vc/external
```

## 注意事项

1. 不同插件的模块可以同名（约定 `plugin_impl`），SDK 按文件路径唯一加载。
2. `python_env = "isolated"` 时宿主要求
   `app-data/runtimes/plugin-envs/<id>/` 存在独立 venv（GUI 修复环境可创建）。
3. 崩溃会被宿主自动重启（指数退避，10 分钟内 5 次封顶）——插件应保持幂等。
4. 网络权限默认关闭；确需联网的插件必须在 manifest 声明，安装时 GUI 高亮提示。
