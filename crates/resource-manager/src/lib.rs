//! Resource Manager（二十.）：GPU/CPU/内存采集、显存预检、OOM 恢复顺序。
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct ResourceSnapshot {
    pub gpu_name: String,
    pub vram_total_mb: u32,
    pub vram_used_mb: u32,
    pub cpu_percent: f32,
    pub mem_total_gb: f32,
    pub mem_used_gb: f32,
    pub ts: String,
}

pub struct ResourceManager {
    nvml: Option<nvml_wrapper::Nvml>,
    sys: parking_lot::Mutex<sysinfo::System>,
}

impl ResourceManager {
    pub fn new() -> Self {
        let nvml = nvml_wrapper::Nvml::init().ok();
        if nvml.is_none() { log::warn!("NVML 不可用（无 NVIDIA GPU 或驱动问题）"); }
        Self { nvml, sys: parking_lot::Mutex::new(sysinfo::System::new()) }
    }

    pub fn snapshot(&self) -> ResourceSnapshot {
        let mut sys = self.sys.lock();
        sys.refresh_cpu_usage();
        sys.refresh_memory();
        let (name, total, used) = self.gpu_info();
        ResourceSnapshot {
            gpu_name: name,
            vram_total_mb: total,
            vram_used_mb: used,
            cpu_percent: sys.global_cpu_usage(),
            mem_total_gb: sys.total_memory() as f32 / 1e9,
            mem_used_gb: sys.used_memory() as f32 / 1e9,
            ts: chrono::Local::now().format("%H:%M:%S").to_string(),
        }
    }

    fn gpu_info(&self) -> (String, u32, u32) {
        if let Some(nvml) = &self.nvml {
            if let Ok(dev) = nvml.device_by_index(0) {
                let name = dev.name().map(|s| s.trim().to_string()).unwrap_or_default();
                let mem = dev.memory_info().ok();
                let total = mem.as_ref().map(|m| (m.total / 1_048_576) as u32).unwrap_or(0);
                let used = mem.as_ref().map(|m| (m.used / 1_048_576) as u32).unwrap_or(0);
                return (name, total, used);
            }
        }
        (String::new(), 0, 0)
    }

    /// 启动管线前资源预检（二十.）：返回错误则拒绝启动，警告则允许。
    pub fn preflight(&self, estimated_vram_mb: u32) -> Result<(), String> {
        let s = self.snapshot();
        if s.vram_total_mb == 0 {
            return Ok(()); // 无 GPU 信息时不阻塞
        }
        let avail = s.vram_total_mb.saturating_sub(s.vram_used_mb);
        if estimated_vram_mb > avail {
            return Err(format!(
                "显存预检失败：需要 {}MB，可用 {}MB（可尝试 asr_cpu 模式或卸载其他模型）",
                estimated_vram_mb, avail));
        }
        Ok(())
    }
}

impl Default for ResourceManager {
    fn default() -> Self { Self::new() }
}
