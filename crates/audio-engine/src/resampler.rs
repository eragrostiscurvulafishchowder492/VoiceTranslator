//! 高质量异步重采样（rubato，线性/采样率任意）。
use rubato::{FftFixedIn, Resampler};

pub struct StreamResampler {
    inner: FftFixedIn<f32>,
    in_buf: Vec<Vec<f32>>,
    /// 输入到输出比率（输出帧数/输入帧数），不足一帧的余量累积
    in_needed: usize,
}

impl StreamResampler {
    /// 48k→16k: chunk 480→160；16k→48k: 160→480。
    pub fn new(from: u32, to: u32, chunk_in: usize) -> anyhow::Result<Self> {
        let inner = FftFixedIn::<f32>::new(from as usize, to as usize, chunk_in, 2, 1)?;
        let in_needed = inner.input_frames_max();
        Ok(Self {
            inner,
            in_buf: vec![Vec::with_capacity(in_needed)],
            in_needed,
        })
    }

    /// 送入任意长度输入，返回已就绪的输出（可能为空）。
    pub fn process(&mut self, input: &[f32]) -> anyhow::Result<Vec<f32>> {
        self.in_buf[0].extend_from_slice(input);
        let mut out = Vec::new();
        while self.in_buf[0].len() >= self.in_needed {
            let chunk: Vec<f32> = self.in_buf[0]
                .drain(..self.inner.input_frames_next())
                .collect();
            self.in_buf[0].shrink_to_fit();
            self.in_buf[0].reserve(self.in_needed);
            let processed = self.inner.process(&[chunk], None)?;
            out.extend_from_slice(&processed[0]);
        }
        Ok(out)
    }

    /// 冲刷尾部（补零到整块）。
    pub fn flush(&mut self) -> anyhow::Result<Vec<f32>> {
        let pad = self.in_needed - self.in_buf[0].len();
        if pad > 0 && !self.in_buf[0].is_empty() {
            self.in_buf[0].extend(std::iter::repeat_n(0.0, pad));
        }
        let mut out = Vec::new();
        while self.in_buf[0].len() >= self.in_needed {
            let chunk: Vec<f32> = self.in_buf[0].drain(..self.in_needed).collect();
            let processed = self.inner.process(&[chunk], None)?;
            out.extend_from_slice(&processed[0]);
        }
        Ok(out)
    }
}

/// 离线重采样（WAV 文件、参考音频）。
pub fn resample_once(input: &[f32], from: u32, to: u32) -> anyhow::Result<Vec<f32>> {
    if from == to {
        return Ok(input.to_vec());
    }
    let chunk = (from as usize / 50).max(64); // 20ms
    let mut rs = StreamResampler::new(from, to, chunk)?;
    let mut out = rs.process(input)?;
    out.extend(rs.flush()?);
    Ok(out)
}
