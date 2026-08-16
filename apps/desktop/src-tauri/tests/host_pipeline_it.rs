//! 桌面宿主命令层集成测试：原生节点管线（WAV 文件 → 增益 → 录制）全链路。
//! 不开窗口、不需要音频硬件（文件源 + 文件汇），验证：
//! app_init / node_registry / validate / start_pipeline / snapshot / stop_pipeline。
use serde_json::json;

fn repo_root() -> std::path::PathBuf {
    let mut d = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    for _ in 0..4 { d.pop(); }
    d
}

#[test]
fn native_pipeline_end_to_end_via_commands() {
    let root = repo_root();
    let data_dir = std::env::temp_dir().join(format!("vs_host_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&data_dir);
    std::env::set_var("VOICE_STUDIO_DATA", &data_dir);
    let state = voice_studio_desktop_lib::state::AppState::new(root.clone()).unwrap();
    voice_studio_desktop_lib::presets::ensure_installed(&state.store);

    // 1) init：预置管线已写入
    let pl = state.store.list_pipelines();
    assert!(pl.len() >= 6, "预置管线 ≥6，实际 {pl:?}");

    // 2) 节点注册表：内置节点齐全
    let builtin_count = state.registry.read().all().len();
    assert!(builtin_count >= 15, "内置节点 ≥15（12.1），实际 {builtin_count}");

    // 3) 造测试 WAV（1 秒 440Hz）
    let wav = data_dir.join("in.wav");
    let sr = 48000u32;
    let samples: Vec<f32> = (0..sr).map(|i| {
        0.3 * (2.0 * std::f32::consts::PI * 440.0 * i as f32 / sr as f32).sin()
    }).collect();
    voice_audio_engine::wav::write_wav(&wav, &samples, sr).unwrap();

    // 4) 管线：file → gain(+6dB) → recorder
    let out_wav = data_dir.join("out.wav");
    let graph = json!({
        "format_version": 1, "id": "it_graph", "name": "it",
        "nodes": [
            {"id": "f", "node_type": "audio.file", "label": "文件",
             "params": {"path": wav.to_string_lossy(), "loop": false}, "position": [0.0, 0.0]},
            {"id": "g", "node_type": "audio.gain", "label": "增益",
             "params": {"gain_db": 6.0}, "position": [200.0, 0.0]},
            {"id": "r", "node_type": "audio.file_recorder", "label": "录制",
             "params": {"path": out_wav.to_string_lossy()}, "position": [400.0, 0.0]},
        ],
        "edges": [
            {"id": "e1", "from_node": "f", "from_port": "out", "to_node": "g", "to_port": "in"},
            {"id": "e2", "from_node": "g", "from_port": "out", "to_node": "r", "to_port": "in"},
        ],
    }).to_string();

    // 5) 校验通过（无 Error）
    {
        let reg = state.registry.read();
        let ext = voice_pipeline_core::validate::ExternalChecks::default();
        let issues = voice_pipeline_core::validate::validate(
            &serde_json::from_str(&graph).unwrap(), &reg, &ext);
        let errs: Vec<_> = issues.iter()
            .filter(|i| i.level == voice_pipeline_core::validate::Severity::Error).collect();
        assert!(errs.is_empty(), "校验错误: {errs:?}");
    }

    // 6) 启动 → 运行 → 停止（走命令层同构路径）
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Arc;
    let bridge = Arc::new(voice_pipeline_core::native::DeviceBridge {
        pull_input: Box::new(|_| 0),
        submit_output: Box::new(|_| {}),
        ptt_active: Box::new(|| true),
    });
    let (tx, _rx) = crossbeam_channel::bounded(1024);
    let g: voice_pipeline_core::graph::PipelineGraph = serde_json::from_str(&graph).unwrap();
    let mut engine = voice_pipeline_core::runtime::ExecutionEngine::new(
        g, bridge, Default::default(), tx);
    {
        let reg = state.registry.read();
        engine.start(&reg).expect("管线启动");
    }
    // 文件源 100ms/块 × 10 块 = ~1s
    std::thread::sleep(std::time::Duration::from_millis(2500));
    let snap = engine.snapshot();
    assert_eq!(snap["state"], "Running");
    engine.stop();

    // 7) 输出 WAV 存在且能量高于输入（+6dB）
    assert!(out_wav.exists(), "录制文件未生成");
    let (out_samples, _, _) = voice_audio_engine::wav::read_mono_48k(&out_wav).unwrap();
    assert!(!out_samples.is_empty(), "输出为空");
    let peak_in = samples.iter().map(|s| s.abs()).fold(0.0f32, f32::max);
    let peak_out = out_samples.iter().map(|s| s.abs()).fold(0.0f32, f32::max);
    assert!(peak_out > peak_in * 1.4, "+6dB 未生效: {peak_in} → {peak_out}");
    println!("[host-it] {peak_in:.3} → {peak_out:.3} (+6dB), {} 样本", out_samples.len());

    // 8) 崩溃标记语义
    voice_diagnostics::mark_clean_exit(&data_dir.join("logs"));
    assert!(!voice_diagnostics::was_abnormal_exit(&data_dir.join("logs")));
    let _ = AtomicBool::new(false);
    let _ = Ordering::Relaxed;
    println!("[host-it] PASS");
}
