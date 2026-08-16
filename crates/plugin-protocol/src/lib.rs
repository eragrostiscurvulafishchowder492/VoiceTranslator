//! gRPC 插件协议（Rust 客户端侧生成代码）。
pub mod voice_plugin {
    pub mod v1 {
        include!(concat!(env!("OUT_DIR"), "/voice_plugin.v1.rs"));
    }
}

/// 宿主与插件共同遵守的协议版本（协商失败则拒绝运行）。
pub const HOST_PROTOCOL_VERSION: &str = "1.0";

pub mod prelude {
    pub use tonic::transport::Channel;
    pub use tonic::Request;
    pub use crate::voice_plugin::v1::*;
}

/// 音频格式描述串："pcm_f32le@48000:1"
pub fn format_audio(rate: u32, ch: u16) -> String {
    format!("pcm_f32le@{rate}:{ch}")
}
