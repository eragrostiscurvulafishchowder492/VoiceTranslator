# Voice Studio — Architecture

可视化、可插拔、可组合的本地实时语音处理平台。

## 1. 总体结构

```
┌────────────────────────────────────────────────────────────┐
│ Tauri 2 宿主 (Rust)                                        │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐ ┌──────────────┐  │
│  │audio-eng.│ │pipeline-  │ │plugin-   │ │persistence   │  │
│  │(cpal/WSA)│ │core(图/调度│ │host(生命 │ │(SQLite/迁移) │  │
│  │ring/DSP/ │ │ /背压)     │ │ 周期/重启)│ │              │  │
│  │resample  │ └───────────┘ └────┬─────┘ └──────────────┘  │
│  └──────────┘        ┌───────────┴──────────┐              │
│  resource-manager    │ plugin-protocol(gRPC) │  diagnostics │
│  (GPU/CPU/显存预检)   └───────────┬──────────┘              │
└──────────────────────────────────┼─────────────────────────┘
                        gRPC 控制面 + 双向流数据面 (127.0.0.1)
        ┌───────────────┬───────────────┬────────────────┐
        │ Python Worker │ Python Worker │ Python Worker  │
        │ funasr ASR    │ cosyvoice TTS │ textkit / VC…  │
        │ (复用 app/ 引擎)│ (复用 app/)    │ (复用 app/)     │
        └───────────────┴───────────────┴────────────────┘
                     WebView2 (Vue 3 GUI)
```

## 2. Crate 边界（26. 目录规范）

| crate | 职责 | 禁止 |
|---|---|---|
| common | 路径/ID/时间/错误/日志 | 业务逻辑 |
| plugin-protocol | proto 生成代码 + 版本常量 | 任何逻辑 |
| audio-engine | 设备/采集/播放/ring/DSP/重采样/WAV | 推理、GUI |
| pipeline-core | 端口类型/图/校验/调度/背压/内置节点 | 直接依赖音频设备（经 DeviceBridge 注入） |
| plugin-host | manifest/发现/安装/worker/生命周期 | 音频处理 |
| resource-manager | GPU/CPU 采集、显存预检 | — |
| persistence | SQLite + 版本化迁移 | — |
| diagnostics | 日志环/崩溃标记 | — |
| desktop (bin) | Tauri 组装、IPC 命令、热键、事件 | 逻辑下沉到 crate |

## 3. 数据流（核心用例：中文语音转目标音色）

```
麦克风(48k) → [Resampler→16k] → funasr.streaming_asr → text.partial
  → textkit.segmenter(稳定前缀+断句) → textkit.normalizer → textkit.to_tts
  → tts.request → cosyvoice.zero_shot_tts(24k 流式) → audio.limiter
  → audio.virtual_output(CABLE Input) [+ 可选 monitor]
```

每条边：有界通道 + 背压策略（BLOCK/DROP_OLDEST/DROP_NEWEST/LATEST_ONLY/FAIL_PIPELINE）。
实时电平类用 LATEST_ONLY；ASR 音频默认 BLOCK；过时 partial 由下游自然替换；
TTS 请求超限即 FAIL_PIPELINE 触发保护停止。

## 4. 节点体系

- 统一端口类型（10 种，见 PROTOCOL.md）；连接前校验：端口存在、类型/采样率/声道兼容、
  循环检测（DFS）、必需参数、插件安装、显存预检。
- 内置节点（Rust，无依赖即可跑）：麦克风/扬声器/虚拟输出/WAV 输入/录制/增益/噪声门/
  限幅/高通/重采样/声道转换/PTT/文本输入/输出/指标。
- 插件节点：`<plugin_id>/<node_type>`（如 `org.voicestudio.funasr/funasr.streaming_asr`），
  握手后合并进注册表；参数面板由 params_schema 自动生成。

## 5. 线程/进程模型

- GUI：WebView（Vue），经 Tauri IPC 调命令；**绝不**执行推理/音频处理。
- 音频回调：cpal 线程，只做 DSP + ring 读写。
- 节点任务：每个节点一个 std::thread（源节点按节拍产出，处理节点阻塞等待）。
- 插件 worker：独立 OS 进程（gRPC server），心跳 5s，崩溃指数退避重启
  （1/2/4/8/16s，10 分钟 5 次封顶）。
- 宿主监控线程：设备热插拔（5s）、管线 watchdog。

## 6. 既有 Python 引擎（app/）的角色

`app/` 是本仓库早期完成并充分验证的 Python 语音链路（FunASR 引擎含增量重叠合并修复、
CosyVoice 引擎含 fast LLM 解码器、断句器、文本标准化），30 分钟 soak 345 轮验证。
Voice Studio 的 AI 插件**直接复用**这些引擎（worker 内 import），不重复实现。
这保证了桌面平台的推理质量与已验证的性能特性一致。

## 7. 持久化与恢复

- SQLite（WAL，版本化迁移 v1）：settings/pipelines/presets/voice_profiles/models/
  recent_events/benchmarks/session_state。
- last_known_good_pipeline：每次保存管线时更新。
- 崩溃标记：启动写入、正常退出清除；残留则首启弹安全模式（不自动加载插件/管线）。
- 设备拔出→自动停管线；OOM→节点错误状态+真实错误消息（不伪装恢复）。

## 8. 扩展点（未来）

- Rust/外部进程/http 插件 runtime（manifest.runtime 字段已预留）
- WASAPI Exclusive / ASIO 低延迟后端（audio-engine 边界已隔离）
- 共享内存数据面（协议版本化已预留，基准数据证明必要时才做）
- 真沙箱（Job Object/AppContainer）
- 远程插件索引/更新源（安装接口已按本地 ZIP + 目录两种来源设计）
