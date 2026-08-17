//! 播放：主输出（虚拟设备/扬声器）+ 可选监听 fan-out。48k mono f32 内部格式，
//! 自动重采样到设备原生率。带 underrun 统计与紧急静音。
use crate::ringbuffer::RingBuffer;
use cpal::traits::{DeviceTrait, StreamTrait};
use cpal::{OutputCallbackInfo, SampleFormat, Stream};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;

pub struct PlaybackWorker {
    pub ring: Arc<RingBuffer>,
    monitor_ring: Option<Arc<RingBuffer>>,
    stream: Option<Stream>,
    monitor_stream: Option<Stream>,
    muted: Arc<AtomicBool>,
    underruns: Arc<AtomicU64>,
    pub device_key: String,
    pub monitor_key: String,
    cross: Vec<f32>,
}

// SAFETY: 同 AudioCapture —— 数据经 RingBuffer 交换，流句柄只在 stop 时 pause。
unsafe impl Send for PlaybackWorker {}

impl PlaybackWorker {
    pub fn start(main_key: &str, monitor_key: Option<&str>, gain_db: f32) -> anyhow::Result<Self> {
        let muted = Arc::new(AtomicBool::new(false));
        let underruns = Arc::new(AtomicU64::new(0));
        let (stream, ring) =
            open_output(main_key, muted.clone(), underruns.clone(), gain_db, true)?;
        let (monitor_stream, monitor_ring) = match monitor_key {
            Some(k) => {
                let (s, r) =
                    open_output(k, muted.clone(), underruns.clone(), gain_db - 6.0, false)?;
                (Some(s), Some(r))
            }
            None => (None, None),
        };
        Ok(Self {
            ring,
            monitor_ring,
            stream: Some(stream),
            monitor_stream,
            muted,
            underruns,
            device_key: main_key.into(),
            monitor_key: monitor_key.unwrap_or("").into(),
            cross: Vec::new(),
        })
    }

    /// 送入 48k mono f32（已完成重采样/音量处理的）。
    pub fn submit(&mut self, chunk: &[f32]) {
        crate::dsp::crossfade_append(&mut self.cross, chunk, 240); // 5ms @48k
        let take = self.cross.len().min(16384);
        let block: Vec<f32> = self.cross.drain(..take).collect();
        self.ring.push(&block);
        if let Some(mr) = &self.monitor_ring {
            mr.push(&block);
        }
    }

    pub fn set_muted(&self, m: bool) {
        self.muted.store(m, Ordering::Relaxed);
    }
    pub fn is_muted(&self) -> bool {
        self.muted.load(Ordering::Relaxed)
    }
    pub fn underrun_count(&self) -> u64 {
        self.underruns.load(Ordering::Relaxed)
    }

    pub fn stop(&mut self) {
        if let Some(s) = self.stream.take() {
            s.pause().ok();
        }
        if let Some(s) = self.monitor_stream.take() {
            s.pause().ok();
        }
    }
}

fn open_output(
    device_key: &str,
    muted: Arc<AtomicBool>,
    underruns: Arc<AtomicU64>,
    gain_db: f32,
    is_main: bool,
) -> anyhow::Result<(Stream, Arc<RingBuffer>)> {
    let dev = crate::devices::find_by_key(device_key)
        .ok_or_else(|| anyhow::anyhow!("输出设备不存在: {device_key}"))?;
    let cfg = dev.default_output_config()?;
    let rate = cfg.sample_rate().0;
    let ch = cfg.channels().max(1);
    let ring = Arc::new(RingBuffer::new(1 << 16));
    let ring_r = ring.clone();
    let gain = 10f32.powf(gain_db / 20.0);
    let err_cb = move |e| {
        log::error!(
            "output stream error ({}): {e}",
            if is_main { "main" } else { "monitor" }
        )
    };
    // 内部 48k → 设备率（共享模式常见 48k；44.1k 等由 rubato 转换）
    let mut rs = crate::resampler::StreamResampler::new(48_000, rate, 480)?;
    let mut leftover: Vec<f32> = Vec::new();
    let mut need = (rate as usize / 100).max(64); // 每回调需求的近似帧数

    let stream = match cfg.sample_format() {
        SampleFormat::F32 => dev.build_output_stream(
            &cfg.into(),
            move |data: &mut [f32], _: &OutputCallbackInfo| {
                render(
                    data,
                    ch,
                    &ring_r,
                    &muted,
                    gain,
                    &mut rs,
                    &mut leftover,
                    &mut need,
                    &underruns,
                )
            },
            err_cb,
            None,
        )?,
        SampleFormat::I16 => dev.build_output_stream(
            &cfg.into(),
            move |data: &mut [i16], _: &OutputCallbackInfo| {
                let n = data.len();
                let mut tmp = vec![0f32; n];
                render(
                    &mut tmp,
                    ch,
                    &ring_r,
                    &muted,
                    gain,
                    &mut rs,
                    &mut leftover,
                    &mut need,
                    &underruns,
                );
                for (o, s) in data.iter_mut().zip(tmp) {
                    *o = (s * 32767.0) as i16;
                }
            },
            err_cb,
            None,
        )?,
        other => anyhow::bail!("不支持的采样格式: {other:?}"),
    };
    stream.play()?;
    Ok((stream, ring))
}

#[allow(clippy::too_many_arguments)]
fn render(
    data: &mut [f32],
    ch: u16,
    ring: &RingBuffer,
    muted: &AtomicBool,
    gain: f32,
    rs: &mut crate::resampler::StreamResampler,
    leftover: &mut Vec<f32>,
    need: &mut usize,
    underruns: &AtomicU64,
) {
    let frames = data.len() / ch as usize;
    while leftover.len() < frames {
        let mut src = vec![0f32; 960];
        let got = ring.pop(&mut src);
        if got == 0 {
            if !leftover.is_empty() {
                break;
            }
            underruns.fetch_add(1, Ordering::Relaxed);
            break;
        }
        if let Ok(mut out) = rs.process(&src[..got]) {
            leftover.append(&mut out);
        }
    }
    let m = if muted.load(Ordering::Relaxed) {
        0.0
    } else {
        gain
    };
    for (i, frame) in data.chunks_mut(ch as usize).enumerate() {
        let s = leftover.get(i).copied().unwrap_or(0.0) * m;
        for o in frame {
            *o = s;
        }
    }
    let consumed = leftover.len().min(frames);
    leftover.drain(..consumed);
    *need = frames.max(64);
}
