# Voice Studio

可视化、可插拔、可组合的**本地实时语音处理平台**（Windows 11 优先）。

```
麦克风 → 降噪/VAD → ASR → 文本处理 → zero-shot TTS → 音频效果 → 虚拟麦克风
```

用户在节点图（Pipeline Studio）中自由组合管线；ASR/TTS/VC/DSP 由独立进程的插件提供，
新增能力不需要修改宿主核心代码。

## 快速开始（开发者）

```powershell
.\scripts\setup.ps1     # 环境 + 构建 + 内置插件安装 + Smoke Test
.\scripts\run.ps1       # 启动桌面应用
.\scripts\test.ps1      # 全部测试（-Soak 增加 30 分钟长稳）
.\scripts\diagnose.ps1  # 环境诊断
.\scripts\package.ps1   # NSIS 安装包 + Portable ZIP + SHA-256
```

普通用户流程：安装 → 首启向导 → 选择麦克风/输出 → 启用 AI 插件 → 模型就位 →
加载预置管线 → 开始使用。

## 主要能力（当前版本）

- **桌面宿主**：Tauri 2 + Rust（8 个 crate：audio-engine / pipeline-core / plugin-host /
  plugin-protocol / persistence / resource-manager / diagnostics / common）+ Vue 3 GUI
  （十页导航 + SVG 节点编辑器 + Schema 驱动参数面板）。
- **插件系统**：Python SDK（gRPC 控制面 + 双向流数据面）、独立 worker 进程、
  协议版本协商、心跳、崩溃重启（指数退避 + 次数限制）、ZIP 安装（校验和、zip-slip 防护）。
- **真实 AI 插件**：FunASR 流式中文识别（复用已验证的增量合并修复）、
  CosyVoice3 零样本 TTS（fast LLM 解码器）、中文文本工具（稳定前缀/断句/标准化）、
  实时变声（WSOLA 音高+共振峰，真实 DSP 算法）。
- **示例插件**：Audio Gain / Text Replace / Test Tone / Null Output / 外部命令包装，
  另有 `scripts\create_plugin.ps1` 一键生成插件模板。
- **音频引擎**：WASAPI（cpal）采集/播放、无锁 RingBuffer、rubato 重采样、
  HPF/噪声门/限幅器、5ms crossfade、underrun/溢出统计、设备热插拔检测。
- **内置节点**：麦克风、扬声器/虚拟输出、WAV 输入/录制、增益、噪声门、限幅、
  高通、重采样、声道转换、PTT、文本输入/输出、指标（12.1 全部）。
- **管线引擎**：类型化端口（10 种）、连接前校验（类型/采样率/声道/循环/必需参数/
  插件存在/显存预检）、有界队列 + 5 种背压策略、节点状态机。
- **预置管线**：原声监听 / 中文 ASR 字幕 / 中文语音转目标音色（核心用例）/
  直接实时变声 / 双路输出 / 翻译语音模板（显式标注缺失依赖）。
- **热键**：F8 PTT / F9 静音 / F10 清队列 / F11 中断（可配置）。
- **持久化**：SQLite（版本化迁移）+ last_known_good + 崩溃恢复（安全模式）。

## 目录

```
apps/desktop/       Tauri 2 + Vue 3 桌面应用
crates/             Rust 宿主 crate ×8
proto/              插件协议（Protobuf，Rust/Python 双端生成）
sdk/python/         Python Plugin SDK
plugins/examples/   示例插件 ×5
plugins/ai/         真实 AI 插件 ×4
app/                既有 Python 语音引擎（被 AI 插件复用：ASR/TTS/断句/标准化）
scripts/            setup/run/diagnose/test/package/create_plugin
tests/              Rust 之外的综合测试（SDK 回环 / AI 冒烟 / 30min soak）
docs/               全部文档
```

## 隐私与许可

- 全部推理本地进行；不上传麦克风音频、参考音频、转写文本。
- 不附带任何第三方角色语音；音色由用户自行导入。
- 网络权限默认关闭；模型下载是唯一联网行为（官方源，一次性）。
- 进程隔离不等于完整安全沙箱（见 docs/SECURITY.md）。

详细文档：[ARCHITECTURE](docs/ARCHITECTURE.md) · [PLUGIN_DEVELOPMENT](docs/PLUGIN_DEVELOPMENT.md) ·
[PLUGIN_MANIFEST](docs/PLUGIN_MANIFEST.md) · [PROTOCOL](docs/PROTOCOL.md) ·
[AUDIO_ENGINE](docs/AUDIO_ENGINE.md) · [SECURITY](docs/SECURITY.md) ·
[TROUBLESHOOTING](docs/TROUBLESHOOTING.md) · [TEST_REPORT](docs/TEST_REPORT.md) ·
[PERFORMANCE_REPORT](docs/PERFORMANCE_REPORT.md) · [FINAL_REPORT](docs/FINAL_REPORT.md)
