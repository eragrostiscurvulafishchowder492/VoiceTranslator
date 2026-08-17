//! 手测自动化（用户验收清单的无耳版本）：走 GUI start_pipeline 的**生产同路径**。
//!
//! cargo run -p voice-studio-desktop --example manual_test [-- --skip-full]
//!
//! T1 变声管线：WAV→vcpitch→录制，频谱验证（音高上移→过零率上升）
//! T2 ASR 管线：真实语音→funasr，文本相似度验证
//! T3 完整核心管线：WAV→ASR→断句→标准化→TTS→限幅→录制，产物验证
//! T4 原声监听：麦克风→增益→扬声器 6 秒，underrun 检查
use serde_json::json;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};
use voice_pipeline_core::graph::{Edge, NodeInstance, PipelineGraph};
use voice_pipeline_core::runtime::PluginBridge as _;
use voice_pipeline_core::types::{Msg, Payload};
use voice_studio_desktop_lib::commands::{start_pipeline_impl, stop_pipeline_impl};
use voice_studio_desktop_lib::state::AppState;

const SPEECH_WAV: &str = "logs/smoke_ai_tts.wav"; // 4.76s 真实语音("你们先过去，我拿一下东西，马上回来。")
const EXPECT_TEXT: &str = "你们先过去，我拿一下东西，马上回来。";

fn root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf()
}

fn node(id: &str, ty: &str, label: &str, params: serde_json::Value) -> NodeInstance {
    NodeInstance {
        id: id.into(),
        node_type: ty.into(),
        label: label.into(),
        params,
        position: (0.0, 0.0),
        bypassed: false,
        notes: String::new(),
        group: String::new(),
    }
}

fn edge(a: &str, ap: &str, b: &str, bp: &str) -> Edge {
    Edge {
        id: format!("e{a}{b}"),
        from_node: a.into(),
        from_port: ap.into(),
        to_node: b.into(),
        to_port: bp.into(),
        backpressure: Default::default(),
        capacity: 64,
    }
}

fn graph(name: &str, nodes: Vec<NodeInstance>, edges: Vec<Edge>) -> PipelineGraph {
    let mut g = PipelineGraph::new(name);
    g.nodes = nodes;
    g.edges = edges;
    g
}

fn zcr(samples: &[f32]) -> f64 {
    let mut z = 0;
    for w in samples.windows(2) {
        if (w[0] >= 0.0) != (w[1] >= 0.0) {
            z += 1;
        }
    }
    z as f64 / samples.len().max(1) as f64
}

fn sim(a: &str, b: &str) -> f64 {
    // 简单字符 LCS 相似度
    let a: Vec<char> = a.chars().filter(|c| !c.is_whitespace()).collect();
    let b: Vec<char> = b.chars().filter(|c| !c.is_whitespace()).collect();
    let (n, m) = (a.len(), b.len());
    let mut prev = vec![0usize; m + 1];
    let mut cur = vec![0usize; m + 1];
    for i in 1..=n {
        for j in 1..=m {
            cur[j] = if a[i - 1] == b[j - 1] {
                prev[j - 1] + 1
            } else {
                cur[j - 1].max(prev[j])
            };
        }
        std::mem::swap(&mut prev, &mut cur);
        cur.iter_mut().for_each(|x| *x = 0);
    }
    2.0 * prev[m] as f64 / (n + m).max(1) as f64
}

