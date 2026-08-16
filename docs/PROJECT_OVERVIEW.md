# Voice Studio — 项目架构与现状总览

> 更新：2026-08-16 · 提交 `98146f1` · 219 个文件入库 · 约 14,000 行代码
> 一句话：**本地优先、可插拔的 Windows 实时语音工作台**——麦克风进、变声后的目标音色出（VB-CABLE 虚拟麦克风），ASR/TTS/DSP 全部以独立进程插件的形式自由组合。

---

## 1. 项目定位

| 维度 | 内容 |
|---|---|
| 核心用例 | 中文语音 → 流式识别 → 智能断句 → 零样本 TTS（用户自备参考音色）→ 虚拟麦克风输出 |
| 次要用例 | 直接实时变声（DSP）、ASR 实时字幕、双路输出、翻译模板 |
| 平台 | Windows 11 优先（RTX 4060 8GB 实测）；架构预留 Linux/macOS/CPU/DML |
| 隐私 | 全本地推理，不上传音频/文本；不附带任何角色语音素材 |
| 许可 | Apache-2.0（本仓库代码）；模型与第三方依赖见 THIRD_PARTY_NOTICES.md |

## 2. 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Voice Studio 桌面应用                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  WebView2 (Vue 3 GUI，十页导航 + SVG 节点编辑器 + Schema 表单) │  │
│  └──────────────────────────┬────────────────────────────────┘  │
│                             │ Tauri IPC（33 个命令）               │
│  ┌──────────────────────────┴────────────────────────────────┐  │
│  │                 Rust 宿主（8 个 crate，5,215 行）             │  │
│  │  audio-engine ── 设备/采集/播放/无锁Ring/重采样/DSP           │  │
│  │  pipeline-core ─ 类型化端口/图校验/背压调度/内置节点×15        │  │
│  │  plugin-host ─── manifest/ZIP安装/worker进程/心跳/崩溃重启     │  │
│  │  plugin-protocol─ gRPC v1（protox 生成，免 protoc）           │  │
│  │  persistence ─── SQLite WAL + 版本化迁移/last_known_good      │  │
│  │  resource-manager─ GPU/显存采集 + 启动预检                     │  │
│  │  diagnostics ─── 日志环/崩溃标记→安全模式                      │  │
│  │  common ──────── 路径/ID/时间/错误                             │  │
│  └──────┬─────────────────────────────────────────┬────────────┘  │
└─────────│ WASAPI                                    │ gRPC 双向流   │
          ▼                                           ▼ (127.0.0.1)
   麦克风/扬声器/VB-CABLE                    独立 Python Worker 进程 ×N
                                            ├ funasr   (流式ASR+VAD, GPU)
                                            ├ cosyvoice(零样本TTS, GPU)
                                            ├ textkit  (断句/标准化/替换)
                                            ├ vcpitch  (实时变声, CPU DSP)
                                            └ examples ×5 (gain/文本替换/
                                               测试音/空输出/外部命令)
                                            ——Worker 复用 app/ 的
                                            Python 引擎（4,461 行，含
                                            fast-LLM 解码器与增量合并修复）
