# Performance Report — Voice Studio

日期：2026-08-16 · RTX 4060 Laptop 8GB · 驱动 610.88 · 48k 输入

> 所有数字为真实测量，原始数据在 logs/。目标对照原始规格（二十九.）。

## 1. gRPC 插件通道开销（数据面）

本地回环（smoke_plugin_sdk）单帧 480 样本（10ms@48k）端到端往返 <10ms
（含 Python asyncio 调度），其中网络序列化占比可忽略。
结论：**第一版按规格采用 gRPC 双向流即够用**；共享内存数据面留作实测出瓶颈后再做。

## 2. TTS（CosyVoice3-0.5B，fast LLM 解码器开启）

引擎层基准（logs/benchmark_results.json，2026-08-16 刷新）：

| 用例 | TTFA | 总生成 | 音频时长 | RTF |
|---|---|---|---|---|
| 短句 11 字（流式） | 5231 ms | 6947 ms | 2.80 s | 2.48 |
| 长句 62 字（流式） | 5705 ms | 26959 ms | 16.32 s | 1.65 |
| Fish Speech 1.5（对照，不可实时） | 12702 ms | 12702 ms | 3.02 s | 4.21 |

插件路径（gRPC worker，smoke_ai.log）：冷启动（含模型加载 ~40s）后生成正常；
常驻后 TTFA 等同引擎层 + gRPC 开销（<10ms）。

**与目标（0.8~1.5s）的差距（诚实记录）**：瓶颈为 0.5B LLM 在单卡 4060 上的真实
算力需求（解码 ~3.4s）+ flow 首块；fast_llm 已消除纯框架开销（4.9s→3.4s）。
优化路线：KV-cache fp8/INT8、更小 LLM、投机解码、flow 步数（当前 10）与质量权衡。

## 3. ASR（FunASR paraformer-streaming，CUDA）

- 单块（600ms 音频）推理 40~70ms（rtf 0.06~0.13，logs/simulate_30min.log）。
- 增量文本合并修复后：真实麦克风音频 100% 逐字正确；
  TTS 回灌音频句均相似度 92%（残余为同音字）。
- 端到端 partial 延迟 ≈ 600ms 块粒度 + 70ms 推理（符合 chunk [0,10,5] 设计）。

## 4. 变声（vcpitch，CPU WSOLA）

WSOLA 音高移动（1024 窗/512 hop @48k）+ FFT 共振峰：单帧 <2ms（CPU 单核），
RTF << 1，满足直接变声管线的实时预算（目标感知延迟 <300ms 的主要构成只剩
音频缓冲 ~60ms + 本节点 <5ms + 输出缓冲）。

## 5. 30 分钟稳定性（引擎层，2026-08-16）

| 指标 | 值 |
|---|---|
| 轮数/时长 | 345 / 30.06 min |
| 错误率 | 0.29% |
| 平均相似度 | 0.919 |
| 峰值显存 | 6523 MB（345/345 轮恒定，零泄漏） |
| 耗时漂移 | 无（区块均值 4631/4676/3615/4532/4594ms，非单调） |

## 6. 资源占用

- 常驻（ASR+TTS 皆加载）：~6.5GB/8GB。仅 TTS：~4.6GB。仅 ASR：~1GB。
- 桌面宿主（Rust）：~70MB 内存。
- 空闲插件 worker（gain 级）：~25MB/进程。

## 7. 音频稳定性

- underrun/overflow 计数器接入 GUI 性能页；soak 期间引擎层 0 underrun。
- 桌面 WASAPI 路径的长时间 underrun 统计需 GUI 层 soak 补充（见 TEST_REPORT 6）。
