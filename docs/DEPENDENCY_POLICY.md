# Dependency Policy（Phase 0 冻结，2026-08-16）

选择标准（按规格二十七.）：当前仍维护 / 官方资料完整 / Windows 兼容良好 /
许可证允许 / 容易自动化安装 / 适合长期维护。

## 许可与可复现性门禁

版本进入本清单不等于已经批准分发。新增或升级依赖时必须同时更新声明文件和 lockfile，
并在 `THIRD_PARTY_NOTICES.md` 中记录来源、许可证据与仍待确认的义务。

- Rust 和前端分别以 `Cargo.lock`、`pnpm-lock.yaml` 的实际解析结果为准；不得只记录宽泛
  版本范围。
- 在发布二进制、预装环境或任何附带 Python wheel 的发行物前，必须采用可复现、带哈希并
  覆盖传递依赖的 lock；当前公开源码中的 `requirements.txt` 已精确固定 34 个直接条目，
  但仍不是可用于依赖再分发的完整 lock。
- Git 仓库依赖必须固定 commit；模型必须固定 provider、模型 ID、revision 和许可证材料。
- 模型下载只可从与 provider/revision 绑定的独立 staging 提升；可选 Fish Speech 还必须同时
  固定 HF commit 与独立 VQGAN asset 的 SHA-256，二者均不属于核心模型事务的成功条件。
- 所有第三方 SPDX 表达式、LICENSE、NOTICE/copyright 与 copyleft 条件必须按最终产物
  重新生成并人工复核。lockfile 本身不提供许可证授权。
- 不得把本项目的 Apache-2.0 元数据套用到第三方包、模型或用户导入素材。

当前 owner 门禁：确定许可证清单/SBOM 生成工具及允许列表；生成 Python 传递依赖/hash
lock，固定 PyTorch wheel/CUDA 变体和模型 revision；对 LGPL 组件及模型再分发作出审核
决定。这些决定未完成前，不得把本文称为完整的发行许可批准。

## 冻结版本清单

### 桌面宿主（Rust 1.97.1 · MSVC）

| 组件 | 版本 | 说明 |
|---|---|---|
| tauri | 2.x | 桌面框架（WebView2） |
| cpal | 0.15.3 | WASAPI 采集/播放（注意：0.15 API 为 default_input_config） |
| rubato | 0.15 | 高质量重采样 |
| tonic / prost / protox | 0.13 / 0.13 / 0.8 | gRPC；protox 免外部 protoc |
| rusqlite | 0.32（bundled） | SQLite，版本化迁移 |
| sysinfo + nvml-wrapper | 0.32 / 0.10 | CPU/内存/显存 |

### 前端（Node 24.x · pnpm 9.15.0）

vue 3.5 · vite 5 · typescript 5.6 · @tauri-apps/api 2

`vue-tsc` 固定为 `3.3.9`，仅用于 Vue SFC 类型检查；npm registry 与安装后包元数据均为
MIT，peer dependency 为 `typescript >=5.0.0`，与固定的 `typescript 5.6.3` 兼容。它是第
8 个前端直接依赖；`pnpm-lock.yaml` 所含传递包仍不在本节直接依赖许可声明范围内。

### Python（3.12.9 · .venv）

| 组件 | 版本 | 用途 |
|---|---|---|
| torch | 2.7.0+cu126 | 推理（cu126 wheel 与驱动 610.88 兼容） |
| funasr | 1.4.1 | 流式 ASR（chunk [0,10,5]） |
| CosyVoice | commit `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc` | 零样本 TTS；setup 脚本与本地 HEAD 一致，本地 LICENSE 为 Apache-2.0，发行时按锁定 tree/子模块重验 |
| silero-vad | 6.x | VAD（torch.hub） |
| grpcio / protobuf | 1.83.0 / 7.35.1 | 插件协议（Python 端） |
| sounddevice / soxr / soundfile | 0.5.5 / 1.1.0 / 0.14.0 | 音频 IO/重采样（旧 app/ 层）；直接版本已固定，传递闭包、wheel hash 与许可义务仍须发布前复核 |
| einx | 0.4.3 | 张量表达式；与 `vector_quantize_pytorch==1.31.1` 的 `einx>=0.3.0` 约束兼容 |

### 模型（官方源，本地 models/）

| 模型 | 位置 | 显存 |
|---|---|---|
| Fun-CosyVoice3-0.5B-2512 | models/CosyVoice3-0.5B | ~4.2GB fp16 |
| paraformer-zh-streaming | models/paraformer-streaming | ~0.9GB fp16 |

## 明确不采用 / 观望

| 项 | 原因 |
|---|---|
| Fish Speech 1.5 作实时引擎 | 实测 RTF 4.2（8GB 显卡不可实时），保留对照 |
| 共享内存数据面 | gRPC 实测开销 <2ms/帧，未见瓶颈（规格明确禁止过早实现） |
| torch.compile | Windows/onnx 组合收益低、稳定性风险（实测决定） |
| ASIO / WASAPI Exclusive | 第一版用 Shared（兼容性优先），后端边界已隔离可扩展 |
| 自研虚拟音频驱动 | 第一版依赖用户安装 VB-CABLE，绝不静默装驱动 |
| RVC / Seed-VC | 适配位保留，未伪实现 |

## 工具链、缓存与大文件策略

Rust 使用标准 rustup 安装并从 `PATH` 发现 Cargo；需要显式覆盖时设置
`VOICE_TRANSLATOR_CARGO` 为单一可执行文件。`CARGO_HOME`、`RUSTUP_HOME`、pnpm store、
pip cache 等可按贡献者环境自定义，但仓库脚本不注入私人盘符或固定缓存目录。
模型在仓库 `models/`（gitignore）；宿主包不包含模型、`.venv` 或 Python 依赖。
