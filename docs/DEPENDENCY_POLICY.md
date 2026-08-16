# Dependency Policy（Phase 0 冻结，2026-08-16）

选择标准（按规格二十七.）：当前仍维护 / 官方资料完整 / Windows 兼容良好 /
许可证允许 / 容易自动化安装 / 适合长期维护。

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

### 前端（Node 24 · pnpm 9）

vue 3.5 · vite 5 · typescript 5.6 · @tauri-apps/api 2

### Python（3.12.9 · .venv）

| 组件 | 版本 | 用途 |
|---|---|---|
| torch | 2.7.0+cu126 | 推理（cu126 wheel 与驱动 610.88 兼容） |
| funasr | 1.4.1 | 流式 ASR（chunk [0,10,5]） |
| CosyVoice | GitHub main @2026-08 | 零样本 TTS（deps/ clone，Apache-2.0） |
| silero-vad | 6.x | VAD（torch.hub） |
| grpcio / grpcio-tools | 1.83 | 插件协议（Python 端） |
| sounddevice / soxr / soundfile | 最新 | 音频 IO/重采样（旧 app/ 层） |

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

## 大文件策略（本机约定）

工具链与缓存一律 D 盘：`RUSTUP_HOME=D:\_toolchains\rustup`、
`CARGO_HOME=D:\_toolchains\cargo`、pnpm store / npm cache → `D:\_toolchains`。
模型在仓库 `models/`（gitignore），安装包不含模型。
