//! 基础 DSP：HPF biquad、噪声门、限幅器、增益。全部无分配、可实时调用。

/// 单极点→双二阶高通（80Hz 默认）。
pub struct HighPass {
    b0: f32, b1: f32, b2: f32, a1: f32, a2: f32,
    x1: f32, x2: f32, y1: f32, y2: f32,
}

impl HighPass {
    pub fn new(rate: f32, freq: f32) -> Self {
        let w0 = std::f32::consts::TAU * freq / rate;
        let (s, c) = w0.sin_cos();
        let al = s / (2.0 * 0.707);
        let a0 = 1.0 + al;
        Self {
            b0: ((1.0 + c) / 2.0) / a0, b1: (-(1.0 + c)) / a0, b2: ((1.0 + c) / 2.0) / a0,
            a1: (-2.0 * c) / a0, a2: (1.0 - al) / a0,
            x1: 0.0, x2: 0.0, y1: 0.0, y2: 0.0,
        }
    }

    pub fn process(&mut self, x: f32) -> f32 {
        let y = self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2 - self.a1 * self.y1 - self.a2 * self.y2;
        self.x2 = self.x1; self.x1 = x; self.y2 = self.y1; self.y1 = y;
        y
    }
}

/// 噪声门（RMS 包络，attack/release 毫秒）。
pub struct NoiseGate {
    threshold: f32, attack: f32, release: f32,
    env: f32, gain: f32, opened: bool, hold_ms: f32, held_ms: f32,
}

impl NoiseGate {
    pub fn new(threshold_db: f32, attack_ms: f32, release_ms: f32, rate: f32, hold_ms: f32) -> Self {
        Self {
            threshold: 10f32.powf(threshold_db / 20.0),
            attack: (-1.0 / (attack_ms / 1000.0 * rate)).exp(),
            release: (-1.0 / (release_ms / 1000.0 * rate)).exp(),
            env: 0.0, gain: 1.0, opened: false, held_ms: 0.0, hold_ms,
        }
    }

    pub fn process(&mut self, x: f32) -> f32 {
        let abs = x.abs();
        self.env = if abs > self.env { abs } else { abs + self.release * (self.env - abs) };
        if self.env > self.threshold {
            self.opened = true;
            self.held_ms = 0.0;
        } else if self.opened {
            self.held_ms += 1000.0 / 48_000.0;
            if self.held_ms > self.hold_ms { self.opened = false; }
        }
        let target = if self.opened { 1.0 } else { 0.0 };
        let coef = if target > self.gain { self.attack } else { self.release };
        self.gain = target + (self.gain - target) * coef;
        x * self.gain
    }
}

/// 峰值限幅器（软饱和 + 包络跟随，无 lookahead）。
pub struct Limiter { ceiling: f32, env: f32, coef: f32 }

impl Limiter {
    pub fn new(ceiling_db: f32, release_ms: f32, rate: f32) -> Self {
        Self {
            ceiling: 10f32.powf(ceiling_db / 20.0),
            env: 1.0,
            coef: (-1.0 / (release_ms / 1000.0 * rate)).exp(),
        }
    }

    pub fn process(&mut self, x: f32) -> f32 {
        let peak = x.abs().max(1e-9);
        if peak * self.env > self.ceiling {
            self.env = self.ceiling / peak;
        } else {
            self.env = 1.0 + (self.env - 1.0) * self.coef;
            self.env = self.env.max(self.ceiling / 8.0);
        }
        let y = x * self.env;
        // 软削顶兜底
        y.clamp(-1.0, 1.0).tanh() * 1.002
    }
}

/// 前置链：HPF → Gate → Limiter → Gain（与 Python 侧 dsp 语义一致）。
pub struct PreChain {
    hp: HighPass, gate: NoiseGate, lim: Limiter, gain: f32,
}

impl PreChain {
    pub fn new(rate: f32, hpf_hz: f32, gate_db: f32, gain_db: f32) -> Self {
        Self {
            hp: HighPass::new(rate, hpf_hz),
            gate: NoiseGate::new(gate_db, 3.0, 60.0, rate, 80.0),
            lim: Limiter::new(-1.0, 50.0, rate),
            gain: 10f32.powf(gain_db / 20.0),
        }
    }

    pub fn process(&mut self, x: f32) -> f32 {
        self.lim.process(self.gate.process(self.hp.process(x))) * self.gain
    }
}

/// 峰值电平（RMS + peak）。
#[derive(Default, Clone, Copy)]
pub struct LevelMeter { pub rms: f32, pub peak: f32 }

pub fn measure(buf: &[f32]) -> LevelMeter {
    if buf.is_empty() { return LevelMeter::default(); }
    let sum: f32 = buf.iter().map(|s| s * s).sum();
    LevelMeter { rms: (sum / buf.len() as f32).sqrt(), peak: buf.iter().map(|s| s.abs()).fold(0.0, f32::max) }
}

/// 每 chunk 间 5ms crossfade 拼接，防 click。
pub fn crossfade_append(dst: &mut Vec<f32>, chunk: &[f32], fade_n: usize) {
    if dst.is_empty() || chunk.is_empty() {
        dst.extend_from_slice(chunk);
        return;
    }
    let n = fade_n.min(dst.len()).min(chunk.len());
    for i in 0..n {
        let a = dst.len() - n + i;
        let t = (i + 1) as f32 / (n + 1) as f32;
        dst[a] = dst[a] * (1.0 - t) + chunk[i] * t;
    }
    dst.extend_from_slice(&chunk[n..]);
}
