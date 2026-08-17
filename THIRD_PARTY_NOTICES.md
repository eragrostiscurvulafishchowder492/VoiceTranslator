# Third-Party Notices

本仓库自有代码以 Apache-2.0 发布（见 `LICENSE`）。第三方代码、二进制、模型、
素材和服务不因被本项目调用而改用 Apache-2.0；适用条款始终以相应上游发布物为准。

本文是 2026-08-16 对仓库声明和本地可用材料的审计快照，不是法律意见，也不是完整的
发行版许可证包。状态含义如下：

- **仓库确认**：身份、版本或来源可由已跟踪文件直接复核。
- **本地材料确认**：本次工作目录旁的安装包元数据或上游许可证文件支持该结论；这些
  材料未必随仓库或最终发行物交付。
- **待确认**：lockfile/声明文件不包含足够的许可证文本或归属证据，发布前仍需人工或
  专用许可证清单工具复核。

## 声明与 lockfile 交叉检查

| 生态 | 仓库证据 | 本次覆盖 | 结论 |
|---|---|---:|---|
| Rust | 10 个 `Cargo.toml`、`Cargo.lock` v4 | 9 个工作区包；lock 中 607 个 package record（598 个 registry source、9 个本地包） | 包身份、解析版本、source/checksum 可确认；`Cargo.lock` 不记录许可证，598 个外部 record 的完整许可/NOTICE 集合待生成 |
| 前端 | `apps/desktop/package.json`、`pnpm-lock.yaml` v9 | 1 个 importer、8 个直接依赖、103 个 package key、103 个 snapshot key | 解析版本与 integrity 可确认；lockfile 不记录许可证，传递依赖的完整许可文本待生成 |
| Python | `requirements.txt` | 34 个直接条目，均以精确 `==` 版本固定 | 没有带哈希且覆盖传递依赖的 Python lock；wheel 身份、依赖闭包和许可证集合仍不能视为可复现发行清单 |

上表计数来自当前跟踪文件。`torch`/`torchaudio` 由文档要求单独安装，并不在
`requirements.txt`；`deps/CosyVoice` 由 `scripts/setup.ps1` 固定到 commit
`074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`，但仍不属于 Python lock 覆盖范围。

## 已确认的直接依赖材料

### Rust

工作区直接使用 Tauri、Tokio、Tonic/Prost/Protox、cpal、rubato、hound、rusqlite、
sysinfo、nvml-wrapper、zip、serde、日志/错误处理和并发工具等 crates。本地 cargo registry
中的相应 crate manifest 可确认常见的 Apache-2.0、MIT、BSD、ISC、MPL、Unicode、Zlib、
CC0 等许可表达式；但这只是本地材料确认，不能代替按 `Cargo.lock` 598 个外部 record
生成并随发行物归档的逐包许可证清单。

`rusqlite` 启用了 `bundled` SQLite。发布审查必须同时覆盖 `libsqlite3-sys` 所携带的
SQLite 材料，而不能只记录 Rust wrapper 的 MIT 元数据。

### 前端

本地已安装的直接包 `package.json` 与 `pnpm-lock.yaml` 解析版本一致：

该前端工作区在 `apps/desktop/package.json` 中声明 Node.js `24.x` 与
`pnpm@9.15.0`；这是仓库工具链约束，不是对本机安装状态、上游发布物或许可结论的声明。

| 包 | 解析版本 | 上游包元数据中的许可证 | 状态 |
|---|---:|---|---|
| `@tauri-apps/api` | 2.11.1 | Apache-2.0 OR MIT | 本地材料确认 |
| `@tauri-apps/plugin-dialog` | 2.7.2 | MIT OR Apache-2.0 | 本地材料确认 |
| `vue` | 3.5.41 | MIT | 本地材料确认 |
| `@tauri-apps/cli` | 2.11.4 | Apache-2.0 OR MIT | 本地材料确认 |
| `@vitejs/plugin-vue` | 5.2.4 | MIT | 本地材料确认 |
| `typescript` | 5.6.3 | Apache-2.0 | 本地材料确认 |
| `vue-tsc` | 3.3.9 | MIT | npm registry 与安装后 `package.json` 确认；Vue SFC 类型检查 CLI |
| `vite` | 5.4.21 | MIT | 本地材料确认 |

这 8 项不覆盖 103 个 package key 的传递闭包；发行清单仍为**待确认**。

### Python

`requirements.txt` 的 34 个直接条目为：

