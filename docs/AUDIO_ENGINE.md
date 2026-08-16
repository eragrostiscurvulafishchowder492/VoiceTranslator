# Audio Engine（crates/audio-engine + 宿主设备桥）

## 设备

- 后端：cpal（Windows = WASAPI Shared）。枚举输入/输出、默认设备、采样率。
- 设备标识用**稳定键** `in|设备名` / `out|设备名`，绝不持久化索引
  （Windows 热插拔后索引会漂移）。
- 热插拔：宿主 5s 轮询 `diff_devices` → GUI 事件；运行中的管线依赖的设备消失 →
  自动停止管线并提示（应用不崩溃）。
- VB-CABLE：检测名称含 `CABLE Input` 的输出即视为虚拟设备；未安装不阻塞其他功能，
  GUI 提供安装指引，**绝不自动安装驱动**。

## 内部格式

- 全链路统一 **48kHz mono f32le**；模型需要的采样率由 Resampler 节点/插件内部转换
  （rubato FFT 异步重采样，高质量）。
- 采集侧：任意设备采样率/声道 → mono → 前置 DSP（HPF 80Hz → 噪声门 → 限幅 → 增益）
  → RingBuffer。
- 播放侧：48k mono → 设备原生率（含 44.1k 等）→ 多声道复制。
  chunk 间 5ms crossfade 防 click。

## RingBuffer（无锁 SPSC）

`ringbuffer.rs`：f32 以位模式存 `AtomicU32` 环；head/tail 原子索引。
容量 65536 帧（≈1.37s@48k）。溢出丢整块并计数；下溢计数（underrun）。
GUI 性能页实时展示两个计数。

## 回调纪律（十五.）

音频回调（采集/播放）内**禁止**：分配大内存、磁盘/网络/日志 IO、推理、长锁。
本实现中回调只做：mono 混合、4 个轻量 DSP biquad/包络、原子 ring 读写。

## DSP

| 模块 | 实现 |
|---|---|
| HighPass | RBJ 双二阶，80Hz 默认 |
| NoiseGate | RMS 包络，attack 3ms / release 60ms / hold 可配 |
| Limiter | 峰值包络增益 + tanh 软削顶，-1dB 天花板 |
| Gain | 线性增益 |
| Resampler | rubato FftFixedIn，流式（StreamResampler）与离线（resample_once） |
| Crossfade | 5ms 等功率交叉淡化 |

## 与管线核心的边界

`pipeline-core::native::DeviceBridge` 是唯一接触点：

```rust
pub struct DeviceBridge {
    pub pull_input: Box<dyn Fn(&mut [f32]) -> usize>,  // 拉取 48k mono
    pub submit_output: Box<dyn Fn(&[f32])>,            // 提交 48k mono
    pub ptt_active: Box<dyn Fn() -> bool>,
}
```

宿主（Tauri app）在 start_pipeline 时打开设备并注入闭包；
engine 不依赖具体音频实现，便于测试与替换后端（未来 WASAPI Exclusive / ASIO）。

## WAV IO

`wav.rs`（hound）：读任意 WAV → 48k mono f32；写 f32 WAV（录制节点/Voice Lab 输出）。
