# Voice Studio — 最终报告（FINAL REPORT）

日期：2026-08-17
历史运行环境：Windows 11 · RTX 4060 Laptop 8GB · Rust 1.97.1 · Node 24 · Python 3.12.9

> F9 已通过当前本地源码门禁，精确命令、exit 与 PRE=POST 指纹见 `docs/TEST_REPORT.md`。
> 第 2–5 节中的 AI、麦克风、GUI 与 soak 数据仍是较早环境的历史日志；源码公开就绪和
> 二进制/模型发行必须分开判断。

---

## 1. 交付物总览

| 交付物 | 位置 | 状态 |
|---|---|---|
| Tauri 2 + Rust 宿主（8 crate） | `crates/` + `apps/desktop/src-tauri/` | F9 Rust metadata/fmt/clippy 通过；启动属历史证据 |
| Vue 3 GUI（十页导航 + SVG 节点编辑器 + Schema 参数面板） | `apps/desktop/src/` | F9 frozen install/typecheck/build 通过；GUI 运行属历史证据 |
| Protobuf + gRPC 插件协议 v1 | `proto/voice_plugin_v1.proto` | 历史 Rust/Python 双端生成与验证证据 |
| Python Plugin SDK | `sdk/python/voice_plugin_sdk/` | F9 SDK smoke 通过；较深 E2E 属历史证据 |
| 示例插件 ×5 | `plugins/examples/` | 历史全部加载验证证据 |
| 真实 AI 插件 ×4（ASR/TTS/文本工具/变声） | `plugins/ai/` | 历史 ASR/TTS/文本工具真实推理证据；VC 为真实 DSP 算法 |
| 预置管线 ×6 | 宿主内置（首启写 DB） | 历史证据 |
| 自动化脚本 | `scripts/*.ps1` | 当前入口见 BUILDING/TEST_REPORT；不以精确文件总数作为门禁 |
| 当前源码测试 | `crates/*/tests`、`tests/` | F9：21 passed / 0 failed，desktop integration targets + SDK smoke 通过；AI 未运行 |
| 安装包 + Portable ZIP + SHA-256 | `dist-package/` | 历史快照，见第 6 节；本轮未打包/发布 |
| 文档 | `docs/` + README | 当前事实边界以 BUILDING/TEST_REPORT 为准 |

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

## 3. 历史真实性声明（三十二.「真实性」逐项）

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

- **当前 F9 source gate PASS**：Rust metadata/fmt/clippy；前端 frozen install、typecheck/build；
  官方非 AI Rust + desktop integration（21 passed / 0 failed，明确包含 `desktop_e2e_it.rs` 与
  `host_pipeline_it.rs`）；Python SDK smoke。AI 未运行。
- 以下为历史结果，不是 F9 current PASS：Rust 21/21 通过（含**宿主⇄真实 worker 生命周期**：崩溃强杀后宿主存活；
  **宿主命令层原生管线 E2E**：WAV→+6dB→录制数值验证；
  **桌面命令层插件 E2E**：自动启动/Configure/桥接/调度全链路）。
- **手测自动化 4/4 通过**（`--example manual_test`，生产同路径）：
  变声（升调+时长保持）/ ASR（相似度 0.91）/ **完整核心管线**（真实语音→
  ASR→断句→标准化→CosyVoice 合成→3.56s WAV）/ 原声监听（underrun=0）。
- 实机麦克风采集验证通过（零溢出）；GUI 十页截图视觉验证通过。
- 发布前修复的关键 bug（均由手测自动化暴露）：start_pipeline 插件误判
  （内置节点管线无法启动）、resampler 吞 EOS（ASR 无 final）、vc_pitch
  时长缩短 25%、边统计不刷新、Configure 未下发。
- SDK 回环：握手/配置/数据面/健康/优雅退出全链路 + 数值精确验证。
- AI 管线冒烟：真实 TTS 音频 + 正确断句（gRPC 插件路径）。
- 30 分钟 soak：0.29% 错误率、VRAM 零增长、无耗时漂移。
- **TTFA 5.2s 未达 0.8~1.5s 目标**（差距分析 + 优化路线在 PERFORMANCE_REPORT 第 2 节）。

## 6. 历史打包快照（非 current release evidence）

旧日志曾记录 `Voice Studio_0.1.0_x64-setup.exe`、`VoiceStudio-Portable.zip`、尺寸与截断
SHA，并做过启动冒烟。这些值仅属于当时的生成物；本轮没有确认文件仍存在、哈希仍匹配，
也没有执行正式打包或发布，不能作为当前安装包/Portable 可用性的证据。

当前 `package.ps1` 生成的 Portable ZIP 设计上只含 exe、`plugins/` 与 `sdk/`，不含
`.venv`、`models/` 或 Python dependencies。因此它是**宿主便携包，需另配 Python 环境、
已批准的 torch/torchaudio 组合和模型**，不是开箱即用 AI 发行版。源码公开就绪不会自动
批准二进制再分发；完整许可证/SBOM、模型与声音权利、发布身份仍是 owner gate。

## 7. 复现

```powershell
.\scripts\setup.ps1        # 环境 + 构建 + 插件安装 + Smoke
.\scripts\run.ps1          # 启动桌面应用
.\scripts\test.ps1 -SkipAi # 贡献者非 AI 基线，含完整 desktop tests
.\scripts\diagnose.ps1
.\scripts\package.ps1      # 安装包 + Portable + SHA-256
```

## 8. 非 F9 范围与人工验收项

### 8.1 历史人工/GUI证据（非 current release evidence）

- ✅ 实机麦克风采集验证（HECATE G2，131712 帧，零溢出）
- ✅ GUI 十页视觉验证（`--page` 深链接 + 截图）
- ✅ 桌面命令层 E2E（插件自动启动/Configure/桥接/引擎调度全链路）
- ✅ 隔离 venv 自动创建（venv + SDK 依赖 + requirements + 握手缓存）
- ✅ 热键即时重注册（设置保存即生效）
- ✅ 插件节点类型 DB 缓存（编辑器离线可见预置管线节点）

### 8.2 仍需人工完成的验收

1. VB-CABLE 实机输出（本机未装；输出路径/检测/指引已实现）。
2. 麦克风→扬声器**听感**（爆音/延迟需人耳；underrun 计数已入 GUI）。
3. Discord/QQ/VRChat 中 CABLE Output 端到端联调。

### 8.3 已知缺口

1. 桌面 GUI 层 30 分钟 soak（引擎层已有；GUI 层依赖人工或后续自动化）。
2. 故障注入测试（设备拔插/OOM/断流）为保护逻辑实现，无自动化注入用例。
3. 插件商店/远程索引：按规格仅预留接口。
4. TTFA 延迟目标未达成（算力瓶颈，见性能报告）。
5. RVC/Seed-VC 模型级变声为文档化适配位（未伪造实现）；
   当前 VC 插件为真实 WSOLA DSP 算法。
6. wetext 前端 403 降级、Fish Speech 不可实时——继承自 Python 阶段已知限制。

## 9. 结论

1. **GitHub 源码开源：READY。** 依据 F9 的技术门禁、文档与许可一致性本地证据，源码仓库
   公开于 <https://github.com/RedeatI/VoiceTranslator>，并已启用 GitHub private vulnerability
   reporting。当前没有 GitHub Release、公开二进制下载、已启用 CI 或稳定版本支持 SLA。
2. **二进制/模型发行：NOT READY。** F9 未运行当前 package、GUI、AI/GPU 或硬件验收；第三方、
   模型、声音及二进制再分发仍须 owner 明确批准。