```

**关键设计**（对应原始规格的核心原则）：

- **主程序与模型解耦**：AI 模型全部跑在插件 worker 独立进程里，崩溃不拖垮 GUI（有测试证据）；
- **统一版本化协议**：Protobuf `voice_plugin_v1`（10 类端口消息），主版本不匹配拒绝运行；
- **实时纪律**：音频回调零 IO/零锁（无锁 SPSC Ring），GUI 零推理，推理在线程池/独立进程；
- **Schema 驱动 UI**：插件参数由 JSON Schema 自动生成控件，新增插件零前端改动；插件被禁止向 WebView 注入脚本。

## 3. 目录结构

```
VoiceTranslator/
├─ apps/desktop/            # Tauri 2 + Vue 3 桌面应用（src-tauri 宿主 + src 前端）
├─ crates/                  # Rust 宿主 8 crate（含单元/集成测试 + 诊断 examples）
├─ proto/voice_plugin_v1.proto
├─ sdk/python/voice_plugin_sdk/   # Python Plugin SDK（gRPC server + VoicePlugin 基类）
├─ plugins/
│  ├─ examples/ ×5          # 示例插件（SDK 教学用）
│  └─ ai/ ×4                # 真实 AI 插件（funasr/cosyvoice/textkit/vc_pitch）
├─ app/                     # 既有 Python 语音引擎（被 AI 插件复用：ASR/TTS/断句/标准化）
├─ tests/                   # SDK 回环/AI 冒烟/30min soak/历史调参 probe
├─ scripts/ ×9              # setup/run/diagnose/test/package/create_plugin/make_sha256/…
├─ docs/ ×13                # 全套文档（本文件 + 12 份专题）
├─ .venv / models/ / deps/  # 本地运行环境与模型（gitignore，不入库）
├─ app-data/                # 运行数据：plugins/database/references/logs/…（gitignore）
└─ dist-package/            # 打包产物 + SHA256SUMS（gitignore）
```

代码构成：Rust 5,215 行 · Python 引擎+SDK 4,461 行 · 测试/脚本 1,804 行 · 插件 1,018 行 · Vue/TS 1,599 行 · Proto 174 行 · 文档 1,261 行。

## 4. 端到端数据流（核心用例）

```
麦克风(48k f32, HPF→Gate→Limiter→Gain 前置 DSP)
 → [audio.resampler 48k→16k]（EOS 标记透传）
 → funasr.streaming_asr（600ms 块流式推理；增量重叠合并防丢字）
 → text.partial ×N（600ms 级增长）
 → textkit.segmenter（4 轮稳定前缀 + 标点/26字/1.5s 超时强制提交）
 → textkit.normalizer（数字/日期/游戏模式）
 → textkit.to_tts（→ tts.request，QUEUE/INTERRUPT 策略）
 → cosyvoice.zero_shot_tts（fast-LLM 解码 + flow 10 步，24k 流式 chunk）
 → audio.limiter → CABLE Input（虚拟麦克风）[可选 monitor 耳机]
```

每条边：有界通道 + 背压策略（BLOCK/DROP_OLDEST/DROP_NEWEST/LATEST_ONLY/FAIL_PIPELINE），
GUI 性能页实时显示各边队列深度/发送/丢弃计数。

## 5. 插件系统生命周期

```
discover(扫描 plugin.toml) → validate(权限白名单/版本) → install(ZIP,
 zip-slip 防护+checksums) → prepare_env(main 共享 venv 或 isolated 独立 venv,
 自动装 SDK 依赖) → start_worker(独立进程+gRPC) → handshake(协议协商,
 节点类型→DB 缓存) → Configure(每节点实例参数+路由键) → Process(双向流)
 → Health(5s 心跳, 3 败杀) → 崩溃→指数退避重启(1/2/4/8/16s,
 10min 内 5 次封顶) → Shutdown(优雅退出)
