//! 诊断：GUI 内存日志环形缓冲 + 组件健康检查 + 崩溃标记。
use parking_lot::Mutex;
use std::collections::VecDeque;

/// GUI 可见的日志环（最近 N 条，组件/插件/事件标签）。
pub struct LogRing {
    buf: Mutex<VecDeque<LogLine>>,
    cap: usize,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct LogLine {
    pub ts: String,
    pub level: String,
    pub component: String,
    pub message: String,
}

impl LogRing {
    pub fn new(cap: usize) -> Self {
        Self {
            buf: Mutex::new(VecDeque::with_capacity(cap)),
            cap,
        }
    }

    pub fn push(&self, level: &str, component: &str, message: impl Into<String>) {
        let mut b = self.buf.lock();
        if b.len() >= self.cap {
            b.pop_front();
        }
        b.push_back(LogLine {
            ts: chrono::Local::now().format("%H:%M:%S%.3f").to_string(),
            level: level.into(),
            component: component.into(),
            message: message.into(),
        });
    }

    pub fn snapshot(&self, last_n: usize) -> Vec<LogLine> {
        self.buf
            .lock()
            .iter()
            .rev()
            .take(last_n)
            .rev()
            .cloned()
            .collect()
    }
}

impl Default for LogRing {
    fn default() -> Self {
        Self::new(2000)
    }
}

/// 崩溃标记：启动时写入，正常退出清除；下次启动若残留 → 提供安全模式。
pub fn crash_marker_path(data_dir: &std::path::Path) -> std::path::PathBuf {
    data_dir.join("logs").join(".crash_marker")
}

pub fn mark_running(data_dir: &std::path::Path) {
    let _ = std::fs::write(crash_marker_path(data_dir), chrono::Utc::now().to_rfc3339());
}

pub fn mark_clean_exit(data_dir: &std::path::Path) {
    let _ = std::fs::remove_file(crash_marker_path(data_dir));
}

pub fn was_abnormal_exit(data_dir: &std::path::Path) -> bool {
    crash_marker_path(data_dir).exists()
}
