[English](README.md) | [简体中文](README.zh-CN.md)

# Voice Studio

面向 Windows、本地优先的实时语音工作台：用可视化节点把采集、识别、文本处理、合成、变声、监听和虚拟输出组合成自己的语音管线。

桌面宿主和非 AI 路径可以从源码构建；AI 模型与硬件相关运行时按需另行准备。

> **项目状态：** 当前仓库已整理为可在本机从源码构建的工程，但这不等于已经存在公开二进制、托管下载或已启用的远程自动化。二进制分发、模型再分发、第三方许可材料以及特定硬件上的 AI 运行栈仍需独立验收和 owner 决策。

~~~text
麦克风 → DSP / VAD → ASR → 文本工具 → 零样本 TTS / 变声效果 → 监听或虚拟输出
~~~

## 核心能力

- **可视化管线工作室：** 自由连接类型化节点，启动前校验连接，加载预置，并用有界队列与背压策略控制实时数据流。
- **Windows 音频宿主：** 基于 cpal 的 WASAPI 采集/播放，以及重采样、WAV 输入与录制、增益、高通、噪声门、限幅、声道转换和设备变更保护。
- **本地插件进程：** Python 插件以独立进程运行，通过版本化 gRPC 控制面和流式数据面与宿主通信。
- **内置语音流程：** FunASR 流式识别、CosyVoice3 零样本 TTS、中文断句与标准化、音高/共振峰变声，以及无需 AI 的示例插件。
- **运行控制：** 按键说话、静音、清队列、中断、设备/模型/插件管理、声音档案、测试实验室、本地日志和崩溃恢复。
- **可扩展界面：** Vue 根据插件参数 Schema 生成控件，不允许插件向 WebView 注入任意脚本。

## 界面导览

### 先搭好信号链

![Voice Studio 管线编辑器展示麦克风、重采样和流式识别节点](logs/screenshots/studio2.png)

*节点编辑器可以组合内置音频处理器和插件节点，并提供预置、校验、导入导出以及 Schema 驱动的属性面板。*

### 再从一个界面控制运行

![Voice Studio 实时语音页展示按键说话和运行指标](logs/screenshots/live.png)

*实时语音页集中放置启动停止、按键说话、静音、清队列、中断、识别文本、电平和运行状态。*

### 参考音频只保存在本地

![Voice Studio 声音档案页用于导入本地参考音频](logs/screenshots/voice.png)

*声音档案引用用户自行提供、保存在本地应用数据中的 WAV；项目不附带第三方角色语音。*

### 把模型来源摆到明面上

![Voice Studio 模型管理页展示本地模型目录](logs/screenshots/models.png)

*模型作为本地资产管理，不进入源码树或宿主安装包；实际模型必须来自 owner 批准的 provider revision。*

### 看清插件边界

![Voice Studio 插件管理页展示权限与 worker 环境](logs/screenshots/plugins.png)

*插件页展示版本、声明权限、运行环境、状态、日志和生命周期操作。*

## 架构

| 层 | 职责 |
|---|---|
| **Tauri 2 + Rust 宿主** | 负责窗口、IPC、热键、设备、音频回调、管线调度、插件生命周期、持久化、资源预检和诊断；具体能力分布在8个 workspace crate 中。 |
| **Vue 3 界面** | 提供管线画布、实时控制、声音档案、模型、插件、设备、测试、设置和 Schema 参数面板；不承担推理或音频 DSP。 |
| **Python SDK 与 worker** | 提供版本化插件 API、独立 worker、gRPC 控制/流式传输，并复用仓库已有的 ASR、TTS、文本和语音处理引擎。 |
| **本地状态** | SQLite 与 app-data 目录保存设置、管线、插件、参考音频、模型、日志、缓存和恢复状态。 |

标准数据路径留在本机：

~~~text
Vue 界面 ──Tauri IPC──> Rust 宿主 ──127.0.0.1 gRPC──> Python 插件 worker
                            │
                            └── WASAPI / 文件 / SQLite / 本地应用数据
~~~

目录分工：