```

## 6. 验证与质量现状（全部真实数据，可复现）

### 6.1 测试矩阵（全绿）

| 层 | 内容 | 结果 |
|---|---|---|
| Rust 单元+集成 ×21 | 图校验/循环检测/版本协商/zip-slip 拒绝/退避上限/DB 迁移/**宿主⇄worker 生命周期（强杀存活）**/命令层 E2E | 21/21 |
| SDK 回环 | 握手→Configure→数据面(+6dB 数值精确)→健康→优雅退出 | PASS |
| AI 管线冒烟 | textkit 断句 + CosyVoice 真实合成（gRPC 全链路） | PASS |
| **手测自动化 ×4**（`--example manual_test`，生产同路径） | T1 变声（升调+时长 1.00）/ T2 ASR（相似度 0.91）/ **T3 完整核心管线（真实语音→…→3.56s WAV）**/ T4 监听（underrun=0） | 4/4 |
| 30 分钟 soak（引擎层） | 345 轮，错误率 0.29%，VRAM 6,523MB×345 轮零增长，无耗时漂移 | PASS |
| 实机麦克风 | HECATE G2，131,712 帧，检测到环境声，溢出=0 | PASS |
| GUI 视觉 | `--page` 深链接十页截图，节点编辑器预置管线 9 节点+连线 | PASS |

### 6.2 开发过程中发现并修复的关键 bug（均有测试回归覆盖）

| 阶段 | bug | 影响 |
|---|---|---|
| Python 期 | FunASR 增量文本替换语义 | final 只剩最后一小块 |
| Python 期 | fast-LLM 因果 mask 缺失 | 流式音频膨胀 9.16s→2.80s |
| 桌面期 | start_pipeline 插件误判（`.` vs `/`） | **任何内置节点管线启动即失败** |
| 桌面期 | resampler 吞 EOS | ASR 永远无 final |
| 桌面期 | vc_pitch 缺重采样 | 变声输出缩短 25% |
| 桌面期 | Configure 不下发 | 插件节点参数/路由全空 |
| 桌面期 | ps1 无 BOM | run.bat 双击无反应 |

### 6.3 性能实测（RTX 4060 Laptop 8GB）

| 指标 | 实测 | 目标 | 判定 |
|---|---|---|---|
| TTS TTFA（短句） | 5,231 ms | 0.8~1.5 s | **未达**（0.5B LLM 算力瓶颈，优化路线已列） |
| ASR 单块推理 | 40~70 ms (rtf 0.06~0.13) | 实时 | 达成 |
| 变声单帧（CPU） | <2 ms | 实时 | 达成 |
| gRPC 单帧往返 | <10 ms | 低开销 | 达成 |
| 常驻显存 | ASR+TTS 6.5GB / 仅 TTS 4.6GB | 8GB 内 | 达成 |
| 30min 稳定性 | 显存零增长/无漂移 | 无泄漏 | 达成 |

## 7. 交付产物

| 产物 | 位置 |
|---|---|
| NSIS 安装包（4.2MB，不含模型） | `dist-package/Voice Studio_0.1.0_x64-setup.exe`（SHA `D43253D9…`） |
| Portable ZIP（exe+插件+SDK） | `dist-package/VoiceStudio-Portable.zip`（SHA `446F6733…`） |
| 源码仓库 | 4 个提交，219 文件，`git log` 干净 |
| 文档 ×13 | 架构/协议/插件开发/manifest/音频/安全/排障/测试/性能/依赖政策/最终报告/本总览 |
| 脚本 ×9 | 一键环境/启动/诊断/测试/打包/插件模板/截图/SHA |

## 8. 已知限制与待办（不隐瞒）

**需人工完成**：听感验收（T3 产物 `app-data/cache/manual_full_out.wav` 可直接试听）；VB-CABLE 安装后的游戏内联调（本机未装）。

**技术缺口**：TTS TTFA 未达标（算力瓶颈）；GUI 层 30min soak 未做（引擎层已有）；故障注入（拔插/OOM/断流）无自动化用例；远程插件索引仅预留接口；RVC/Seed-VC 为文档化适配位（当前 VC 为真实 WSOLA DSP，未伪造模型实现）。

**环境已知项**：wetext 前端下载 403 时自动降级；Fish Speech RTF 4.2 不可实时（保留对照）。

## 9. 快速上手

```powershell
.\scripts\setup.ps1      # 环境+构建+插件安装+冒烟（CosyVoice 仓库自动 clone）
.\scripts\run.ps1        # 启动桌面应用（release；-Dev 开发模式）
.\scripts\test.ps1       # 全部测试（-Soak 加 30 分钟长稳）
cargo run -p voice-studio-desktop --example manual_test   # 手测自动化 4 项
.\scripts\create_plugin.ps1 my-plugin -Type tts           # 生成插件模板
```

首次使用核心用例：声音档案页导入参考 WAV（5~15s 清晰语音）→ 管线工作室加载预置
「中文语音转目标音色」→ ▶ 启动 → 说话。输出到虚拟麦克风需安装 VB-CABLE
（应用绝不自动装驱动，检测不到时自动回退扬声器并给出指引）。
