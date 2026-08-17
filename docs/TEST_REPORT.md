# Test Report — Voice Studio

日期：2026-08-17 · 当前 F9 环境：Windows PowerShell 5.1.26100.8875 · Node v24.14.0 · pnpm 9.15.0 · cargo/rustc 1.97.1 · rustfmt 1.9.0-stable · clippy 0.1.97

> 第 0 节是当前 worktree 的本地源码门禁。第 1 节以后均为较早环境的历史记录，不能替代
> 当前结果；AI/GPU/硬件/GUI/正式打包均不在 F9 范围内。

## 0. 当前本地源码门禁（F9，2026-08-17）

固定 Windows 环境：`PATHEXT=.COM;.EXE;.BAT;.CMD`；`VOICE_TRANSLATOR_CARGO=D:\_toolchains\cargo\bin\cargo.exe`；`CARGO_HOME=D:\_toolchains\cargo`；`RUSTUP_HOME=D:\_toolchains\rustup`。

| # | 命令（各执行一次，首非零即停止） | Exit | 关键摘要 |
|---:|---|---:|---|
| 1 | `cargo metadata --locked` | 0 | 607 packages、9 workspace members；stderr 仅 format-version 建议。 |
| 2 | `cargo fmt --all -- --check` | 0 | stdout/stderr 均为空。 |
| 3 | `cargo clippy --workspace --all-targets --locked -- -D warnings` | 0 | 无 warnings。 |
| 4 | `pnpm install --frozen-lockfile` | 0 | 641ms 完成；Node DEP0169 warning 不影响真实 exit。 |
| 5 | `pnpm --filter voice-studio-desktop check` | 0 | `vue-tsc --noEmit` + Vite 5.4.21；54 modules，1.82s。 |
| 6 | `.\scripts\test.ps1 -SkipAi` | 0 | workspace + desktop 共 21 passed / 0 failed：persistence 2、pipeline-core 10、plugin-host 6、lifecycle 1、`desktop_e2e_it.rs` 1、`host_pipeline_it.rs` 1；Python SDK SMOKE PASS；AI 未运行。 |
| 7 | `git diff --check` | 0 | 仅 Windows Git LF/CRLF 提示；无 whitespace error。 |

