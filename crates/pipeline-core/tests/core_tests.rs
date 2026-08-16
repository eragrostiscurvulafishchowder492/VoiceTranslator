//! pipeline-core 单元测试：图校验、循环检测、序列化、背压策略、迁移。
use voice_pipeline_core::graph::{Edge, NodeInstance, PipelineGraph};
use voice_pipeline_core::native::builtin_registry;
use voice_pipeline_core::types::{Backpressure, Payload, PortType};
use voice_pipeline_core::validate::{validate, ExternalChecks, Severity};

fn n(id: &str, ty: &str) -> NodeInstance {
    NodeInstance { id: id.into(), node_type: ty.into(), label: id.into(),
                   params: serde_json::json!({}), position: (0.0, 0.0),
                   bypassed: false, notes: String::new(), group: String::new() }
}

fn e(a: &str, ap: &str, b: &str, bp: &str) -> Edge {
    Edge { id: format!("e{a}{b}"), from_node: a.into(), from_port: ap.into(),
           to_node: b.into(), to_port: bp.into(),
           backpressure: Backpressure::Block, capacity: 4 }
}

#[test]
fn port_type_compat() {
    assert!(PortType::parse("audio.pcm").is_some());
    assert_eq!(PortType::AudioPcm.as_str(), "audio.pcm");
    assert!(PortType::parse("bogus.type").is_none());
}

#[test]
fn graph_roundtrip_serialization() {
    let mut g = PipelineGraph::new("测试");
    g.nodes.push(n("m", "audio.microphone"));
    g.nodes.push(n("o", "audio.speaker_output"));
    g.edges.push(e("m", "out", "o", "in"));
    let dir = std::env::temp_dir().join("vc_graph_test");
    std::fs::create_dir_all(&dir).unwrap();
    let f = dir.join("g.json");
    g.save_json(&f).unwrap();
    let g2 = PipelineGraph::load_json(&f).unwrap();
    assert_eq!(g2.nodes.len(), 2);
    assert_eq!(g2.format_version, 1);
}

#[test]
fn validate_type_mismatch() {
    let mut g = PipelineGraph::new("坏类型");
    g.nodes.push(n("t", "text.manual_input"));
    g.nodes.push(n("o", "audio.speaker_output"));
    g.edges.push(e("t", "out", "o", "in")); // text.segment → audio.pcm
    let reg = builtin_registry();
    let issues = validate(&g, &reg, &ExternalChecks::default());
    assert!(issues.iter().any(|i| i.code == "TYPE_MISMATCH"), "应检出类型不匹配: {issues:?}");
}

#[test]
fn validate_cycle_detection() {
    let mut g = PipelineGraph::new("循环");
    g.nodes.push(n("g1", "audio.gain"));
    g.nodes.push(n("g2", "audio.gain"));
    g.nodes.push(n("g3", "audio.gain"));
    g.edges.push(e("g1", "out", "g2", "in"));
    g.edges.push(e("g2", "out", "g3", "in"));
    g.edges.push(e("g3", "out", "g1", "in"));
    let reg = builtin_registry();
    let issues = validate(&g, &reg, &ExternalChecks::default());
    assert!(issues.iter().any(|i| i.code == "CYCLE"), "应检出循环: {issues:?}");
}

#[test]
fn validate_required_input() {
    let mut g = PipelineGraph::new("缺输入");
    g.nodes.push(n("o", "audio.speaker_output")); // 必需输入未连
    let reg = builtin_registry();
    let issues = validate(&g, &reg, &ExternalChecks::default());
    assert!(issues.iter().any(|i| i.code == "REQUIRED_INPUT" && i.level == Severity::Error));
}

#[test]
fn validate_missing_plugin() {
    let mut g = PipelineGraph::new("缺插件");
    g.nodes.push(NodeInstance { id: "x".into(),
        node_type: "org.nothing.missing/some.node".into(), label: "x".into(),
        params: serde_json::json!({}), position: (0.0, 0.0),
        bypassed: false, notes: String::new(), group: String::new() });
    let reg = builtin_registry();
    let ext = ExternalChecks { is_plugin_installed: Box::new(|_| false),
        has_model: Box::new(|_, _| false), total_vram_mb: 0, used_vram_mb: 0 };
    let issues = validate(&g, &reg, &ext);
    assert!(issues.iter().any(|i| i.code == "PLUGIN_MISSING"));
}

#[test]
fn validate_vram_preflight() {
    let mut g = PipelineGraph::new("显存预检");
    g.nodes.push(n("m", "audio.microphone"));
    let reg = builtin_registry();
    let ext = ExternalChecks { is_plugin_installed: Box::new(|_| true),
        has_model: Box::new(|_, _| true), total_vram_mb: 8188, used_vram_mb: 6000 };
    // 内置节点 VRAM=0 不触发；仅当注册表含高 VRAM 插件节点才可能 Warning
    let issues = validate(&g, &reg, &ext);
    assert!(!issues.iter().any(|i| i.code == "VRAM_TIGHT"));
}

#[test]
fn export_sanitizes_paths() {
    let mut node = n("f", "audio.file");
    node.params = serde_json::json!({"path": "D:\\secret\\ref.wav"});
    let mut g = PipelineGraph::new("隐私");
    g.nodes.push(node);
    let s = g.export_sanitized().unwrap();
    assert!(!s.contains("secret"), "导出不得包含本地绝对路径");
    assert!(s.contains("$USER_FILE"));
}

#[test]
fn backpressure_parse() {
    assert_eq!(Backpressure::parse("LATEST_ONLY"), Backpressure::LatestOnly);
    assert_eq!(Backpressure::parse("DROP_OLDEST"), Backpressure::DropOldest);
    assert_eq!(Backpressure::parse("whatever"), Backpressure::Block);
}

#[test]
fn payload_port_type() {
    let audio = Payload::Audio(voice_pipeline_core::types::AudioChunk {
        stream_id: "s".into(), sequence: 0, timestamp_ns: 0, sample_rate: 48000,
        channels: 1, samples: std::sync::Arc::new(vec![]),
        end_of_stream: false, end_of_utterance: false,
    });
    assert_eq!(audio.port_type(), PortType::AudioPcm);
}
