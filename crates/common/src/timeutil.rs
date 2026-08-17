//! 单调时钟（音频时间戳用），与墙钟（日志用）区分。
use std::time::{SystemTime, UNIX_EPOCH};

pub fn now_ns() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos() as i64)
        .unwrap_or(0)
}

pub fn now_ms() -> i64 {
    now_ns() / 1_000_000
}

pub fn iso_now() -> String {
    chrono::Local::now()
        .format("%Y-%m-%dT%H:%M:%S%.3f")
        .to_string()
}