**PRE = POST。** branch `master`；HEAD `032b1ddb8b778438c857ef68b48e546311fe0949`；status-z SHA-256 `9d75c255bdbc53dfe8488635e7c3d037ea9228678cb936b8079419708450a424`；binary diff SHA-256 `38a8757b4d097a4db67b1d50149a8d1d924d2eddc825671446bb0f22f3d4519c`；staged diff SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`。tracked/untracked 集合、锁文件（`Cargo.lock`、`pnpm-lock.yaml`、`requirements.txt`）及其给定哈希均未改变；基线为 220 tracked、4 untracked（`CHANGELOG.md`、`CONTRIBUTING.md`、`SECURITY.md`、`docs/BUILDING.md`）。

早期 D/E3/E4 验证及其工具/文档 checker 限制仅保留为历史过程，不构成当前 PASS 或 FAIL。以下内容同样为历史验证记录；其中 AI、GPU、麦克风、GUI 与 soak 的结果不得提升为 F9 当前结论。

## 1. 发布前新增验证（历史记录）

### 1.1 手测自动化（用户验收清单的无耳版本，4/4 通过）

`cargo run -p voice-studio-desktop --example manual_test`（logs/manual_test_full.log）
——全部走 GUI start_pipeline 的**生产同路径**（start_pipeline_impl）：

| # | 用户清单对应 | 结果 |
|---|---|---|
| T1 变声管线 | 直接实时变声 | PASS：ZCR 0.060→0.089（升调），时长比 1.00（WSOLA+重采样正确） |
| T2 ASR 管线 | 中文 ASR 字幕 | PASS：真实语音→"你们先过去我拿一下东西马上回来"，相似度 0.91，partial 增量流完整 |
| T3 完整核心管线 | 中文语音转目标音色 | PASS：真实语音→ASR→稳定前缀断句→标准化→**CosyVoice 真实合成**→限幅→录制 3.56s WAV（RMS 0.068 / 峰值 0.533） |
| T4 原声监听 | 原声监听 | PASS：麦克风 584 帧流经管线，underrun=0 |

### 1.2 本轮发现并修复的产品 bug（全部由手测自动化暴露）

| bug | 影响 | 修复 |
|---|---|---|
| start_pipeline 插件判定用 `contains('.')` | **任何含内置节点的管线启动即失败**（"插件未安装: audio.file"） | 判据改 `contains('/')` |
| audio.ressembler 吞 EOS | 重采样节点 flush 无输出时不转发 end_of_stream，**下游 ASR 永远不 finalize** | EOS 标记必转发 |
| vc_pitch 音高算法不完整 | 只做时间压缩未重采样回原长，**变声输出缩短 25%**（磁带加速效应） | 重采样×r + WSOLA 拉回原时长 |
| 引擎边统计从不刷新 | GUI 性能页 sent/queue 恒 0 | snapshot 时从原子计数刷新 |
| 文件节点 EOS 重复发送 | 每 tick 重发 EOS（无害但脏日志/多余 finalize） | 发送一次后置哨兵 |

### 1.3 其他新增验证

| 项 | 结果 | 证据 |
|---|---|---|
| **实机麦克风采集** | PASS：HECATE G2 默认输入，3s 采集 131712 帧，RMS 0.0066 / peak 0.2544（检测到环境声），44.1kHz 自动处理，**溢出=0** | `cargo run -p voice-audio-engine --example mic_probe` |
| **GUI 十页视觉验证** | PASS：`--page=<id>` 深链接逐页截图（logs/screenshots/*.png），节点编辑器带预置管线 9 节点+连线完整渲染 | 10 张截图 |
| **桌面命令层 E2E** | PASS：text.manual_input → textkit.to_tts（真实 worker）经 **插件自动启动→Configure 下发→桥接→引擎调度** 产出正确 tts.request（3.9s） | logs/desktop_e2e.log |
| **隔离 venv 闭环** | PASS：tonegen 声明 isolated，自动创建 venv + SDK 依赖 + 握手 + 节点缓存（17.2s） | registry 15→25 节点 |

## 2. Rust 单元 + 集成测试（21 通过 / 0 失败）

`cargo test --workspace --exclude voice-studio-desktop`（logs/rust_tests.log）

| 套件 | 数量 | 覆盖 |
|---|---|---|
| pipeline-core | 10 | 端口类型解析、图序列化往返、**类型不匹配校验**、**循环检测（DFS）**、必需输入、缺失插件、显存预检、导出脱敏（绝对路径剥离）、背压策略解析、Payload 类型映射 |
| plugin-host 单元 | 6 | manifest 解析/校验、**未知权限解析期拒绝**、**api_version 主版本协商**、ZIP 安装往返 + checksums、**zip-slip 路径穿越拒绝**、**重启退避递增 + 次数上限** |
| persistence | 2 | 版本化迁移、管线 CRUD + 默认唯一、last_known_good、会话状态、声音档案、事件 |
| plugin-host 集成 | 1 | **宿主⇄真实 Python worker 全生命周期**（见下） |
| 桌面命令层 E2E | 1 | **插件自动启动 + Configure 下发 + 桥接 + 引擎调度**（真实 worker，见第 0 节） |
| 桌面原生管线 | 1 | WAV 文件→+6dB 增益→录制（48000 样本数值验证） |

### 插件生命周期集成测试（最关键验收证据，logs/lifecycle_test.log）

```
[lifecycle] worker pid=Some(56688) port=Some(64988)
[lifecycle] crash detected → state=stopped
[lifecycle] PASS — finished in 4.60s
```

验证链：临时 app-data 安装 gain 插件 → discover → spawn 独立 worker 进程 →
gRPC 握手（协议 1.0 协商）→ node_types 返回 → 注册表合并 → 数据面双向流
（480 样本音频回环，0dB 原样断言）→ **taskkill 强杀 worker → 宿主进程存活、
状态正确转移** → 优雅停止幂等。

## 3. Python SDK 回环（tests/smoke_plugin_sdk.py）

```
[1] worker 就绪 OK            [4] 音频回环 OK: 0.25 -> 0.4988 (+6dB 数值精确)
[2] 握手 OK（节点类型返回）     [5] Health OK
[3] Configure OK              [6] 优雅退出 OK (exit 0)
SMOKE PASS
```

## 4. 真实 AI 管线冒烟（tests/smoke_ai_pipeline.py，logs/smoke_ai.log）

经 gRPC 插件 worker 全链路（非直接调用引擎）：

```
[1] textkit + cosyvoice worker 就绪（独立进程）
[3] TTS 输出 OK: 4.76s 真实音频, 写入 logs/smoke_ai_tts.wav
[5] 断句 OK: ['你们先过去，我拿一下东西，马上']
AI PIPELINE SMOKE PASS
```

- CosyVoice3-0.5B 真实推理（worker 显存 4.6GB），流式 chunk 经 gRPC 双向流回传。
- 断句器（稳定前缀算法，复用 app/pipeline/chunker.py）经 Configure→增量 partial→final 全链路正确切分。
- TTFA 43.9s 为**冷启动**（首请求触发模型懒加载）；模型常驻后由 PERFORMANCE_REPORT 的基准覆盖。

## 5. 桌面应用

- 构建成功（debug + release），**启动冒烟**：进程存活 6s+、app-data 目录结构
  （database/plugins/models/references/pipelines/presets/logs/cache/temp/runtimes）完整创建。
- GUI 页面/节点编辑器为声明式 Vue 组件；自动化点击未纳入本轮（无 GUI 自动化框架），
  需要人工验收的部分已在 FINAL_REPORT 第 8 节如实列出。

## 6. 长时间运行（Soak，沿用 Python 引擎层）

- 30.06 分钟 / 345 轮全链路：错误率 0.29%（1/345）、avg_sim 0.919、
  **VRAM 6523MB × 345/345 轮零增长**、TTS 耗时无漂移（5 区块均值无单调上升）。
- 原始数据：logs/simulate_results.json、logs/simulate_30min.log。
- 注：soak 在引擎层执行（ASR/TTS 与桌面插件共享同一 app/ 引擎代码）；
  桌面 GUI 层 30 分钟 soak 列入已知未完成项（FINAL_REPORT 8.2）。

## 7. 测试覆盖缺口（如实）

1. 设备拔插/OOM/断流的故障注入为部分实现（热插拔轮询已实现并有保护逻辑，
   自动化注入测试未写）。
2. GUI 交互级自动化（点击/拖拽）未实现；视觉渲染已用截图验证覆盖。
3. VB-CABLE 虚拟输出：本机未安装，无法实测（逻辑与检测已实现）。
