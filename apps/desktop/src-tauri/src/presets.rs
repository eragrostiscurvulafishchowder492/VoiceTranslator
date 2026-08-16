//! 预置管线（十三.）：首启时写入 DB。
use serde_json::json;
use voice_pipeline_core::graph::{Edge, NodeInstance, PipelineGraph};

fn node(id: &str, node_type: &str, label: &str, x: f32, y: f32, params: serde_json::Value) -> NodeInstance {
    NodeInstance { id: id.into(), node_type: node_type.into(), label: label.into(),
                   params, position: (x, y), bypassed: false, notes: String::new(), group: String::new() }
}

fn edge(from: &str, fp: &str, to: &str, tp: &str) -> Edge {
    Edge { id: voice_common::ids::new_id("e"), from_node: from.into(), from_port: fp.into(),
           to_node: to.into(), to_port: tp.into(),
           backpressure: Default::default(), capacity: 64 }
}

fn graph(name: &str, desc: &str, nodes: Vec<NodeInstance>, edges: Vec<Edge>) -> (PipelineGraph, String) {
    let mut g = PipelineGraph::new(name);
    g.description = desc.into();
    g.nodes = nodes;
    g.edges = edges;
    let json = serde_json::to_string(&g).unwrap();
    (g, json)
}

pub fn builtin_presets() -> Vec<(String, String)> {  // (name, graph_json)
    let mut out = Vec::new();

    // 13.1 原声监听
    out.push(graph("原声监听", "麦克风 → 增益 → 限幅 → 扬声器",
        vec![
            node("mic", "audio.microphone", "麦克风", 60.0, 160.0, json!({"block_ms": 20})),
            node("gain", "audio.gain", "增益", 320.0, 100.0, json!({"gain_db": 3.0})),
            node("lim", "audio.limiter", "限幅", 580.0, 160.0, json!({})),
            node("out", "audio.speaker_output", "扬声器输出", 840.0, 160.0, json!({})),
        ],
        vec![edge("mic", "out", "gain", "in"), edge("gain", "out", "lim", "in"), edge("lim", "out", "out", "in")]));

    // 13.2 中文 ASR 字幕
    out.push(graph("中文 ASR 字幕", "麦克风 → VAD → 流式识别 → 字幕面板（text.file_output 记录）",
        vec![
            node("mic", "audio.microphone", "麦克风", 60.0, 160.0, json!({"block_ms": 20})),
            node("rs", "audio.resampler", "重采样 48k→16k", 300.0, 160.0, json!({"target_rate": 16000})),
            node("asr", "org.voicestudio.funasr/funasr.streaming_asr", "流式识别", 540.0, 160.0, json!({})),
            node("txt", "text.file_output", "字幕输出", 820.0, 160.0, json!({"path": "subtitles.txt"})),
        ],
        vec![edge("mic", "out", "rs", "in"), edge("rs", "out", "asr", "in"), edge("asr", "final", "txt", "in")]));

    // 13.3 中文语音转目标音色（核心用例）
    out.push(graph("中文语音转目标音色", "麦克风 → 识别 → 稳定前缀断句 → 零样本 TTS → 限幅 → 虚拟输出",
        vec![
            node("mic", "audio.microphone", "麦克风", 40.0, 240.0, json!({"block_ms": 20})),
            node("rs", "audio.resampler", "重采样→16k", 250.0, 240.0, json!({"target_rate": 16000})),
            node("asr", "org.voicestudio.funasr/funasr.streaming_asr", "流式识别", 460.0, 240.0, json!({})),
            node("seg", "org.voicestudio.textkit/textkit.segmenter", "稳定前缀+断句", 700.0, 240.0, json!({})),
            node("norm", "org.voicestudio.textkit/textkit.normalizer", "文本标准化", 930.0, 240.0, json!({"mode": "gaming"})),
            node("ttsreq", "org.voicestudio.textkit/textkit.to_tts", "→TTS请求", 1160.0, 240.0, json!({})),
            node("tts", "org.voicestudio.cosyvoice/cosyvoice.zero_shot_tts", "零样本 TTS", 1390.0, 240.0, json!({})),
            node("lim", "audio.limiter", "限幅", 1620.0, 240.0, json!({})),
            node("vout", "audio.virtual_output", "虚拟输出", 1840.0, 240.0, json!({})),
        ],
        vec![
            edge("mic", "out", "rs", "in"), edge("rs", "out", "asr", "in"),
            edge("asr", "partial", "seg", "in"), edge("seg", "out", "norm", "in"),
            edge("norm", "out", "ttsreq", "in"), edge("ttsreq", "out", "tts", "in"),
            edge("tts", "out", "lim", "in"), edge("lim", "out", "vout", "in"),
        ]));

    // 13.4 直接实时变声
    out.push(graph("直接实时变声", "麦克风 → 噪声门 → 变声 → 限幅 → 虚拟输出",
        vec![
            node("mic", "audio.microphone", "麦克风", 60.0, 160.0, json!({"block_ms": 20})),
            node("gate", "audio.noise_gate", "噪声门", 300.0, 160.0, json!({"threshold_db": -45.0})),
            node("vc", "org.voicestudio.vcpitch/vcpitch.voice_convert", "实时变声", 540.0, 160.0,
                 json!({"character": "female_bright"})),
            node("lim", "audio.limiter", "限幅", 780.0, 160.0, json!({})),
            node("vout", "audio.virtual_output", "虚拟输出", 1020.0, 160.0, json!({})),
        ],
        vec![edge("mic", "out", "gate", "in"), edge("gate", "out", "vc", "in"),
             edge("vc", "out", "lim", "in"), edge("lim", "out", "vout", "in")]));

    // 13.5 双路输出
    out.push(graph("双路输出", "文件输入 → 增益 → 虚拟输出 + 扬声器",
        vec![
            node("file", "audio.file", "WAV 文件", 60.0, 140.0, json!({"path": "", "loop": false})),
            node("gain", "audio.gain", "增益", 320.0, 140.0, json!({"gain_db": 0.0})),
            node("vout", "audio.virtual_output", "虚拟输出", 600.0, 80.0, json!({})),
            node("sout", "audio.speaker_output", "监听输出", 600.0, 220.0, json!({})),
        ],
        vec![edge("file", "out", "gain", "in"), edge("gain", "out", "vout", "in"), edge("gain", "out", "sout", "in")]));

    // 13.6 中文翻译语音（实验模板：标注缺失依赖）
    out.push(graph("中文翻译语音 (实验)", "需安装翻译插件（text.translator）后把『标准化』连到翻译节点；当前模板显示缺失依赖",
        vec![
            node("mic", "audio.microphone", "麦克风", 60.0, 160.0, json!({"block_ms": 20})),
            node("rs", "audio.resampler", "重采样→16k", 280.0, 160.0, json!({"target_rate": 16000})),
            node("asr", "org.voicestudio.funasr/funasr.streaming_asr", "流式识别", 500.0, 160.0, json!({})),
            node("note", "text.file_output", "文本暂存", 780.0, 160.0, json!({"path": "translate_in.txt"})),
        ],
        vec![edge("mic", "out", "rs", "in"), edge("rs", "out", "asr", "in"), edge("asr", "final", "note", "in")]));

    out.into_iter().map(|(g, j)| (g.name.clone(), j)).collect()
}

/// 首启/缺预置时写入 DB（幂等：同名跳过）。
pub fn ensure_installed(store: &voice_persistence::Store) {
    let existing: Vec<String> = store.list_pipelines().into_iter().map(|p| p.name).collect();
    for (name, json) in builtin_presets() {
        if !existing.contains(&name) {
            let g: PipelineGraph = serde_json::from_str(&json).unwrap();
            let _ = store.save_pipeline(&g.id, &name, &json, name == "中文语音转目标音色");
        }
    }
}
