# 本地安装、构建与打包

本项目的“可复现”指使用已锁定的前端、Rust 与 Python 直接依赖重建同一源树。NSIS 与 ZIP 会带工具链和文件时间戳，当前不承诺字节级可复现。

## 工具链基线

- Windows PowerShell 5.1（脚本保持 UTF-8 BOM）。
- Node.js `24.x`（本轮 Windows 门禁为 `v24.14.0`）；`apps/desktop/package.json` 声明 `pnpm@9.15.0`。
- Python `3.12.x`；`requirements.txt` 锁定 34 条项目直接依赖版本。
- Rust/Cargo 版本尚未由仓库内 `rust-toolchain.toml` 锁定。在 owner 批准工具链前，脚本会记录实际 `cargo --version`，但不将任意本地版本写成项目决策。

Cargo 默认按 `PATH` 顺序解析第一个 `cargo` Application。需要使用自定义安装时，可把
`VOICE_TRANSLATOR_CARGO` 设置为一个明确的可执行文件；空值、目录、不存在的路径或不能
解析为单一 Application 的值会立即失败。标准 `CARGO_HOME`、`RUSTUP_HOME`、pnpm store
和 pip cache 都可由贡献者自行配置，仓库不注入私人工具链目录。

锁文件的使用规则：

- `pnpm install --frozen-lockfile` 使用 `pnpm-lock.yaml`；锁文件与 `package.json` 不一致就失败。
- `cargo build --locked` 使用 `Cargo.lock`；打包前也先运行 `cargo metadata --locked`。
- Python 目前是“锁定直接依赖版本”，还不是带 wheel hash 的完整跨平台 lock。`torch`/`torchaudio` 也不在本文件中擅自选择 CUDA ABI；见末尾 owner 决策。

## 首次联网安装

在仓库根目录使用 Windows PowerShell 5.1：

```powershell
.\scripts\setup.ps1
```

脚本会按顺序检查工具版本、创建 `.venv`、同步 Python 直接依赖、验证或获取锁定的
CosyVoice source tree、执行 `pnpm install --frozen-lockfile`、通过真实 workspace 入口
`pnpm --filter voice-studio-desktop build` 生成 `apps/desktop/dist`，然后才执行
`cargo build --locked -p voice-studio-desktop`，安装内置插件并运行 SDK smoke test。任一
原生进程返回非零时，脚本立即以同一 exit code 结束，不继续到 Rust build、应用启动或
“完成”消息。setup 建立开发/运行环境，不生成 NSIS、ZIP，也不代表发行打包完成。

联网 setup 可能访问 pip index、pnpm registry、crates.io/Cargo git source 和 CosyVoice git
remote；这些是开发构建期取依赖，与应用运行时隐私边界不同。

CosyVoice 代码只检出本地已存在且曾用于本项目的副本提交：

```text
FunAudioLLM/CosyVoice@074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc
```

该 SHA 来自 2026-08-16 修改前已存在的 `deps/CosyVoice` checkout，不是新选的上游版本。已存在副本若不匹配，`setup.ps1` 会失败而不覆盖它。子模块由该 superproject commit 继续锁定。

## 离线边界

```powershell
.\scripts\setup.ps1 -Offline
```

离线模式不会获取 CosyVoice，pip 使用 `--no-index`，pnpm 使用 `--offline`，Cargo 使用 `--offline`。因此运行前必须同时具备：

- 匹配 SHA 且子模块已初始化的 `deps/CosyVoice`；
- pip 缓存中的所有必需 wheel/sdist；
- 完整 pnpm store 与 Cargo registry/git 缓存；
- 已由 owner 选择且预装的 `torch`/`torchaudio` 组合。

模型不是 setup 的必需下载项。大模型只能通过显式、不可变的 provider revision 下载：

```powershell
.\.venv\Scripts\python.exe scripts\download_models.py `
  --paraformer-ms-revision <OWNER_APPROVED_REVISION> `
  --cosyvoice-ms-revision <OWNER_APPROVED_REVISION> `
  --cosyvoice-hf-revision <40_HEX_COMMIT>
