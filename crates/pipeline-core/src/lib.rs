//! 管线核心：统一端口类型、版本化管线图、校验、带背压的实时调度器、内置节点。
pub mod types;
pub mod graph;
pub mod validate;
pub mod native;
pub mod runtime;

pub use graph::{PipelineGraph, NodeInstance, Edge, PORT as CURRENT_PORT_FORMAT};
pub use types::*;
pub use runtime::{ExecutionEngine, EngineEvent};