~~~text
apps/desktop/          Tauri 2 + Vue 桌面应用
crates/                8个 Rust 宿主 crate
proto/                 版本化插件协议
sdk/python/            Python Plugin SDK
plugins/ai/            FunASR、CosyVoice、TextKit、音高/共振峰插件
plugins/examples/      5个非 AI 示例插件
app/                   可复用的 Python 语音引擎
scripts/               setup、run、test、诊断、模型和打包入口
docs/                  架构、构建、插件、安全和依赖文档
~~~

详细边界见[架构说明](docs/ARCHITECTURE.md)、[音频引擎](docs/AUDIO_ENGINE.md)与[协议说明](docs/PROTOCOL.md)。

## 从源码快速开始

### 环境要求

在 Windows 11 的 Windows PowerShell 5.1 中，从仓库根目录操作：

- Node.js 24.x 与 pnpm 9.15.0
- Python 3.12.x
- 通过 rustup 安装的 Rust/Cargo
- Visual Studio 2022「使用 C++ 的桌面开发」工作负载与 Windows SDK
- Git
- Windows 输入/输出音频设备

仓库尚未用 rust-toolchain.toml 固定 Rust channel。需要自定义 Cargo 时可设置 VOICE_TRANSLATOR_CARGO；仓库不要求任何私人工具链目录。

### 初始化并启动

~~~powershell
.\scripts\setup.ps1
.\scripts\run.ps1
~~~

setup.ps1 会检查工具链，创建或更新 .venv，安装已固定版本的 Python 直接依赖，核对锁定的 CosyVoice source tree，执行 frozen pnpm install，以锁定依赖构建前端和 Rust 宿主，把9个内置插件安装到本地应用数据，并运行 Python SDK smoke test。

它**不会**下载 AI 模型、替你选择 torch/torchaudio、安装虚拟音频驱动、生成安装包，也不能证明已经达到发布条件。

需要开发模式窗口时：

~~~powershell
.\scripts\run.ps1 -Dev
~~~

只有 pip、pnpm、Cargo、CosyVoice 与模型输入都已预热时，才可使用离线模式：

~~~powershell
.\scripts\setup.ps1 -Offline
.\scripts\run.ps1 -Offline
~~~

准备 AI 或离线环境前，请先读[本地安装、构建与首用](docs/BUILDING.md)和[排障指南](docs/TROUBLESHOOTING.md)。

## 首次使用、模型、联网与硬件边界

1. 在「音频设备」中选择麦克风和监听输出。
2. 先使用内置非 AI 路径，或按下文准备 AI 运行栈。
3. 在「管线工作室」加载预置或搭建管线，校验后从工作室或实时语音页启动。
4. 需要虚拟麦克风时，手动安装 VB-CABLE 等兼容驱动并选择对应输入/输出。Voice Studio 不会自行安装驱动或申请管理员权限。

### 模型与 AI

- 模型是被 gitignore 排除的本地资产，不随源码仓库、NSIS 宿主包或 Portable 宿主包分发。
- requirements.txt 固定了34个 Python 直接依赖版本，但还不是覆盖全部传递依赖与 wheel hash 的完整 lock。
- torch 与 torchaudio 被刻意留在 requirements.txt 之外，CPU/CUDA 目标、来源、版本和 wheel hash 必须由 owner 批准。
- 模型下载器要求传入不可变、经 owner 批准的 provider revision。使用前先查看当前参数：

~~~powershell
.\.venv\Scripts\python.exe scripts\download_models.py --help
~~~

- 模型许可、声音权利、显存需求、推理速度和音质都取决于具体模型与硬件；本文不写单一 GPU 或延迟承诺。

### 联网行为

| 操作 | 预期联网边界 |
|---|---|
| 联网 setup | 可能访问 pip/pnpm registry、Cargo source 与锁定的 CosyVoice Git source。 |
| 离线 setup | 使用 no-index/offline 模式；缺少缓存或 source tree 时直接失败。 |
| 模型准备 | 仅显式执行；从 owner 提供的 provider/revision 下载，通过必需文件检查后记录本地 provenance。 |
| 正常音频处理 | 标准配置下，麦克风音频、参考音频、转写文本、管线和日志留在本机。 |
| 第三方插件 | 声明 network 权限的插件可能对外联网；权限可见，但不是操作系统级沙箱。 |

