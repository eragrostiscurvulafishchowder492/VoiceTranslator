//! 内置原生节点（12.1）：不依赖任何插件即可运行。
//! 音频设备 IO 通过 DeviceBridge 与宿主音频引擎解耦。
use crate::graph::{NodeRegistry, NodeSpec, PortSpec};
use crate::types::*;
use serde_json::json;
use std::sync::Arc;

/// 宿主注入的设备桥：mic 源 / 输出汇，避免管线核心直接依赖具体音频实现。
pub struct DeviceBridge {
    /// 拉取 48k mono 输入（返回实际帧数）
    pub pull_input: Box<dyn Fn(&mut [f32]) -> usize + Send + Sync>,
    /// 提交 48k mono 输出（主输出）
    pub submit_output: Box<dyn Fn(&[f32]) + Send + Sync>,
    /// 当前 PTT 按下状态
    pub ptt_active: Box<dyn Fn() -> bool + Send + Sync>,
}

impl Default for DeviceBridge {
    fn default() -> Self {
        Self {
            pull_input: Box::new(|_| 0),
            submit_output: Box::new(|_| {}),
            ptt_active: Box::new(|| true),
        }
    }
}

pub fn builtin_registry() -> NodeRegistry {
    let mut r = NodeRegistry::default();
    let ps = |name: &str, pt: PortType, req: bool| PortSpec {
        name: name.into(), port_type: pt, required: req, sample_rate: 0, channels: 0,
    };
    let audio_in = || vec![ps("in", PortType::AudioPcm, true)];
    let audio_out = || vec![ps("out", PortType::AudioPcm, true)];

    let entries: Vec<NodeSpec> = vec![
        NodeSpec {
            node_type: "audio.microphone".into(),
            display_name: "麦克风输入".into(),
            category: "输入".into(),
            inputs: vec![],
            outputs: audio_out(),
            default_params: json!({"device": "", "block_ms": 20, "gain_db": 0.0, "gate_db": -50.0}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "audio.file".into(),
            display_name: "WAV 文件输入".into(),
            category: "输入".into(),
            inputs: vec![],
            outputs: audio_out(),
            default_params: json!({"path": "", "loop": false}),
            params_schema: Some(json!({
                "type": "object",
                "required": ["path"],
                "properties": {"path": {"type": "string", "ui:widget": "file"},
                               "loop": {"type": "boolean", "default": false}}
            })),
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "text.manual_input".into(),
            display_name: "文本输入".into(),
            category: "输入".into(),
            inputs: vec![],
            outputs: vec![ps("out", PortType::TextSegment, true)],
            default_params: json!({"text": ""}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "audio.gain".into(),
            display_name: "增益".into(),
            category: "音频效果".into(),
            inputs: audio_in(),
            outputs: audio_out(),
            default_params: json!({"gain_db": 0.0}),
            params_schema: Some(json!({
                "type": "object",
                "properties": {"gain_db": {"type": "number", "minimum": -40, "maximum": 40,
                                           "default": 0, "ui:widget": "slider", "unit": "dB"}}
            })),
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "audio.noise_gate".into(),
            display_name: "噪声门".into(),
            category: "音频效果".into(),
            inputs: audio_in(),
            outputs: audio_out(),
            default_params: json!({"threshold_db": -45.0, "hold_ms": 80.0}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "audio.limiter".into(),
            display_name: "限幅器".into(),
            category: "音频效果".into(),
            inputs: audio_in(),
            outputs: audio_out(),
            default_params: json!({"ceiling_db": -1.0}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "audio.high_pass".into(),
            display_name: "高通滤波".into(),
            category: "音频效果".into(),
            inputs: audio_in(),
            outputs: audio_out(),
            default_params: json!({"cutoff_hz": 80.0}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "audio.resampler".into(),
            display_name: "重采样".into(),
            category: "音频效果".into(),
            inputs: audio_in(),
            outputs: audio_out(),
            default_params: json!({"target_rate": 16000}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "audio.channel_converter".into(),
            display_name: "声道转换".into(),
            category: "音频效果".into(),
            inputs: audio_in(),
            outputs: audio_out(),
            default_params: json!({"target_channels": 1}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "audio.speaker_output".into(),
            display_name: "扬声器输出".into(),
            category: "输出".into(),
            inputs: audio_in(),
            outputs: vec![],
            default_params: json!({"device": ""}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "audio.virtual_output".into(),
            display_name: "虚拟音频输出".into(),
            category: "输出".into(),
            inputs: audio_in(),
            outputs: vec![],
            default_params: json!({"device": ""}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "audio.file_recorder".into(),
            display_name: "WAV 录制".into(),
            category: "输出".into(),
            inputs: audio_in(),
            outputs: vec![],
            default_params: json!({"path": ""}),
            params_schema: Some(json!({
                "type": "object", "required": ["path"],
                "properties": {"path": {"type": "string", "ui:widget": "savefile"}}
            })),
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "text.file_output".into(),
            display_name: "文本输出(文件)".into(),
            category: "输出".into(),
            inputs: vec![ps("in", PortType::TextFinal, true)],
            outputs: vec![],
            default_params: json!({"path": ""}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "control.push_to_talk".into(),
            display_name: "按键说话".into(),
            category: "控制".into(),
            inputs: vec![ps("in", PortType::AudioPcm, true), ps("control", PortType::ControlSignal, false)],
            outputs: audio_out(),
            default_params: json!({"mode": "hold"}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
        NodeSpec {
            node_type: "metrics.tap".into(),
            display_name: "实时指标".into(),
            category: "控制".into(),
            inputs: vec![ps("in", PortType::AudioPcm, false), ps("text", PortType::TextPartial, false)],
            outputs: vec![ps("out", PortType::MetricsSample, true)],
            default_params: json!({}),
            params_schema: None,
            estimated_vram_mb: 0,
        },
    ];
    for e in entries { r.register(e); }
    r
}

/// 内置节点处理器状态机（每个节点实例一个）。
pub enum NativeProcessor {
    Microphone { bridge: Arc<DeviceBridge>, block_ms: u32, seq: u64, stream_id: String },
    FileSource { samples: Arc<Vec<f32>>, pos: usize, loop_: bool, rate: u32, seq: u64 },
    TextInput { pending: Option<String>, sent: bool },
    Gain(f32),
    NoiseGate(voice_audio_engine::dsp::NoiseGate),
    Limiter(voice_audio_engine::dsp::Limiter),
    HighPass(voice_audio_engine::dsp::HighPass),
    Resampler { target: u32, rs: voice_audio_engine::resampler::StreamResampler, seq: u64 },
    ChannelConverter { target: u16 },
    SpeakerOut { bridge: Arc<DeviceBridge> },
    Recorder { writer: Option<hound::WavWriter<std::io::BufWriter<std::fs::File>>> },
    TextFileOut { path: std::path::PathBuf, written: u32 },
    PushToTalk { bridge: Arc<DeviceBridge> },
    MetricsTap { count: u64, last_ns: i64 },
    Bypassed,
}

pub fn create_native(node_type: &str, params: &serde_json::Value, bridge: &Arc<DeviceBridge>)
    -> anyhow::Result<NativeProcessor> {
    let g = |k: &str, d: f32| params.get(k).and_then(|v| v.as_f64()).unwrap_or(d as f64) as f32;
    Ok(match node_type {
        "audio.microphone" => NativeProcessor::Microphone {
            bridge: bridge.clone(),
            block_ms: params.get("block_ms").and_then(|v| v.as_u64()).unwrap_or(20) as u32,
            seq: 0,
            stream_id: voice_common::ids::new_id("mic"),
        },
        "audio.file" => {
            let path = params.get("path").and_then(|v| v.as_str()).unwrap_or("");
            anyhow::ensure!(!path.is_empty(), "audio.file 需要 path 参数");
            let (samples, rate, _) = voice_audio_engine::wav::read_mono_48k(std::path::Path::new(path))?;
            NativeProcessor::FileSource { samples: Arc::new(samples), pos: 0,
                loop_: params.get("loop").and_then(|v| v.as_bool()).unwrap_or(false), rate, seq: 0 }
        }
        "text.manual_input" => NativeProcessor::TextInput {
            pending: Some(params.get("text").and_then(|v| v.as_str()).unwrap_or("").to_string()),
            sent: false,
        },
        "audio.gain" => NativeProcessor::Gain(10f32.powf(g("gain_db", 0.0) / 20.0)),
        "audio.noise_gate" => NativeProcessor::NoiseGate(
            voice_audio_engine::dsp::NoiseGate::new(g("threshold_db", -45.0), 3.0, 60.0, 48_000.0, g("hold_ms", 80.0))),
        "audio.limiter" => NativeProcessor::Limiter(
            voice_audio_engine::dsp::Limiter::new(g("ceiling_db", -1.0), 50.0, 48_000.0)),
        "audio.high_pass" => NativeProcessor::HighPass(
            voice_audio_engine::dsp::HighPass::new(48_000.0, g("cutoff_hz", 80.0))),
        "audio.resampler" => NativeProcessor::Resampler {
            target: params.get("target_rate").and_then(|v| v.as_u64()).unwrap_or(16_000) as u32,
            rs: voice_audio_engine::resampler::StreamResampler::new(48_000, 16_000, 480)?,
            seq: 0,
        },
        "audio.channel_converter" => NativeProcessor::ChannelConverter {
            target: params.get("target_channels").and_then(|v| v.as_u64()).unwrap_or(1) as u16,
        },
        "audio.speaker_output" | "audio.virtual_output" => NativeProcessor::SpeakerOut { bridge: bridge.clone() },
        "audio.file_recorder" => {
            let path = params.get("path").and_then(|v| v.as_str()).unwrap_or("");
            anyhow::ensure!(!path.is_empty(), "audio.file_recorder 需要 path 参数");
            NativeProcessor::Recorder { writer: None }
        },
        "text.file_output" => NativeProcessor::TextFileOut {
            path: params.get("path").and_then(|v| v.as_str()).unwrap_or("output.txt").into(),
            written: 0,
        },
        "control.push_to_talk" => NativeProcessor::PushToTalk { bridge: bridge.clone() },
        "metrics.tap" => NativeProcessor::MetricsTap { count: 0, last_ns: 0 },
        _ => anyhow::bail!("非内置节点: {node_type}"),
    })
}
