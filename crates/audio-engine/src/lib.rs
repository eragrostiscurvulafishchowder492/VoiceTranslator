//! 音频引擎：设备枚举、采集、播放、RingBuffer、重采样、基础 DSP。
//! 音频回调内禁止：分配大内存、锁等待、日志、推理、IO。
pub mod capture;
pub mod devices;
pub mod dsp;
pub mod output;
pub mod resampler;
pub mod ringbuffer;
pub mod wav;

pub const INTERNAL_RATE: u32 = 48_000;
pub const ASR_RATE: u32 = 16_000;

pub use capture::AudioCapture;
pub use output::PlaybackWorker;
pub use ringbuffer::RingBuffer;
