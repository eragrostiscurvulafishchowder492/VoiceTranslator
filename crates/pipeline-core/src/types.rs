//! 统一端口类型与消息信封（版本化）。节点间禁止传递无类型数据。
use serde::{Deserialize, Serialize};
use std::sync::Arc;

/// 统一端口类型（七.）：全部小写点分。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum PortType {
    #[serde(rename = "audio.pcm")]
    AudioPcm,
    #[serde(rename = "audio.encoded")]
    AudioEncoded,
    #[serde(rename = "speech.vad_event")]
    VadEvent,
    #[serde(rename = "text.partial")]
    TextPartial,
    #[serde(rename = "text.final")]
    TextFinal,
    #[serde(rename = "text.segment")]
    TextSegment,
    #[serde(rename = "tts.request")]
    TtsRequest,
    #[serde(rename = "control.signal")]
    ControlSignal,
    #[serde(rename = "system.event")]
    SystemEvent,
    #[serde(rename = "metrics.sample")]
    MetricsSample,
}

impl PortType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::AudioPcm => "audio.pcm",
            Self::AudioEncoded => "audio.encoded",
            Self::VadEvent => "speech.vad_event",
            Self::TextPartial => "text.partial",
            Self::TextFinal => "text.final",
            Self::TextSegment => "text.segment",
            Self::TtsRequest => "tts.request",
            Self::ControlSignal => "control.signal",
            Self::SystemEvent => "system.event",
            Self::MetricsSample => "metrics.sample",
        }
    }

    pub fn parse(s: &str) -> Option<Self> {
        Some(match s {
            "audio.pcm" => Self::AudioPcm,
            "audio.encoded" => Self::AudioEncoded,
            "speech.vad_event" => Self::VadEvent,
            "text.partial" => Self::TextPartial,
            "text.final" => Self::TextFinal,
            "text.segment" => Self::TextSegment,
            "tts.request" => Self::TtsRequest,
            "control.signal" => Self::ControlSignal,
            "system.event" => Self::SystemEvent,
            "metrics.sample" => Self::MetricsSample,
            _ => return None,
        })
    }
}

/// 端口兼容：同类型即可连接；音频端口再由采样率/声道校验（见 validate）。
pub fn port_compatible(a: PortType, b: PortType) -> bool {
    a == b
}

/// PCM 音频块（内部统一 f32 mono；sample_rate 标注原始率）。
#[derive(Debug, Clone)]
pub struct AudioChunk {
    pub stream_id: String,
    pub sequence: u64,
    pub timestamp_ns: i64,
    pub sample_rate: u32,
    pub channels: u16,
    pub samples: Arc<Vec<f32>>,
    pub end_of_stream: bool,
    pub end_of_utterance: bool,
}

#[derive(Debug, Clone)]
pub struct TextMsg {
    pub stream_id: String,
    pub segment_id: String,
    pub sequence: u64,
    pub text: String,
    pub language: String,
    pub is_partial: bool,
    pub is_final: bool,
    pub stability: f32,
    pub start_time: f64,
    pub end_time: f64,
    pub confidence: f32,
}

#[derive(Debug, Clone)]
pub struct TtsRequestMsg {
    pub request_id: String,
    pub text: String,
    pub language: String,
    pub voice_profile: String,
    pub style: String,
    pub speed: f32,
    pub pitch: f32,
    pub energy: f32,
    pub priority: i32,
    pub interrupt_mode: String, // QUEUE / INTERRUPT / REPLACE_PENDING / DROP_IF_BUSY
}

#[derive(Debug, Clone)]
pub struct ControlMsg {
    pub signal: String, // vad_start / vad_end / ptt_down / ptt_up / flush / eos / interrupt / clear
    pub payload_json: String,
}

#[derive(Debug, Clone)]
pub struct MetricsMsg {
    pub metric: String,
    pub value: f32,
    pub timestamp_ns: i64,
}

/// 消息信封：携带来源与负载。
#[derive(Debug, Clone)]
pub struct Msg {
    pub from_node: String,
    pub from_port: String,
    pub ts_ns: i64,
    pub payload: Payload,
}

#[derive(Debug, Clone)]
pub enum Payload {
    Audio(AudioChunk),
    Text(TextMsg),
    TtsRequest(TtsRequestMsg),
    Control(ControlMsg),
    Metrics(MetricsMsg),
}

impl Payload {
    pub fn port_type(&self) -> PortType {
        match self {
            Payload::Audio(_) => PortType::AudioPcm,
            Payload::Text(t) => {
                if t.is_final { PortType::TextFinal }
                else if t.is_partial { PortType::TextPartial }
                else { PortType::TextSegment }
            }
            Payload::TtsRequest(_) => PortType::TtsRequest,
            Payload::Control(_) => PortType::ControlSignal,
            Payload::Metrics(_) => PortType::MetricsSample,
        }
    }
}

/// 每条连接的背压策略（九.）。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum Backpressure {
    #[default]
    Block,
    DropOldest,
    DropNewest,
    LatestOnly,
    FailPipeline,
}

impl Backpressure {
    pub fn parse(s: &str) -> Self {
        match s {
            "DROP_OLDEST" => Self::DropOldest,
            "DROP_NEWEST" => Self::DropNewest,
            "LATEST_ONLY" => Self::LatestOnly,
            "FAIL_PIPELINE" => Self::FailPipeline,
            _ => Self::Block,
        }
    }
}

/// 管线状态。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum PipelineState {
    #[default]
    Stopped,
    Starting,
    Running,
    Degraded,
    Stopping,
    Failed,
}

/// 节点状态。
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
pub enum NodeState {
    #[default]
    Unloaded,
    Loading,
    Ready,
    Processing,
    Bypassed,
    Error,
    Restarting,
}
