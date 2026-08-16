# Third-Party Notices

本仓库代码以 Apache-2.0 发布（见 LICENSE）。以下第三方组件**不以源码形式包含在本仓库中**
（.gitignore 排除，由安装脚本获取），此清单说明其许可证以便合规使用与分发。

## Rust 宿主依赖（crates.io）

| crate | 许可证 |
|---|---|
| tauri 2 / tauri-build / tauri-plugin-global-shortcut / tauri-plugin-dialog | MIT 或 Apache-2.0 |
| tokio / tonic / prost / protox | MIT |
| cpal | Apache-2.0 |
| rubato | MIT |
| hound | Apache-2.0 |
| rusqlite（bundled SQLite） | MIT / SQLite 公有领域 |
| sysinfo | MIT |
| nvml-wrapper | MIT 或 Apache-2.0 |
| zip | MIT |
| sha2 / hex / bytemuck | MIT 或 Apache-2.0 |
| serde / serde_json / toml / anyhow / thiserror / log / env_logger / parking_lot / crossbeam-channel / uuid / chrono | MIT 或 Apache-2.0 |

## 前端依赖（npm）

| 包 | 许可证 |
|---|---|
| vue 3 / @vitejs/plugin-vue / vite / typescript | MIT |
| @tauri-apps/api / @tauri-apps/cli / @tauri-apps/plugin-dialog | MIT 或 Apache-2.0 |

## Python 运行环境（.venv，requirements.txt）

| 包 | 许可证 |
|---|---|
| torch / torchaudio | BSD-3-Clause |
| funasr | MIT |
| modelscope / grpcio / grpcio-tools | Apache-2.0 |
| protobuf | BSD-3-Clause |
| numpy / scipy / librosa | BSD-3-Clause |
| sounddevice | MIT（含 PortAudio，可分发） |
| soxr（libsoxr 绑定） | **LGPL-2.1（libsoxr）**——以独立进程动态调用，不链接进宿主二进制 |
| silero-vad（模型与代码） | MIT |
| PySide6（旧 app/gui） | LGPL-3（动态链接，可分发） |
| openai-whisper | MIT |
| wetext / inflect / einops / einx / tiktoken / loguru / hydra-core / rich / psutil / requests / nvidia-ml-py / natsort / vector-quantize-ptorch / sentencepiece / huggingface_hub / hyperpyyaml | MIT 或 Apache-2.0 |

## 外部仓库与模型（不入库，安装时获取）

| 组件 | 获取方式 | 许可证 |
|---|---|---|
| CosyVoice 仓库（deps/CosyVoice） | `git clone`（setup.ps1 自动） | Apache-2.0（已核对本地 LICENSE） |
| Matcha-TTS（deps 内 third_party） | 随 CosyVoice 仓库 | MIT |
| Fun-CosyVoice3-0.5B 模型 | ModelScope 官方源 | 遵循其模型许可（Apache-2.0 系） |
| paraformer-zh-streaming 模型 | ModelScope 官方源 | 遵循 ModelScope 模型许可 |
| silero-vad 模型 | torch.hub 官方 | MIT |

> 模型权重与 `deps/` 一律不随本仓库分发；使用者自行从官方源下载并遵守相应许可。
> 本项目不附带任何第三方角色语音素材；参考音频由使用者自行导入并自担授权责任。
