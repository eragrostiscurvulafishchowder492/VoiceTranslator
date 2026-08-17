//! 桌面命令层 E2E（真实插件 worker）：
//! text.manual_input → textkit.to_tts(插件节点) → 收集 tts.request 输出。
//! 验证 start_pipeline 的完整语义：插件自动启动 / Configure 下发（__node_type__ 路由）/
//! 桥接双向流 / 引擎调度 / 停止。
//! 需 .venv（无则跳过）。
use std::sync::Arc;
use voice_pipeline_core::graph::{Edge, NodeInstance, PipelineGraph};
use voice_pipeline_core::native::DeviceBridge;
use voice_pipeline_core::runtime::{ExecutionEngine, PluginBridge as _};
use voice_pipeline_core::types::{Msg, Payload};

fn repo_root() -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf()
}

fn have_venv() -> bool {
    repo_root()
        .join(".venv")
        .join("Scripts")
        .join("python.exe")
        .exists()
}

fn n(id: &str, ty: &str, label: &str, params: serde_json::Value) -> NodeInstance {
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

#[test]
#[serial_test::serial]
fn plugin_node_pipeline_e2e_text_to_tts_request() {
    if !have_venv() {
        eprintln!("跳过：无 .venv");
        return;
    }
    let state = voice_studio_desktop_lib::state::AppState::new(repo_root()).unwrap();
    state.plugins.discover();

    // 图：text.manual_input → textkit.to_tts → (collect)
    let mut g = PipelineGraph::new("e2e-tts");
    g.nodes.push(n(
        "t",
        "text.manual_input",
        "文本输入",
        serde_json::json!({"text": "你们先过去，我拿一下东西，马上回来。"}),
    ));
    g.nodes.push(n(
        "tt",
        "org.voicestudio.textkit/textkit.to_tts",
        "→TTS请求",
        serde_json::json!({"voice_profile": "default", "speed": 1.0}),
    ));
    g.edges.push(Edge {
        id: "e1".into(),
        from_node: "t".into(),
        from_port: "out".into(),
        to_node: "tt".into(),
        to_port: "in".into(),
        backpressure: Default::default(),
        capacity: 8,
    });

    // —— start_pipeline 的核心语义（同构复制，因 tauri::State 无法在测试构造）——
    state
        .plugins
        .start_plugin("org.voicestudio.textkit")
        .expect("textkit 自动启动");
    for node in &g.nodes {
        if node.node_type.contains('/') {
            let (pid, short) = node.node_type.split_once('/').unwrap();
            let params = serde_json::to_string(&node.params).unwrap();
            state
                .plugins
                .configure_node(pid, short, &node.id, &params)
                .expect("Configure 下发");
        }
    }
    state.rebuild_registry();

    let (tx, rx) = crossbeam_channel::bounded::<Msg>(64);
    let tx2 = tx.clone();
    let bridge = state
        .plugins
        .ensure_bridge("org.voicestudio.textkit")
        .unwrap();

    let (ev_tx, _ev_rx) = crossbeam_channel::bounded(1024);
    let mut bridges = std::collections::HashMap::new();
    bridges.insert(
        "org.voicestudio.textkit".to_string(),
        bridge.clone() as Arc<dyn voice_pipeline_core::runtime::PluginBridge>,
    );
    let dev_bridge = Arc::new(DeviceBridge {
        pull_input: Box::new(|_| 0),
        submit_output: Box::new(|_| {}),
        ptt_active: Box::new(|| true),
    });
    let mut engine = ExecutionEngine::new(g, dev_bridge, bridges, ev_tx);
    {
        let reg = state.registry.read();
        engine.start(&reg).expect("引擎启动");
    }
    // 引擎 start 会安装自己的路由；测试在其后接管以收集 worker 输出
    bridge.set_router(Arc::new(move |_node: &str, _port: &str, m: Msg| {
        let _ = tx2.send(m);
    }));

    // textkit 处理后应发回 tts.request
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(30);
    let mut got_request: Option<voice_pipeline_core::types::TtsRequestMsg> = None;
    while std::time::Instant::now() < deadline {
        if let Ok(m) = rx.recv_timeout(std::time::Duration::from_millis(500)) {
            if let Payload::TtsRequest(r) = m.payload {
                got_request = Some(r);
                break;
            }
        }
    }
    engine.stop();
    state.plugins.stop_all();

    let req = got_request.expect("30s 内未收到 tts.request（Configure/路由/桥接失败）");
    assert_eq!(req.text, "你们先过去，我拿一下东西，马上回来。");
    assert_eq!(req.voice_profile, "default");
    println!("[desktop-e2e] tts.request 正确：{:?}", req.text);
    println!("[desktop-e2e] PASS：插件节点经 Configure+桥接+引擎调度全链路");
}
