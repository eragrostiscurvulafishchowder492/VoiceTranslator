//! 插件宿主：发现、manifest 校验、安装（ZIP）、Worker 进程管理、
//! gRPC 生命周期（握手/心跳/重启限制）、进程桥接到管线引擎。
//! 注意：进程隔离 ≠ 完整安全沙箱（见 docs/SECURITY.md）。
pub mod manifest;
pub mod manager;
pub mod worker;
pub mod bridge;
pub mod install;

pub use manager::{PluginManager, PluginStatus};
pub use manifest::{PluginManifest, NodeTypeDef, ModelDef};
