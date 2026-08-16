//! Voice Studio 宿主（Tauri 2）。
pub mod commands;
pub mod presets;
pub mod state;

use state::AppState;
use tauri::{Emitter, Manager};

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // 仓库根：从可执行文件向上找（dev: target/debug；打包: 安装目录旁）
    let repo_root = voice_common::paths::default_root()
        .parent().map(|p| p.to_path_buf()).unwrap_or_else(|| std::path::PathBuf::from("."));

    let state = AppState::new(repo_root).expect("宿主状态初始化失败");
    presets::ensure_installed(&state.store);

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().with_handler(|app, shortcut, event| {
            if event.state == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                let id = format!("{shortcut}");
                let st = app.state::<AppState>();
                let signal = match id.as_str() {
                    k if k.contains("F8") => Some("ptt"),
                    k if k.contains("F9") => Some("mute"),
                    k if k.contains("F10") => Some("clear"),
                    k if k.contains("F11") => Some("interrupt"),
                    _ => None,
                };
                match signal {
                    Some("ptt") => { let _ = commands::pipeline_control(st, "ptt_down".into()); }
                    Some("mute") => {
                        let on = st.muted.load(std::sync::atomic::Ordering::Relaxed);
                        let _ = commands::pipeline_control(st, if on { "mute_off".into() } else { "mute_on".into() });
                    }
                    Some(s) => { let _ = commands::pipeline_control(st, s.into()); }
                    None => {}
                }
                // PTT 松开处理
                let _ = &id;
            } else {
                // Released
                let st = app.state::<AppState>();
                let id = format!("{shortcut}");
                if id.contains("F8") {
                    let _ = commands::pipeline_control(st, "ptt_up".into());
                }
            }
        }).build())
        .manage(state)
        .invoke_handler(tauri::generate_handler![
            commands::app_init,
            commands::mark_clean_exit,
            commands::get_startup_page,
            commands::list_devices,
            commands::resource_snapshot,
            commands::node_registry,
            commands::list_pipelines,
            commands::save_pipeline,
            commands::delete_pipeline,
            commands::validate_pipeline,
            commands::start_pipeline,
            commands::stop_pipeline,
            commands::pipeline_snapshot,
            commands::pipeline_control,
            commands::plugin_list,
            commands::plugin_prepare_env,
            commands::plugin_env_status,
            commands::plugin_start,
            commands::plugin_stop,
            commands::plugin_enable,
            commands::plugin_install,
            commands::plugin_uninstall,
            commands::plugin_logs,
            commands::logs_recent,
            commands::model_list,
            commands::model_upsert,
            commands::model_delete,
            commands::reference_list,
            commands::reference_save,
            commands::reference_delete,
            commands::settings_get,
            commands::settings_set,
            commands::test_tts,
            commands::benchmark_recent,
            commands::recovery_use_last_known,
            commands::recovery_safe_mode,
        ])
        .setup(|app| {
            // 注册默认热键 F8~F11（可在设置中改）
            use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut};
            let gs = app.app_handle().global_shortcut();
            for key in ["F8", "F9", "F10", "F11"] {
                if let Ok(sc) = Shortcut::try_from(key) {
                    let _ = gs.register(sc);
                }
            }
            // 设备热插拔轮询：5s
            let handle = app.app_handle().clone();
            std::thread::spawn(move || {
                let mut prev: Vec<String> = voice_audio_engine::devices::list_devices()
                    .into_iter().map(|d| d.key).collect();
                loop {
                    std::thread::sleep(std::time::Duration::from_secs(5));
                    let (added, removed) = voice_audio_engine::devices::diff_devices(&prev);
                    prev = voice_audio_engine::devices::list_devices().into_iter().map(|d| d.key).collect();
                    if !added.is_empty() || !removed.is_empty() {
                        for d in added {
                            let _ = handle.emit("devices-changed", serde_json::json!({"event": "added", "device": d}));
                        }
                        for k in removed {
                            let _ = handle.emit("devices-changed", serde_json::json!({"event": "removed", "key": k}));
                            // 运行中的管线若依赖该设备 → 停止并提示（不崩溃）
                            let st = handle.state::<AppState>();
                            let using = {
                                let c = st.capture.lock();
                                let p = st.playback.lock();
                                c.as_ref().map(|x| x.device_key == k).unwrap_or(false)
                                    || p.as_ref().map(|x| x.device_key == k).unwrap_or(false)
                            };
                            if using && st.is_pipeline_running() {
                                let _ = commands::stop_pipeline(st);
                                let _ = handle.emit("pipeline-event", serde_json::json!({
                                    "kind": "error", "message": format!("音频设备已拔出（{k}），管线已停止")}));
                            }
                        }
                    }
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(app) = window.app_handle().try_state::<AppState>() {
                    let paths = app.paths.clone();
                    app.plugins.stop_all();
                    let _ = commands::stop_pipeline(app);
                    voice_diagnostics::mark_clean_exit(&paths.logs());
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("Voice Studio 启动失败");
    let _ = app;
}
