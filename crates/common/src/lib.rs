//! 公共基础：路径、ID、时间、错误、日志。
pub mod ids;
pub mod logging;
pub mod paths;
pub mod timeutil;

pub use paths::AppPaths;

/// 统一错误类型（避免在各 crate 重复定义）。
#[derive(thiserror::Error, Debug)]
pub enum VoiceError {
    #[error("IO: {0}")]
    Io(#[from] std::io::Error),
    #[error("配置/数据格式错误: {0}")]
    Format(String),
    #[error("插件错误: {0}")]
    Plugin(String),
    #[error("管线错误: {0}")]
    Pipeline(String),
    #[error("音频设备错误: {0}")]
    Audio(String),
    #[error("资源不足: {0}")]
    Resource(String),
}

pub type Result<T> = std::result::Result<T, VoiceError>;