只安装可信插件。进程隔离能限制崩溃扩散，却不会强制隔离文件系统和网络；详见[安全架构](docs/SECURITY.md)。

## 开发与测试

统一使用仓库脚本：

~~~powershell
# 贡献者基线：Rust workspace + 完整 desktop package + Python SDK 回环
.\scripts\test.ps1 -SkipAi

# 增加真实 AI 管线门禁；需要已批准的模型、运行时和硬件
.\scripts\test.ps1

# 在所选测试路径后增加30分钟 soak
.\scripts\test.ps1 -Soak
~~~

脚本在首个失败处停止并保留原始 exit code。AI/GPU、物理音频设备、虚拟路由、GUI 和长稳结果都是独立门禁；不能用非 AI 结果替代。

当前 manifest 定义的前端类型与构建检查：

~~~powershell
pnpm --filter voice-studio-desktop check
~~~

本 README 只记录真实入口，不声称本次文档工作运行过上述门禁。

## 插件 SDK

Python SDK 位于 sdk/python/voice_plugin_sdk。插件提供 plugin.toml 与 Python factory，声明权限和运行要求，并在版本化握手时返回类型化节点 Schema。

生成插件模板：

~~~powershell
.\scripts\create_plugin.ps1 my-plugin -Type tts
~~~

支持 dsp、text、tts、asr、vc、external 六类模板。生成结果默认使用 Apache-2.0 package metadata，若目标已存在则拒绝覆盖。

后续开发见[插件 SDK 指南](docs/PLUGIN_DEVELOPMENT.md)与[Manifest 参考](docs/PLUGIN_MANIFEST.md)。

## 当前状态、下一步与已知限制

### 当前源码已经具备

- Tauri/Vue 桌面宿主、Rust 音频与管线层、Python SDK、4个 AI 插件适配器、5个示例插件、预置、本地持久化、诊断和源码构建脚本均已进入源码树。
- 源码可获得、存在构建入口，不等于已经有经过验证的公开二进制。
- 公开源码本身不能证明已经存在 GitHub Release、公开二进制下载、已启用 CI、下载量或支持 SLA。

### 扩大分发前仍需决定和验证

- 批准并固定 Rust toolchain。
- 生成完整 Python 传递依赖/hash lock，并批准 torch/torchaudio 目标。
- 批准不可变模型 revision，以及相应许可和再分发条件。
- 为实际发行物生成 SBOM、许可证全文、copyright 与 NOTICE。
- 在目标发布硬件上验证打包、Windows GUI、物理音频、虚拟路由、AI/GPU 和长时间运行。
- 制定版本支持策略以及适用的支持 SLA。

### 已知限制与扩展点

- Windows 11 是当前主平台，不声明支持其他桌面平台。
- 虚拟麦克风依赖用户另行安装驱动。
- 插件权限目前是声明式的；Job Object/AppContainer 真沙箱属于架构扩展点。
- 当前以 WASAPI Shared 为基线。Exclusive、ASIO、Rust/external/http 插件 runtime、共享内存传输和远程插件索引都是可能的扩展点，不是发布承诺。
- 模型下载、模型许可与用户提供的声音不属于本项目 Apache-2.0 授权范围。

当前 owner 门禁见[依赖政策](docs/DEPENDENCY_POLICY.md)与[第三方声明](THIRD_PARTY_NOTICES.md)。

## 贡献、安全与许可

- 贡献指南：[CONTRIBUTING.md](CONTRIBUTING.md)
- 漏洞报告政策：[SECURITY.md](SECURITY.md)
- 安全与隐私架构：[docs/SECURITY.md](docs/SECURITY.md)
- 变更记录：[CHANGELOG.md](CHANGELOG.md)
- 第三方声明：[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)
- 项目许可：[Apache License 2.0](LICENSE)

Apache-2.0 只覆盖本仓库自有代码；依赖、外部 source tree、模型、驱动与用户提供的音频分别受各自条款约束。
