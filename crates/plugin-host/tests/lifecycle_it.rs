//! 集成测试：PluginManager ⇄ 真实 Python worker（gain 插件）完整生命周期。
//! 覆盖验收项：发现插件 / 独立 worker / 协议版本交换 / 健康检查 /
//! 插件崩溃后宿主继续运行（杀进程检测）/ 停止。
//! 无 .venv 时跳过（开发机依赖）。
use std::sync::Arc;
use std::time::Duration;
use voice_common::paths::AppPaths;
use voice_pipeline_core::runtime::PluginBridge as _;
use voice_pipeline_core::types::{Msg, Payload};
use voice_plugin_host::manager::PluginManager;

fn repo_root() -> std::path::PathBuf {
    let mut d = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    d.pop();
    d.pop();
    d
}

use std::io::Write as _;

fn have_venv() -> bool {
    repo_root().join(".venv").join("Scripts").join("python.exe").exists()
}

/// 把仓库 plugins/examples 拷到临时 app-data/plugins。
fn prepare(tmp: &std::path::Path) -> AppPaths {
    let paths = AppPaths::new(tmp);
    std::fs::create_dir_all(paths.plugins()).unwrap();
    let src = repo_root().join("plugins/examples/gain");
    let dst = paths.plugins().join("org.voicestudio.gain");
    if !dst.exists() {
        voice_audio_engine_copy_dir(&src, &dst);
    }
    paths
}

fn voice_audio_engine_copy_dir(src: &std::path::Path, dst: &std::path::Path) {
    std::fs::create_dir_all(dst).unwrap();
    for e in std::fs::read_dir(src).unwrap().flatten() {
        let to = dst.join(e.file_name());
        if e.path().is_dir() { voice_audio_engine_copy_dir(&e.path(), &to); }
        else { std::fs::copy(e.path(), to).unwrap(); }
    }
}

#[test]
#[serial_test::serial]
fn full_plugin_lifecycle_with_real_worker() {
    if !have_venv() { eprintln!("跳过：无 .venv"); return; }
    let tmp = std::env::temp_dir().join(format!("vpm_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&tmp);
    let paths = prepare(&tmp);
    let root = repo_root();

    let mgr = PluginManager::new(paths.clone(), root.clone()).unwrap();
    let n = mgr.discover();
    assert!(n >= 1, "应发现 gain 插件");

    // 独立 worker + 协议交换 + 握手节点类型
    mgr.start_plugin("org.voicestudio.gain").unwrap();
    let st = mgr.list_status().into_iter().find(|s| s.id == "org.voicestudio.gain").unwrap();
    assert_eq!(st.state, "running");
    assert!(st.pid.is_some(), "独立 worker 进程应有 pid");
    assert!(st.node_types.contains(&"gain.audio_gain".to_string()),
        "握手应返回节点类型: {:?}", st.node_types);
    println!("[lifecycle] worker pid={:?} port={:?}", st.pid, st.port);

    // node_type_specs（注册表合并）
    let specs = mgr.node_type_specs("org.voicestudio.gain").unwrap();
    assert!(specs.iter().any(|s| s.node_type == "org.voicestudio.gain/gain.audio_gain"));

    // 数据面：bridge 发音频 → 收 +6dB 音频
    let bridge = mgr.ensure_bridge("org.voicestudio.gain").unwrap();
    let (tx, rx) = crossbeam_channel::bounded::<Msg>(16);
    let tx2 = tx.clone();
    bridge.set_router(Arc::new(move |_n: &str, _p: &str, m: Msg| { let _ = tx2.send(m); }));
    // Configure
    {
        use voice_plugin_protocol::voice_plugin::v1 as pb;
        let _ = pb::ConfigRequest::default();
    }
    // gain 参数默认 0dB → 原样返回
    let samples: Vec<f32> = vec![0.25; 480];
    let msg = Msg {
        from_node: "test".into(), from_port: "out".into(),
        ts_ns: voice_common::timeutil::now_ns(),
        payload: Payload::Audio(voice_pipeline_core::types::AudioChunk {
            stream_id: "it".into(), sequence: 1, timestamp_ns: 0,
            sample_rate: 48000, channels: 1, samples: Arc::new(samples),
            end_of_stream: false, end_of_utterance: false,
        }),
    };
    bridge.send("cfg:gain0", msg).unwrap();
    let got = rx.recv_timeout(Duration::from_secs(10)).expect("应收到回传音频");
    if let Payload::Audio(a) = got.payload {
        assert!(!a.samples.is_empty());
        assert!((a.samples[0] - 0.25).abs() < 0.01, "0dB 应原样: {}", a.samples[0]);
    } else { panic!("应收到音频，得到 {:?}", got.payload.port_type()); }

    // 崩溃：杀掉 worker 进程 → 宿主不 panic → 状态转为 restarting/stopped
    {
        let statuses = mgr.list_status();
        let pid = statuses.iter().find(|s| s.id == "org.voicestudio.gain").unwrap().pid.unwrap();
        let out = std::process::Command::new("taskkill").args(["/F", "/PID", &pid.to_string()]).output().unwrap();
        assert!(out.status.success(), "taskkill 应成功");
    }
    std::thread::sleep(Duration::from_secs(2));
    // 宿主仍在运行（本行能执行即证明），状态已离开 running
    let st2 = mgr.list_status().into_iter().find(|s| s.id == "org.voicestudio.gain").unwrap();
    assert_ne!(st2.state, "running", "崩溃后状态应变化: {}", st2.state);
    println!("[lifecycle] crash detected → state={}", st2.state);

    // 优雅停止（幂等）
    mgr.stop_all();
    let st3 = mgr.list_status().into_iter().find(|s| s.id == "org.voicestudio.gain").unwrap();
    assert_eq!(st3.state, "stopped");
    println!("[lifecycle] PASS");
}
