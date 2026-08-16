# Voice Studio — 最终报告（FINAL REPORT）

日期：2026-08-16
环境：Windows 11 · RTX 4060 Laptop 8GB · Rust 1.97.1 · Node 24 · Python 3.12.9

> 只记录真实运行得出的数据。所有数字在 logs/ 有原始记录，复现命令见第 9 节。
> 未完成项与人工验收项在第 8 节明确列出，不做隐瞒。

---

## 1. 交付物总览

| 交付物 | 位置 | 状态 |
|---|---|---|
| Tauri 2 + Rust 宿主（8 crate） | `crates/` + `apps/desktop/src-tauri/` | ✅ 构建通过、启动冒烟通过 |
| Vue 3 GUI（十页导航 + SVG 节点编辑器 + Schema 参数面板） | `apps/desktop/src/` | ✅ 构建通过 |
| Protobuf + gRPC 插件协议 v1 | `proto/voice_plugin_v1.proto` | ✅ Rust/Python 双端生成并验证 |
| Python Plugin SDK | `sdk/python/voice_plugin_sdk/` | ✅ 回环 E2E 通过 |
| 示例插件 ×5 | `plugins/examples/` | ✅ 全部加载验证 |
| 真实 AI 插件 ×4（ASR/TTS/文本工具/变声） | `plugins/ai/` | ✅ ASR/TTS/文本工具真实推理验证；VC 为真实 DSP 算法 |
| 预置管线 ×6 | 宿主内置（首启写 DB） | ✅ |
| 自动化脚本 ×6 | `scripts/*.ps1` | ✅ |
| 测试（Rust 20 + SDK + AI 冒烟 + 30min soak） | `crates/*/tests`、`tests/` | ✅ 全部通过（0 失败） |
| 安装包 + Portable ZIP + SHA-256 | `dist-package/` | 见第 7 节 |
| 文档 ×11 | `docs/` + README | ✅ |

## 2. 架构落地与规格对照

按规格 26 节的 Monorepo 布局落地（crates ×8 / apps/desktop / proto / sdk/python /
plugins/{examples,ai} / scripts / tests），模块边界与依赖方向见
docs/ARCHITECTURE.md 第 2 节（每个 crate 有明确"禁止"清单）。

核心机制对照：

- **管线**：类型化端口 ×10、连接前校验（类型/采样率/声道/循环/必需参数/插件/
  显存预检）、每边有界通道 + BLOCK/DROP_OLDEST/DROP_NEWEST/LATEST_ONLY/
  FAIL_PIPELINE、管线状态机（6 态）、节点状态机（7 态）。
- **插件**：manifest（TOML，权限白名单解析期校验）、ZIP 安装（zip-slip 防护 +
  checksums）、独立 worker 进程、协议版本协商（主版本不符拒绝运行）、心跳 5s、
  崩溃指数退避重启（10 分钟 5 次封顶）、stdout/stderr 采集、启用/禁用/卸载。
- **GUI**：首页/实时语音/管线工作室/声音档案/模型/插件/音频设备/测试实验室/
  性能与日志/设置；节点编辑器支持拖入、拖线（类型校验）、多选、复制粘贴、
  撤销重做、缩放平移、旁路、备注、导入导出、一键启停。
- **音频**：cpal/WASAPI、无锁 SPSC ring（AtomicU32）、rubato 重采样、
  HPF/门/限幅、5ms crossfade、underrun/溢出计数、热插拔 5s 轮询（设备消失
  自动停管线）、稳定键（名称，不持久化索引）。
- **持久化**：SQLite WAL + 版本化迁移、last_known_good、崩溃标记 →
  首启安全模式弹窗。
- **热键**：F8 PTT / F9 静音 / F10 清队列 / F11 中断（global-shortcut，可配置）。
- **Schema 驱动 UI**：插件 params_schema 自动生成滑块/下拉/文本域/开关/文件选择，
  支持 ui:group、unit、requires_model_reload、runtime_modifiable 注解；
  **禁止**插件向 WebView 注入脚本。
- **隐私**：全本地推理、参考音频仅本机、导出脱敏、网络权限默认关闭并高亮。

## 3. 真实性声明（三十二.「真实性」逐项）

- 无任何 Mock 冒充推理：AI 插件直接调用真实模型（CosyVoice3 生成 4.76s 音频的
  WAV 在 logs/smoke_ai_tts.wav；ASR/断句输出在 logs/smoke_ai.log）。