fn main() {
    let root = root();
    std::env::set_current_dir(&root).unwrap();
    std::env::set_var("VOICE_STUDIO_DATA", root.join("app-data"));
    std::env::set_var("PYTHONPATH", root.join("sdk").join("python"));
    let args: Vec<String> = std::env::args().collect();
    let skip_full = args.iter().any(|a| a == "--skip-full");

    let speech = root.join(SPEECH_WAV);
    assert!(
        speech.exists(),
        "测试语音缺失: {SPEECH_WAV}（先跑 tests/smoke_ai_pipeline.py）"
    );
    let _ = env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .try_init();
    let state = AppState::new(root.clone()).unwrap();
    state.plugins.discover();
    println!("=== 手测自动化（生产路径 start_pipeline_impl）===\n");

    let mut pass = 0;
    let mut fail = 0;

    // ---------- T1 变声 ----------
    {
        println!("[T1] 变声管线：WAV → 实时变声(female_bright +5半音) → 录制");
        let out = root.join("app-data/cache/manual_vc_out.wav");
        let _ = std::fs::remove_file(&out);
        let g = graph(
            "t1-vc",
            vec![
                node(
                    "f",
                    "audio.file",
                    "文件",
                    json!({"path": speech.to_string_lossy(), "loop": false}),
                ),
                node(
                    "vc",
                    "org.voicestudio.vcpitch/vcpitch.voice_convert",
                    "变声",
                    json!({"character": "female_bright"}),
                ),
                node(
                    "r",
                    "audio.file_recorder",
                    "录制",
                    json!({"path": out.to_string_lossy()}),
                ),
            ],
            vec![edge("f", "out", "vc", "in"), edge("vc", "out", "r", "in")],
        );
        match start_pipeline_impl(&state, g) {
            Ok(_) => {
                let (orig0, _, _) = voice_audio_engine::wav::read_mono_48k(&speech).unwrap();
                std::thread::sleep(Duration::from_secs(
                    (orig0.len() as f64 / 48000.0) as u64 + 5,
                ));
                stop_pipeline_impl(&state);
                match voice_audio_engine::wav::read_mono_48k(&out) {
                    Ok((samples, _, _)) if samples.len() > 24000 => {
                        let (orig, _, _) = voice_audio_engine::wav::read_mono_48k(&speech).unwrap();
                        let n = samples.len().min(orig.len());
                        let z1 = zcr(&orig[..n]);
                        let z2 = zcr(&samples[..n]);
                        // 时长保持（WSOLA）+ 过零率上升（升调）
                        let dur_ratio = samples.len() as f64 / orig.len() as f64;
                        if z2 > z1 * 1.15 && (0.8..1.25).contains(&dur_ratio) {
                            println!("  PASS：ZCR {z1:.3}→{z2:.3}（升调），时长比 {dur_ratio:.2}，{} 样本", samples.len());
                            pass += 1;
                        } else {
                            println!("  FAIL：ZCR {z1:.3}→{z2:.3}，时长比 {dur_ratio:.2}");
                            fail += 1;
                        }
                    }
                    _ => {
                        println!("  FAIL：输出缺失/过短");
                        fail += 1;
                    }
                }
            }
            Err(e) => {
                println!("  FAIL：{e}");
                fail += 1;
            }
        }
        println!();
    }

    // ---------- T2 ASR ----------
    {
        println!("[T2] ASR 管线：真实语音 → 流式识别（验证增量合并）");
        let (tx, rx) = crossbeam_channel::unbounded::<Msg>();
        let tx2 = tx.clone();
        let g = graph(
            "t2-asr",
            vec![
                node(
                    "f",
                    "audio.file",
                    "文件",
                    json!({"path": speech.to_string_lossy(), "loop": false}),
                ),
                node(
                    "rs",
                    "audio.resampler",
                    "重采样",
                    json!({"target_rate": 16000}),
                ),
                node(
                    "asr",
                    "org.voicestudio.funasr/funasr.streaming_asr",
                    "识别",
                    json!({}),
                ),
            ],
            vec![edge("f", "out", "rs", "in"), edge("rs", "out", "asr", "in")],
        );
        match start_pipeline_impl(&state, g) {
            Ok(_) => {
                // 接管路由收集识别文本（ASR 无下游边）
                if let Some(b) = state.plugins.ensure_bridge("org.voicestudio.funasr") {
                    b.set_router(Arc::new(move |_n, _p, m: Msg| {
                        let _ = tx2.send(m);
                    }));
                }
                let mut final_text = String::new();
                let t0 = Instant::now();
                while t0.elapsed() < Duration::from_secs(90) {
                    match rx.recv_timeout(Duration::from_millis(500)) {
                        Ok(m) => {
                            if let Payload::Text(t) = m.payload {
                                if t.is_final {
                                    final_text = t.text;
                                    break;
                                }
                            }
                        }
                        Err(crossbeam_channel::RecvTimeoutError::Timeout) => {
                            let done = state
                                .engine
                                .lock()
                                .as_ref()
                                .map(|e| {
                                    e.snapshot()["nodes"]
                                        .get("asr")
                                        .map(|s| s == "Ready")
                                        .unwrap_or(false)
                                })
                                .unwrap_or(false);
                            if done && !final_text.is_empty() {
                                break;
                            }
                        }
                        Err(_) => break,
                    }
                }
                stop_pipeline_impl(&state);
                let s = sim(&final_text, EXPECT_TEXT);
                if s >= 0.7 {
                    println!("  PASS：识别=\"{final_text}\" 相似度 {s:.2}");
                    pass += 1;
                } else {
                    println!("  FAIL：识别=\"{final_text}\" 相似度 {s:.2}");
                    for st in state
                        .plugins
                        .list_status()
                        .iter()
                        .filter(|x| x.id.contains("funasr"))
                    {
                        println!("       插件状态: {} detail={}", st.state, st.detail);
                    }
                    for l in state
                        .logring
                        .snapshot(12)
                        .iter()
                        .filter(|l| l.component != "audio")
                    {
                        println!("       [{}] {}", l.component, l.message);
                    }
                    fail += 1;
                }
            }
            Err(e) => {
                println!("  FAIL：{e}");
                fail += 1;
            }
        }
        println!();
    }

    // ---------- T3 完整核心管线 ----------
    if !skip_full {
        println!("[T3] 完整核心管线：WAV → ASR → 稳定前缀断句 → 标准化 → TTS → 限幅 → 录制");
        println!("      （首次含 CosyVoice 懒加载，可能需要 1~2 分钟）");
        let out = root.join("app-data/cache/manual_full_out.wav");
        let _ = std::fs::remove_file(&out);
        let g = graph(
            "t3-full",
            vec![
                node(
                    "f",
                    "audio.file",
                    "文件",
                    json!({"path": speech.to_string_lossy(), "loop": false}),
                ),
                node(
                    "rs",
                    "audio.resampler",
                    "重采样",
                    json!({"target_rate": 16000}),
                ),
                node(
                    "asr",
                    "org.voicestudio.funasr/funasr.streaming_asr",
                    "识别",
                    json!({}),
                ),
                node(
                    "seg",
                    "org.voicestudio.textkit/textkit.segmenter",
                    "断句",
                    json!({"stable_rounds": 2, "flush_timeout_ms": 800}),
                ),
                node(
                    "norm",
                    "org.voicestudio.textkit/textkit.normalizer",
                    "标准化",
                    json!({"mode": "gaming"}),
                ),
                node(
                    "tt",
                    "org.voicestudio.textkit/textkit.to_tts",
                    "→TTS",
                    json!({}),
                ),
                node(
                    "tts",
                    "org.voicestudio.cosyvoice/cosyvoice.zero_shot_tts",
                    "TTS",
                    json!({}),
                ),
                node("lim", "audio.limiter", "限幅", json!({})),
                node(
                    "r",
                    "audio.file_recorder",
                    "录制",
                    json!({"path": out.to_string_lossy()}),
                ),
            ],
            vec![
                edge("f", "out", "rs", "in"),
                edge("rs", "out", "asr", "in"),
                edge("asr", "partial", "seg", "in"),
                edge("seg", "out", "norm", "in"),
                edge("norm", "out", "tt", "in"),
                edge("tt", "out", "tts", "in"),
                edge("tts", "out", "lim", "in"),
                edge("lim", "out", "r", "in"),
            ],
        );
        match start_pipeline_impl(&state, g) {
            Ok(_) => {
                // VAD 结束语义：文件播完 3s 后给断句器发 flush（模拟语音停顿）
                std::thread::sleep(Duration::from_secs(8));
                if let Some(b) = state.plugins.ensure_bridge("org.voicestudio.textkit") {
                    let _ = b.send(
                        "seg",
                        Msg {
                            from_node: "host".into(),
                            from_port: "control".into(),
                            ts_ns: voice_common::timeutil::now_ns(),
                            payload: Payload::Control(voice_pipeline_core::types::ControlMsg {
                                signal: "flush".into(),
                                payload_json: "{}".into(),
                            }),
                        },
                    );
                }
                // 等录制完成：文件尺寸稳定
                let t0 = Instant::now();
                let mut last_len = 0u64;
                let mut stable = 0;
                while t0.elapsed() < Duration::from_secs(240) {
                    std::thread::sleep(Duration::from_millis(1000));
                    let len = std::fs::metadata(&out).map(|m| m.len()).unwrap_or(0);
                    if len == last_len && len > 0 {
                        stable += 1;
                    } else {
                        stable = 0;
                    }
                    last_len = len;
                    if stable >= 10 {
                        break;
                    }
                }
                stop_pipeline_impl(&state);
                match voice_audio_engine::wav::read_mono_48k(&out) {
                    Ok((samples, _, _)) => {
                        let dur = samples.len() as f64 / 48000.0;
                        let peak = samples.iter().map(|s| s.abs()).fold(0.0f32, f32::max);
                        let rms = (samples.iter().map(|s| s * s).sum::<f32>()
                            / samples.len().max(1) as f32)
                            .sqrt();
                        if dur > 1.0 && rms > 0.01 && peak <= 1.0 {
                            println!("  PASS：输出 {dur:.2}s 音频，RMS {rms:.3}，峰值 {peak:.3}（限幅生效）");
                            pass += 1;
                        } else {
                            println!("  FAIL：dur={dur:.2}s rms={rms:.3} peak={peak:.3}");
                            fail += 1;
                        }
                    }
                    _ => {
                        println!("  FAIL：无输出 WAV");
                        fail += 1;
                    }
                }
            }
            Err(e) => {
                println!("  FAIL：{e}");
                fail += 1;
            }
        }
        println!();
    }

    // ---------- T4 原声监听 ----------
    {
        println!("[T4] 原声监听：麦克风 → 增益 → 扬声器（6 秒，underrun 检查）");
        let g = graph(
            "t4-monitor",
            vec![
                node(
                    "m",
                    "audio.microphone",
                    "麦克风",
                    json!({"block_ms": 20, "gain_db": 3.0}),
                ),
                node("g", "audio.gain", "增益", json!({"gain_db": 0.0})),
                node("o", "audio.speaker_output", "输出", json!({})),
            ],
            vec![edge("m", "out", "g", "in"), edge("g", "out", "o", "in")],
        );
        match start_pipeline_impl(&state, g) {
            Ok(_) => {
                std::thread::sleep(Duration::from_secs(6));
                let snap = state
                    .engine
                    .lock()
                    .as_ref()
                    .map(|e| e.snapshot())
                    .unwrap_or(json!({}));
                stop_pipeline_impl(&state);
                let edge_sent: u64 = snap["edges"]
                    .as_array()
                    .map(|a| a.iter().filter_map(|e| e["sent"].as_u64()).sum())
                    .unwrap_or(0);
                let pb = state.playback.lock();
                let underruns = pb.as_ref().map(|p| p.underrun_count()).unwrap_or(0);
                let cap = state.capture.lock();
                let overflows = cap.as_ref().map(|c| c.overflow_count()).unwrap_or(0);
                if edge_sent > 200 && underruns == 0 {
                    println!("  PASS：麦克风流经 {edge_sent} 帧，underrun=0，输入溢出={overflows}");
                    pass += 1;
                } else {
                    println!(
                        "  FAIL：edge_sent={edge_sent} underrun={underruns} overflow={overflows}"
                    );
                    fail += 1;
                }
            }
            Err(e) => {
                println!("  FAIL：{e}");
                fail += 1;
            }
        }
    }

    state.plugins.stop_all();
    println!("\n=== 结果：{pass} 通过 / {fail} 失败 ===");
    std::process::exit(if fail == 0 { 0 } else { 1 });
}
