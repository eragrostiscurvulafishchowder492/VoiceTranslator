//! WAV 读写（hound），统一转 48k mono f32 读入。
pub fn read_mono_48k(path: &std::path::Path) -> anyhow::Result<(Vec<f32>, u32, u32)> {
    let mut r = hound::WavReader::open(path)?;
    let spec = r.spec();
    let sr = spec.sample_rate;
    let ch = spec.channels as u16;
    let raw: Vec<f32> = match spec.sample_format {
        hound::SampleFormat::Float => r.samples::<f32>().map(|s| s.unwrap_or(0.0)).collect(),
        hound::SampleFormat::Int => {
            let max = (1i64 << (spec.bits_per_sample - 1)) as f32;
            r.samples::<i32>().map(|s| s.map(|v| v as f32 / max).unwrap_or(0.0)).collect()
        }
    };
    let mono: Vec<f32> = if ch == 1 { raw } else {
        raw.chunks(ch as usize).map(|c| c.iter().sum::<f32>() / c.len() as f32).collect()
    };
    let out = crate::resampler::resample_once(&mono, sr, 48_000)?;
    Ok((out, 48_000, 1))
}

pub fn write_wav(path: &std::path::Path, samples: &[f32], rate: u32) -> anyhow::Result<()> {
    let spec = hound::WavSpec {
        channels: 1, sample_rate: rate, bits_per_sample: 32, sample_format: hound::SampleFormat::Float,
    };
    let mut w = hound::WavWriter::create(path, spec)?;
    for &s in samples { w.write_sample(s.clamp(-1.0, 1.0))?; }
    w.finalize()?;
    Ok(())
}