- Benchmark 数字全部来自当日实测（PERFORMANCE_REPORT），无写死。
- 未完成项见第 8 节，未隐藏。
- 30 分钟 soak 为真实运行 30.06 分钟（345 轮），日志完整。

## 4. 关键修复遗产（继承自 Python 阶段，桌面插件直接复用）

1. **ASR 增量文本丢失**：FunASR 流式每块返回增量文本，替换语义导致 final 丢字；
   重叠合并修复后真实音频 100% 逐字正确（logs/probe_asr2/3.txt 逐 codepoint 验证）。
2. **fast LLM 解码器因果 mask**：流式音频膨胀 9.16s→2.80s；
   与 eager 逐位一致（max_abs_diff=0）。
3. **框架开销**：LLM 端到端 4.9s→3.4s。

## 5. 测试与性能摘要

详见 docs/TEST_REPORT.md 与 docs/PERFORMANCE_REPORT.md：

- Rust 20/20 通过（含**宿主⇄真实 worker 生命周期**：崩溃强杀后宿主存活；
  **宿主命令层原生管线 E2E**：WAV 文件→+6dB 增益→录制，48000 样本数值验证）。
- SDK 回环：握手/配置/数据面/健康/优雅退出全链路 + 数值精确验证。
- AI 管线冒烟：真实 TTS 音频 + 正确断句（gRPC 插件路径）。
- 30 分钟 soak：0.29% 错误率、VRAM 零增长、无耗时漂移。
- **TTFA 5.2s 未达 0.8~1.5s 目标**（差距分析 + 优化路线在 PERFORMANCE_REPORT 第 2 节）。

## 6. 打包（已产出，dist-package/）

- NSIS 安装包：`Voice Studio_0.1.0_x64-setup.exe`（4.1MB，release exe 16.4MB，
  启动冒烟通过）
- Portable ZIP：`VoiceStudio-Portable.zip`（exe + plugins + sdk，5.7MB）
- 校验：`SHA256SUMS.txt`（安装包 C2D74366…E796 / Portable F6400144…C9DC）
- 大型模型/Python 依赖**不打入**安装包（bundle.resources 为空）；
  模型经官方源放置 models/，插件运行时使用本机 .venv 或独立 venv。

## 7. 复现

```powershell
.\scripts\setup.ps1        # 环境 + 构建 + 插件安装 + Smoke
.\scripts\run.ps1          # 启动桌面应用
.\scripts\test.ps1         # Rust 19 + SDK + AI 冒烟（-Soak 加 30 分钟）
.\scripts\diagnose.ps1
.\scripts\package.ps1      # 安装包 + Portable + SHA-256
```

## 8. 未完成项 / 人工验收项（不隐瞒）

### 8.1 需人工完成的验收

1. VB-CABLE 实机输出（本机未装 VB-CABLE；输出路径与检测逻辑已实现，
   GUI 有安装指引）。
2. 麦克风→扬声器听感（爆音/延迟需人耳；underrun 计数器已接入 GUI）。
3. Discord/QQ/VRChat 中 CABLE Output 作为麦克风的端到端联调。
4. GUI 点击级 E2E（自动化框架未引入）。

### 8.2 已知缺口

1. 桌面 GUI 层 30 分钟 soak（引擎层已有；GUI 层稳定性依赖人工或后续自动化）。
2. 故障注入测试（设备拔插/OOM/断流）为保护逻辑实现，无自动化注入用例。
3. 隔离 venv 的"环境修复"GUI 命令预留未实现完整 CLI（tone_gen 声明 isolated，
   手动放置 venv 可用）。
4. 插件商店/远程索引：按规格仅预留接口，未实现服务器。
5. TTFA 延迟目标未达成（算力瓶颈，见性能报告）。
6. RVC/Seed-VC 模型级变声为文档化适配位（未伪造实现）；
  当前 VC 插件为真实 WSOLA DSP 算法。
7. wetext 前端 403 降级、Fish Speech 不可实时——继承自 Python 阶段的已知限制。

## 9. 结论

原始规格的**桌面宿主、插件系统、管线引擎、可视化编辑器、真实 AI 插件、
SDK、预置管线、热键、持久化、崩溃恢复、打包**全部实现并有测试证据；
**延迟目标**与**三项人工验收**（虚拟设备联调/听感/游戏内联调）未闭环，
均在第 8 节如实列明。
