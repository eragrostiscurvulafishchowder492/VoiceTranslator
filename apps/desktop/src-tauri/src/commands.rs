//! Tauri IPC 命令：设备/管线/插件/模型/参考音频/资源/热键/测试实验室。
use crate::state::AppState;
use serde_json::json;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use tauri::State;
use voice_pipeline_core::graph::PipelineGraph;
use voice_pipeline_core::native::DeviceBridge;
use voice_pipeline_core::runtime::{ExecutionEngine, PluginBridge};
use voice_pipeline_core::types::{Msg, Payload};
use voice_pipeline_core::validate::{validate, ExternalChecks};

type App<'a> = State<'a, AppState>;

// ================= app / 启动 =================
#[tauri::command]
pub fn app_init(app: App) -> Result<serde_json::Value, String> {
    let abnormal = voice_diagnostics::was_abnormal_exit(&app.paths.logs());
    voice_diagnostics::mark_running(&app.paths.logs());
    app.plugins.discover();
    app.rebuild_registry();
    let gpu = app.resources.snapshot();
    Ok(json!({
        "abnormal_exit": abnormal,
        "gpu": gpu,
        "vb_cable": voice_audio_engine::devices::find_virtual_output().is_some(),
        "plugins": app.plugins.list_status(),
        "last_known_good": app.store.last_known_good(),
    }))
}

#[tauri::command]
pub fn mark_clean_exit(app: App) -> Result<(), String> {
    voice_diagnostics::mark_clean_exit(&app.paths.logs());
    app.store.mark_session("clean").ok();
    Ok(())
}

// ================= 设备 =================
#[tauri::command]
pub fn list_devices() -> Result<Vec<voice_audio_engine::devices::DeviceInfo>, String> {
    Ok(voice_audio_engine::devices::list_devices())
}

#[tauri::command]
pub fn resource_snapshot(app: App) -> Result<serde_json::Value, String> {
    let mut s = serde_json::to_value(app.resources.snapshot()).unwrap_or(json!({}));
    if let Some(o) = s.as_object_mut() {
        o.insert("pipeline_running".into(), json!(app.is_pipeline_running()));
        let (underruns, overflows) = {
            let pb = app.playback.lock();
            let cp = app.capture.lock();
            (pb.as_ref().map(|p| p.underrun_count()).unwrap_or(0),
             cp.as_ref().map(|c| c.overflow_count()).unwrap_or(0))
        };
        o.insert("underruns".into(), json!(underruns));
        o.insert("input_overflows".into(), json!(overflows));
    }
    Ok(s)
}

// ================= 节点注册表 =================
#[tauri::command]
pub fn node_registry(app: App) -> Result<serde_json::Value, String> {
    app.rebuild_registry();
    let reg = app.registry.read();
    Ok(serde_json::to_value(reg.all()).unwrap())
}

// ================= 管线 =================
#[tauri::command]
pub fn list_pipelines(app: App) -> Result<serde_json::Value, String> {
    Ok(serde_json::to_value(app.store.list_pipelines()).unwrap())
}

#[tauri::command]
pub fn save_pipeline(app: App, graph_json: String, name: String, is_default: bool) -> Result<String, String> {
    let g: PipelineGraph = serde_json::from_str(&graph_json).map_err(|e| format!("图格式错误: {e}"))?;
    app.store.save_pipeline(&g.id, &name, &graph_json, is_default)
        .map_err(|e| e.to_string())?;
    app.store.set_last_known_good(&graph_json).ok();
    app.logring.push("INFO", "pipeline", format!("已保存管线 {name}"));
    Ok(g.id)
}