```

不传核心模型 revision 就会在下载前失败。脚本不再访问 `resolve/main`，也不再将“目录有任意文件”当作已验证下载。每个 provider/revision 使用独立的隐藏 partial 目录，ModelScope 失败后的 Hugging Face fallback 不会复用前者的部分文件；只有必需文件校验通过后才写 provenance marker 并提升为最终目录。现有 `.completed` 为旧的 `ok` 文本时不会被伪装成已锁定快照；需核对后重新下载到空目录。

Fish Speech 是可选对照模型，不属于上面三个核心参数的成功条件，也不与核心模型事务共享 staging。若 owner 决定准备它，必须同时固定 HF commit 和独立 VQGAN release asset 的 SHA-256；其许可证与再分发条件仍待 owner 复核：

```powershell
.\.venv\Scripts\python.exe scripts\download_models.py `
  --paraformer-ms-revision <OWNER_APPROVED_REVISION> `
  --cosyvoice-ms-revision <OWNER_APPROVED_REVISION> `
  --cosyvoice-hf-revision <40_HEX_COMMIT> `
  --fish-hf-revision <40_HEX_COMMIT> `
  --fish-vq-sha256 <64_HEX_SHA256>
```

## 打包及成功判据

```powershell
.\scripts\package.ps1
# 所有依赖均已预热时：
.\scripts\package.ps1 -Offline
```

`package.ps1` 先解析工具链并运行 `cargo metadata --locked`，再执行
`pnpm install --frozen-lockfile`、真实 workspace 前端 build，以及 workspace 内固定版本的
Tauri CLI。Tauri build 显式以已解析的 `cargo` 可执行文件作为 `--runner`，并把
`--locked`（离线时还包括 `--offline`）传给底层 Cargo。Tauri 或 NSIS 失败会立即非零退出，
没有 `cargo build --release` fallback。该命令是正式打包动作，不属于普通 source-ready
检查；应只在 owner 授权后执行。

只有下列条件全部满足才会打印“打包成功”：

1. Tauri CLI exit code 为 0；
2. `target/release/voice-studio-desktop.exe` 存在；
3. `target/release/bundle/nsis/` 中恰好有一个 `.exe`；
4. Portable ZIP 生成且 NSIS/ZIP 都完成 SHA-256 计算。

成功产物位于：

```text
dist-package/<NSIS installer>.exe
dist-package/VoiceStudio-Portable.zip
dist-package/SHA256SUMS.txt
logs/tauri_build.log
```

Portable ZIP 只包含宿主 exe、`plugins/` 与 `sdk/`；NSIS/ZIP 均不包含 `models/`、`.venv/`
或 Python 依赖。因此它们是**宿主便携包，需另配兼容的 Python 环境、已批准的
torch/torchaudio 组合与模型**，不是开箱即用的 AI 发行版。脚本会在 Tauri 成功之后重建
`dist-package/`，因此该目录只能用作可重建产物，不应放置手工文件。源码达到公开仓库
就绪条件也不等于二进制获准再分发；完整依赖许可包与 owner 决策仍是独立门禁。

## 构建后启动

```powershell
.\scripts\run.ps1
# debug 宿主：
.\scripts\run.ps1 -Dev
```

默认 release 路径会执行 frozen install、前端 build，以及已解析的 Cargo 可执行文件的
`cargo build --locked --release`（离线时加 `--offline`），只有构建成功才启动 release exe。
`-Dev` 在 frozen install 后通过真实 workspace 入口运行 `tauri dev`：Tauri CLI 会启动并管理
Vite dev server（`devUrl`）与桌面应用，并显式以已解析的 Cargo 可执行文件作为 `--runner`，
把 `--locked`（离线时还包括 `--offline`）传给 Cargo；它不预先构建或直接启动 debug exe。
任一子命令失败都原样传播 exit code，且不会启动旧 exe。`-Offline` 要求 pnpm/Cargo 缓存已预热。

## Owner 待决策

1. 批准 Rust toolchain channel/version，然后在后续授权范围内添加 `rust-toolchain.toml`。
2. 批准 Windows CPU/CUDA 目标和 `torch`/`torchaudio` 版本、index 及 wheel hash；再生成 Python 3.12 的完整 transitive hash lock。
3. 确认是否将现有 CosyVoice SHA `074ca6d...` 作为长期基线，或提供另一个经测试的 commit。
4. 为 Paraformer 与 CosyVoice 的 ModelScope 快照、CosyVoice 的 HF fallback 选择不可变 revision。若启用可选 Fish，还须同时批准其 HF commit 与 v1.5.1 VQGAN release asset 的 SHA-256。现有 fish-speech 的 HF 本地 metadata 显示候选 commit `275a984d33c33659e39eed41ff5bcd6e67517f4c`，但在 owner 确认前不写成默认值。
