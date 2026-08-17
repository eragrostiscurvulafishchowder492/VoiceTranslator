//! 管线核心：统一端口类型、版本化管线图、校验、带背压的实时调度器、内置节点。
pub mod graph;
pub mod native;
pub mod runtime;
pub mod types;
pub mod validate;

pub use graph::{Edge, NodeInstance, PipelineGraph, PORT as CURRENT_PORT_FORMAT};
pub use runtime::{EngineEvent, ExecutionEngine};
pub use types::*;