#[tauri::command]
pub fn delete_pipeline(app: App, id: String) -> Result<(), String> {
    app.store.delete_pipeline(&id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn validate_pipeline(app: App, graph_json: String) -> Result<serde_json::Value, String> {
    let g: PipelineGraph = serde_json::from_str(&graph_json).map_err(|e| format!("图格式错误: {e}"))?;
    app.rebuild_registry();
    let reg = app.registry.read();
    let snapshot = app.resources.snapshot();
    let statuses = app.plugins.list_status();
    let ext = ExternalChecks {
        is_plugin_installed: Box::new(move |pid| statuses.iter().any(|s| &s.id == pid && s.enabled)),
        has_model: Box::new(|_mid, _nt| true), // 模型存在性由插件 LoadModel 实测
        total_vram_mb: snapshot.vram_total_mb,
        used_vram_mb: snapshot.vram_used_mb,
    };
    Ok(serde_json::to_value(validate(&g, &reg, &ext)).unwrap())
}

fn ext_checks(app: &AppState) -> ExternalChecks<'_> {
    let snapshot = app.resources.snapshot();
    let statuses = app.plugins.list_status();
    ExternalChecks {
        is_plugin_installed: Box::new(move |pid| statuses.iter().any(|s| &s.id == pid && s.enabled)),
        has_model: Box::new(|_m, _n| true),
        total_vram_mb: snapshot.vram_total_mb,
        used_vram_mb: snapshot.vram_used_mb,
    }
}

#[tauri::command]
pub fn start_pipeline(app: App, graph_json: String) -> Result<serde_json::Value, String> {
    if app.is_pipeline_running() {
        return Err("管线已在运行".into());
    }
    let g: PipelineGraph = serde_json::from_str(&graph_json).map_err(|e| format!("图格式错误: {e}"))?;

    // 1) 自动启动图中引用的插件 worker
    let needed: Vec<String> = g.nodes.iter()
        .filter_map(|n| n.node_type.split('/').next().map(|s| s.to_string()))
        .filter(|id| id.contains('.'))
        .collect();
    for pid in &needed {
        let st = app.plugins.list_status().into_iter().find(|s| &s.id == pid);
        match st {
            Some(s) if s.enabled && s.state != "running" => {
                app.logring.push("INFO", "plugin", format!("自动启动插件 {pid}"));
                if let Err(e) = app.plugins.start_plugin(pid) {
                    return Err(format!("插件 {pid} 启动失败: {e}"));
                }
            }
            Some(_) => {}
            None => return Err(format!("管线引用的插件未安装: {pid}")),
        }
    }
    app.rebuild_registry();

    // 2) 校验（Error 级阻断）
    {
        let reg = app.registry.read();
        let issues = validate(&g, &reg, &ext_checks(&app));
        let errs: Vec<&str> = issues.iter()
            .filter(|i| i.level == voice_pipeline_core::validate::Severity::Error)
            .map(|i| i.message.as_str()).collect();
        if !errs.is_empty() {
            return Err(format!("校验失败: {}", errs.join("; ")));
        }
    }

    // 3) 音频设备（mic 节点 + 输出节点参数决定）
    let mic_node = g.nodes.iter().find(|n| n.node_type == "audio.microphone");
    let out_node = g.nodes.iter().find(|n|
        n.node_type.ends_with("speaker_output") || n.node_type.ends_with("virtual_output"));
    let mic_key = mic_node.and_then(|n| n.params.get("device")).and_then(|v| v.as_str()).unwrap_or("").to_string();
    let out_key = out_node.and_then(|n| n.params.get("device")).and_then(|v| v.as_str()).unwrap_or("").to_string();

    if let Some(n) = mic_node {
        let key = if mic_key.is_empty() {
            voice_audio_engine::devices::list_devices().into_iter()
                .find(|d| d.default_input).map(|d| d.key).unwrap_or_default()
        } else { mic_key.clone() };
        let gain = n.params.get("gain_db").and_then(|v| v.as_f64()).unwrap_or(0.0) as f32;
        let gate = n.params.get("gate_db").and_then(|v| v.as_f64()).unwrap_or(-50.0) as f32;
        let c = voice_audio_engine::AudioCapture::start(&key, gain, gate)
            .map_err(|e| format!("麦克风打开失败: {e}"))?;
        *app.capture.lock() = Some(c);
    }

    if out_node.is_some() {
        let key = if out_key.is_empty() {
            voice_audio_engine::devices::find_virtual_output().map(|d| d.key)
                .or_else(|| voice_audio_engine::devices::list_devices().into_iter()
                    .find(|d| d.default_output).map(|d| d.key)).unwrap_or_default()
        } else { out_key.clone() };
        let p = voice_audio_engine::PlaybackWorker::start(&key, None, 0.0)
            .map_err(|e| format!("输出设备打开失败: {e}"))?;
        *app.playback.lock() = Some(p);
    }

    // 4) 设备桥
    let cap = app.capture.clone();
    let pb = app.playback.clone();
    let ptt = app.ptt_active.clone();
    let bridge = Arc::new(DeviceBridge {
        pull_input: Box::new(move |buf| {
            let g = cap.lock();
            g.as_ref().map(|c| c.ring.pop(buf)).unwrap_or(0)
        }),
        submit_output: Box::new(move |chunk| {
            let mut g = pb.lock();
            if let Some(p) = g.as_mut() { p.submit(chunk); }
        }),
        ptt_active: Box::new(move || ptt.load(Ordering::Relaxed)),
    });

    // 5) 插件桥 + 引擎启动
    let mut bridges: std::collections::HashMap<String, Arc<dyn PluginBridge>> = std::collections::HashMap::new();
    for pid in &needed {
        if let Some(b) = app.plugins.ensure_bridge(pid) {
            bridges.insert(pid.clone(), b);
        }
    }
    let mut engine = ExecutionEngine::new(g, bridge, bridges, app.engine_events.clone());
    {
        let reg = app.registry.read();
        engine.start(&reg).map_err(|e| e.to_string())?;
    }
    *app.engine.lock() = Some(engine);
    app.store.mark_session("running").ok();
    Ok(json!({"ok": true}))
}

#[tauri::command]
pub fn stop_pipeline(app: App) -> Result<(), String> {
    {
        let mut g = app.engine.lock();
        if let Some(e) = g.as_mut() { e.stop(); }
        *g = None;
    }
    {
        let mut c = app.capture.lock();
        if let Some(x) = c.as_mut() { x.stop(); }
        *c = None;
    }
    {
        let mut p = app.playback.lock();
        if let Some(x) = p.as_mut() { x.stop(); }
        *p = None;
    }
    app.logring.push("INFO", "pipeline", "管线已停止");
    Ok(())
}

#[tauri::command]
pub fn pipeline_snapshot(app: App) -> Result<serde_json::Value, String> {
    let g = app.engine.lock();
    Ok(g.as_ref().map(|e| e.snapshot()).unwrap_or(json!({"state": "Stopped", "running": false})))
}

#[tauri::command]
pub fn pipeline_control(app: App, signal: String) -> Result<(), String> {
    match signal.as_str() {
        "ptt_down" => app.ptt_active.store(true, Ordering::Relaxed),
        "ptt_up" => app.ptt_active.store(false, Ordering::Relaxed),
        "mute_on" => { app.muted.store(true, Ordering::Relaxed);
            let g = app.playback.lock(); if let Some(p) = g.as_ref() { p.set_muted(true); } }
        "mute_off" => { app.muted.store(false, Ordering::Relaxed);
            let g = app.playback.lock(); if let Some(p) = g.as_ref() { p.set_muted(false); } }
        "interrupt" | "clear" => {
            let g = app.engine.lock();
            if let Some(e) = g.as_ref() { e.emit_control(&signal, "{}"); }
        }
        _ => {}
    }
    Ok(())
}

// ================= 插件 =================
#[tauri::command]
pub fn plugin_list(app: App) -> Result<serde_json::Value, String> {
    Ok(serde_json::to_value(app.plugins.list_status()).unwrap())
}

#[tauri::command]
pub fn plugin_start(app: App, id: String) -> Result<(), String> {
    app.plugins.start_plugin(&id).map_err(|e| e.to_string())?;
    app.rebuild_registry();
    Ok(())
}

#[tauri::command]
pub fn plugin_stop(app: App, id: String) -> Result<(), String> {
    app.plugins.stop_plugin(&id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn plugin_enable(app: App, id: String, enabled: bool) -> Result<(), String> {
    app.plugins.set_enabled(&id, enabled).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn plugin_install(app: App, zip_path: String) -> Result<String, String> {
    let id = app.plugins.install_zip(std::path::Path::new(&zip_path)).map_err(|e| e.to_string())?;
    app.rebuild_registry();
    Ok(id)
}

#[tauri::command]
pub fn plugin_uninstall(app: App, id: String) -> Result<(), String> {
    app.plugins.uninstall(&id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn plugin_logs(app: App, id: String, last_n: Option<usize>) -> Result<Vec<String>, String> {
    Ok(app.plugins.plugin_logs(&id, last_n.unwrap_or(100)))
}

#[tauri::command]
pub fn logs_recent(app: App, last_n: Option<usize>) -> Result<serde_json::Value, String> {
    Ok(serde_json::to_value(app.logring.snapshot(last_n.unwrap_or(300))).unwrap())
}

// ================= 模型 / 参考音频 =================
#[tauri::command]
pub fn model_list(app: App) -> Result<serde_json::Value, String> {
    Ok(serde_json::to_value(app.store.list_models()).unwrap())
}

#[tauri::command]
pub fn model_upsert(app: App, m: serde_json::Value) -> Result<(), String> {
    let row: voice_persistence::ModelRow = serde_json::from_value(m).map_err(|e| e.to_string())?;
    app.store.upsert_model(&row).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn model_delete(app: App, model_id: String) -> Result<(), String> {
    app.store.delete_model(&model_id).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn reference_list(app: App) -> Result<serde_json::Value, String> {
    Ok(serde_json::to_value(app.store.list_voice_profiles()).unwrap())
}

#[tauri::command]
pub fn reference_save(app: App, p: serde_json::Value) -> Result<(), String> {
    let mut row: voice_persistence::VoiceProfileRow =
        serde_json::from_value(p).map_err(|e| e.to_string())?;
    // 参考音频复制进 app-data/references 统一管理
    let src = std::path::Path::new(&row.ref_path);
    if src.exists() {
        let dst = app.paths.references().join(src.file_name().unwrap_or_default());
        if std::fs::copy(src, &dst).is_ok() {
            row.ref_path = dst.to_string_lossy().into_owned();
        }
    }
    app.store.save_voice_profile(&row).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn reference_delete(app: App, id: String) -> Result<(), String> {
    app.store.delete_voice_profile(&id).map_err(|e| e.to_string())
}

// ================= 设置 =================
#[tauri::command]
pub fn settings_get(app: App) -> Result<serde_json::Value, String> {
    Ok(serde_json::from_str(&app.store.get_setting("ui_settings").unwrap_or_else(|| "{}".into()))
        .unwrap_or(json!({})))
}

#[tauri::command]
pub fn settings_set(app: App, settings: serde_json::Value) -> Result<(), String> {
    app.store.set_setting("ui_settings", &settings.to_string()).map_err(|e| e.to_string())
}

// ================= 测试实验室：Voice A/B（真实 TTS 输出 WAV + TTFA）=================
#[tauri::command]
pub fn test_tts(app: App, text: String, plugin_id: String, instance_id: String) -> Result<serde_json::Value, String> {
    let bridge = app.plugins.ensure_bridge(&plugin_id)
        .ok_or("插件未安装")?;
    let st = app.plugins.list_status().into_iter()
        .find(|s| s.id == plugin_id).ok_or("插件状态未知")?;
    if st.state != "running" {
        app.plugins.start_plugin(&plugin_id).map_err(|e| e.to_string())?;
    }
    let out_dir = app.paths.cache().join("voicelab");
    std::fs::create_dir_all(&out_dir).ok();
    let ts = chrono::Local::now().format("%H%M%S_%3f");
    let wav_path = out_dir.join(format!("tts_{instance_id}_{ts}.wav"));

    // 收集器：路由回调把音频帧累积（rate 固定取首帧）
    struct Collector {
        samples: Vec<f32>,
        rate: u32,
        ttfa_ms: u64,
        started: std::time::Instant,
    }
    let col = Arc::new(parking_lot::Mutex::new(Collector {
        samples: Vec::new(), rate: 0, ttfa_ms: 0,
        started: std::time::Instant::now(),
    }));
    let (done_tx, done_rx) = crossbeam_channel::bounded(1);
    let c2 = col.clone();
    let router: Arc<dyn Fn(&str, &str, Msg) + Send + Sync> = Arc::new(move |_node: &str, _port: &str, msg: Msg| {
        if let Payload::Audio(a) = msg.payload {
            let mut g = c2.lock();
            if g.rate == 0 || !a.samples.is_empty() { g.rate = a.sample_rate; }
            if g.ttfa_ms == 0 && !a.samples.is_empty() {
                g.ttfa_ms = g.started.elapsed().as_millis() as u64;
            }
            let bytes: &[u8] = unsafe { std::slice::from_raw_parts(
                a.samples.as_ptr() as *const u8, a.samples.len() * 4) };
            g.samples.extend(bytes.chunks_exact(4)
                .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]])));
            if a.end_of_utterance {
                let _ = done_tx.send(());
            }
        }
    });
    bridge.set_router(router);
    let msg = Msg {
        from_node: "lab".into(), from_port: "tts".into(),
        ts_ns: voice_common::timeutil::now_ns(),
        payload: Payload::TtsRequest(voice_pipeline_core::types::TtsRequestMsg {
            request_id: format!("lab{ts}"), text: text.clone(), language: "zh".into(),
            voice_profile: "default".into(), style: "calm".into(),
            speed: 1.0, pitch: 1.0, energy: 1.0, priority: 0,
            interrupt_mode: "QUEUE".into(),
        }),
    };
    bridge.send(&instance_id, msg).map_err(|e| format!("发送失败: {e}"))?;
    let t_start = std::time::Instant::now();
    let got_done = done_rx.recv_timeout(std::time::Duration::from_secs(180)).is_ok();
    let (samples, rate, ttfa) = {
        let g = col.lock();
        (g.samples.clone(), if g.rate > 0 { g.rate } else { 24000 }, g.ttfa_ms)
    };
    let dur = samples.len() as f64 / rate as f64;
    voice_audio_engine::wav::write_wav(&wav_path, &samples, rate).ok();
    Ok(json!({
        "wav": wav_path.to_string_lossy(),
        "ttfa_ms": ttfa,
        "total_ms": t_start.elapsed().as_millis() as u64,
        "audio_dur_s": (dur * 100.0).round() / 100.0,
        "complete": got_done,
        "text": text,
    }))
}

#[tauri::command]
pub fn benchmark_recent(app: App) -> Result<serde_json::Value, String> {
    Ok(serde_json::to_value(app.store.recent_events(50)).unwrap())
}

// ================= 崩溃恢复 =================
#[tauri::command]
pub fn recovery_use_last_known(app: App) -> Result<Option<String>, String> {
    Ok(app.store.last_known_good())
}

#[tauri::command]
pub fn recovery_safe_mode(_app: App) -> Result<(), String> {
    // 安全模式：不自动启动任何插件/管线（GUI 只加载编辑器）
    Ok(())
}