`numpy`, `sentencepiece`, `sounddevice`, `soundfile`, `soxr`, `scipy`, `PySide6`,
`funasr`, `modelscope`, `silero-vad`, `huggingface_hub`, `hyperpyyaml`, `grpcio`,
`protobuf`, `onnxruntime`,
`openai-whisper`, `inflect`, `wetext`, `transformers`, `librosa`, `einops`, `einx`,
`tiktoken`, `loguru`, `lightning-utilities`, `loralib`, `hydra-core`, `rich`, `keyboard`,
`psutil`, `requests`, `nvidia-ml-py`, `natsort`, `vector_quantize_pytorch`。

本地 Python distribution metadata 明确暴露了若干需要发行审查的许可族，包括
`soxr` 的 LGPL-2.1-or-later、`PySide6`/Qt 组件的 LGPL、`librosa` 的 ISC，以及常见的
Apache-2.0、MIT、BSD、MPL 和 PSF 许可。部分 distribution metadata 的 license 字段为空、
非 SPDX 文本或仅给出模糊名称，因此不能把整组依赖概括成“MIT 或 Apache-2.0”。

当前 `requirements.txt` 已固定 `sounddevice==0.5.5`、`soundfile==0.14.0`、
`soxr==1.1.0` 与 `einx==0.4.3`；后者满足 `vector_quantize_pytorch==1.31.1` 的
`einx>=0.3.0` 约束，并与本轮验证环境一致。该直接 pin 清单仍不能替代带 wheel hash 的
传递依赖 lock；文档约定的 PyTorch CUDA 变体也不由该文件固定。必须从最终构建环境
重新生成 Python 依赖与许可证清单。

## 外部仓库、模型与用户素材

| 组件 | 仓库中的获取证据 | 许可证状态 |
|---|---|---|
| CosyVoice source tree | `scripts/setup.ps1` 固定 commit `074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc`；本地 HEAD 与其一致 | 本地 `deps/CosyVoice/LICENSE` 为 Apache-2.0；发行时须对锁定 source tree 和子模块重验 |
| Matcha-TTS | 锁定 CosyVoice tree 的子模块；本地为 `dd9105b34bf2be2230f4aa1e4769fb586a3c824e` | 本地许可证为 MIT，并含 Shivam Mehta 2023 copyright notice；发行时须保留适用 notice |
| Fun-CosyVoice3-0.5B-2512 | `scripts/download_models.py` 从 ModelScope/Hugging Face 获取 | 模型目录没有本地 LICENSE；待确认具体 revision、模型卡条款与再分发范围 |
| paraformer streaming model | 同上 | 模型目录没有本地 LICENSE；待确认具体模型 ID/revision、模型卡条款与再分发范围 |
| silero-vad code/model | 插件通过 `torch.hub` 获取 | 获取 revision 未固定，跟踪文件中无随附许可证材料；待确认 |
| Fish Speech model/VQGAN asset | `scripts/download_models.py` 要求 owner 提供不可变 Hugging Face revision | 跟踪文件中无随附许可证材料；如进入发行或测试资产，须先确认 |
| 用户参考音频/音色 | 由用户导入 | 不随仓库授权；用户负责取得声音、录音、表演及素材所需权利 |

当前仓库不应分发 ignored 的 `models/`、`deps/` 或用户素材。模型下载按 provider/revision
使用独立 staging，Fish Speech 仍是可选项；其 HF commit、独立 VQGAN release asset 的 SHA-256
以及二者许可证/再分发条件均待 owner 复核。若发行流程将它们纳入产物，必须重新评估本文结论。

## 发布前 owner 门禁

在公开发布二进制、安装包、容器或带依赖的源码包前，项目所有者必须：

1. 为已固定的 Python 直接依赖生成带哈希的完整 lock，并冻结 torch wheel 来源以及每个
   模型 revision；
2. 从最终产物对应的 `Cargo.lock`、`pnpm-lock.yaml`、Python lock 和外部资产生成完整
   SBOM/许可证清单，并人工处理缺失、非 SPDX、copyleft 与平台条件项；
3. 归档并随产物提供所有要求的许可证全文、copyright/NOTICE 和源码/书面要约义务；
4. 对模型、声音素材及第三方仓库的使用和再分发权作明确决定；
5. 在依赖或产物发生变化后重新生成本文件，而不是沿用本审计快照。

本次仅做静态、本地许可证审计；没有启用远程自动化，也没有执行安全扫描或发布动作。
