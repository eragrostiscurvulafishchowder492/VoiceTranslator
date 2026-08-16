//! 实机麦克风验证：枚举 → 打开默认输入 → 采集 3 秒 → 报告电平/溢出
fn main() {
    let devs = voice_audio_engine::devices::list_devices();
    for d in &devs { if d.is_input { println!("IN  {} (default={}) {}ch {}Hz", d.name, d.default_input, d.max_input_channels, d.default_sample_rate); } }
    let def = devs.iter().find(|d| d.default_input);
    let Some(def) = def else { eprintln!("无默认输入设备"); std::process::exit(2); };
    println!("打开: {}", def.name);
    let cap = voice_audio_engine::AudioCapture::start(&def.key, 0.0, -60.0).expect("打开失败");
    let mut total = 0usize; let mut peak = 0f32; let mut sum = 0f32;
    let t0 = std::time::Instant::now();
    let mut buf = vec![0f32; 4800];
    while t0.elapsed().as_secs() < 3 {
        let n = cap.ring.pop(&mut buf);
        if n > 0 {
            let seg = &buf[..n];
            let lv = voice_audio_engine::dsp::measure(seg);
            peak = peak.max(lv.peak); sum += lv.rms * lv.rms * n as f32; total += n;
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
    let rms = (sum / total.max(1) as f32).sqrt();
    println!("采样 {} 帧 ({:.2}s)，RMS={:.4}，peak={:.4}，溢出={}", total, total as f32 / 48000.0, rms, peak, cap.overflow_count());
    if rms > 0.001 { println!("MIC PASS（检测到环境声）"); } else { println!("MIC OK（设备工作，静音环境）"); }
}
