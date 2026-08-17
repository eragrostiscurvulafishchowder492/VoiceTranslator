//! 麦克风采集：cpal 流 + 前置 DSP + RingBuffer，任何采样率/声道自动转 48k mono f32。
use crate::dsp::PreChain;
use crate::ringbuffer::RingBuffer;
use cpal::traits::{DeviceTrait, StreamTrait};
use cpal::{InputCallbackInfo, SampleFormat, Stream};
use std::sync::Arc;

pub struct AudioCapture {
    pub ring: Arc<RingBuffer>,
    stream: Option<Stream>,
    pub device_key: String,
    pub sample_rate: u32,
    pub channels: u16,
}

// SAFETY: cpal Stream 内部含平台句柄（Windows 上非 Send）。
// 本类型只在创建线程构造、在其他线程最多调用 pause/stop（cpal 内部加锁），
// 音频数据交换全部经由无锁 RingBuffer，不存在跨线程访问流本身的竞争。
unsafe impl Send for AudioCapture {}

impl AudioCapture {
    /// device_key: "in|设备名"。block_ms 建议回调粒度。
    pub fn start(device_key: &str, gain_db: f32, gate_db: f32) -> anyhow::Result<Self> {
        let dev = crate::devices::find_by_key(device_key)
            .ok_or_else(|| anyhow::anyhow!("输入设备不存在: {device_key}"))?;
        let cfg = dev.default_input_config()?;
        let rate = cfg.sample_rate().0;
        let ch = cfg.channels().max(1);
        let ring = Arc::new(RingBuffer::new(1 << 16)); // 65536 帧 ≈ 1.37s@48k
        let ring_w = ring.clone();
        let mut chain = PreChain::new(rate as f32, 80.0, gate_db, gain_db);
        let err_cb = |e| log::error!("capture stream error: {e}");

        let stream = match cfg.sample_format() {
            SampleFormat::F32 => dev.build_input_stream(
                &cfg.into(),
                move |data: &[f32], _: &InputCallbackInfo| on_data(data, ch, &mut chain, &ring_w),
                err_cb,
                None,
            )?,
            SampleFormat::I16 => dev.build_input_stream(
                &cfg.into(),
                move |data: &[i16], _: &InputCallbackInfo| {
                    let f: Vec<f32> = data.iter().map(|s| *s as f32 / 32768.0).collect();
                    on_data(&f, ch, &mut chain, &ring_w)
                },
                err_cb,
                None,
            )?,
            other => anyhow::bail!("不支持的采样格式: {other:?}"),
        };
        stream.play()?;
        Ok(Self {
            ring,
            stream: Some(stream),
            device_key: device_key.into(),
            sample_rate: rate,
            channels: ch,
        })
    }

    pub fn overflow_count(&self) -> u64 {
        self.ring.stats().0
    }
    pub fn stop(&mut self) {
        if let Some(s) = self.stream.take() {
            s.pause().ok();
        }
    }
}

fn on_data(data: &[f32], ch: u16, chain: &mut PreChain, ring: &RingBuffer) {
    // 多声道 → mono（平均）
    let mono: Vec<f32> = if ch == 1 {
        data.to_vec()
    } else {
        data.chunks(ch as usize)
            .map(|c| c.iter().sum::<f32>() / c.len() as f32)
            .collect()
    };
    let processed: Vec<f32> = mono.iter().map(|&s| chain.process(s)).collect();
    ring.push(&processed);
}
