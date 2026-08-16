//! 宿主状态：路径、DB、插件管理器、资源、节点注册表、管线引擎、音频设备桥。
use crossbeam_channel::Sender;
use parking_lot::{Mutex, RwLock};
use std::path::PathBuf;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;
use voice_audio_engine::{AudioCapture, PlaybackWorker};
use voice_diagnostics::LogRing;
use voice_persistence::{open as open_db, Store};
use voice_pipeline_core::graph::NodeRegistry;
use voice_pipeline_core::runtime::{EngineEvent, ExecutionEngine};
use voice_plugin_host::PluginManager;
use voice_resource_manager::ResourceManager;

pub struct AppState {
    pub repo_root: PathBuf,
    pub paths: voice_common::AppPaths,
    pub store: Store,
    pub plugins: PluginManager,
    pub resources: ResourceManager,
    pub logring: Arc<LogRing>,
    pub registry: RwLock<NodeRegistry>,
    pub engine: Arc<Mutex<Option<ExecutionEngine>>>,
    pub capture: Arc<Mutex<Option<AudioCapture>>>,
    pub playback: Arc<Mutex<Option<PlaybackWorker>>>,
    pub engine_events: Sender<EngineEvent>,
    pub ptt_active: Arc<AtomicBool>,
    pub muted: Arc<AtomicBool>,
}

impl AppState {
    pub fn new(repo_root: PathBuf) -> anyhow::Result<Self> {
        let paths = voice_common::AppPaths::default();
        paths.ensure_all()?;
        let store = open_db(&paths.db_file())?;
        let plugins = PluginManager::new(paths.clone(), repo_root.clone())?;
        let resources = ResourceManager::new();
        let (tx, rx) = crossbeam_channel::bounded(4096);
        // 引擎事件 → 日志环（GUI 通过 logs_recent / pipeline-event 读取）
        let logring = Arc::new(LogRing::new(4000));
        let lr = logring.clone();
        std::thread::spawn(move || {
            for ev in rx {
                match &ev {
                    EngineEvent::StateChanged(s) => lr.push("INFO", "pipeline", format!("状态: {s:?}")),
                    EngineEvent::NodeStateChanged { node, state } =>
                        lr.push("INFO", "pipeline", format!("节点 {node}: {state:?}")),
                    EngineEvent::Error { node, message } =>
                        lr.push("ERROR", "pipeline", format!("错误 {node:?}: {message}")),
                    EngineEvent::Text { kind, text } =>
                        lr.push("INFO", "text", format!("[{kind}] {text}")),
                    EngineEvent::AudioLevel { rms, peak } =>
                        lr.push("DEBUG", "audio", format!("level rms={rms:.3} peak={peak:.3}")),
                }
            }
        });
        let mut registry = voice_pipeline_core::native::builtin_registry();
        Ok(Self {
            repo_root,
            paths,
            store,
            plugins,
            resources,
            logring,
            registry: RwLock::new(std::mem::take(&mut registry)),
            engine: Arc::new(Mutex::new(None)),
            capture: Arc::new(Mutex::new(None)),
            playback: Arc::new(Mutex::new(None)),
            engine_events: tx,
            ptt_active: Arc::new(AtomicBool::new(true)),
            muted: Arc::new(AtomicBool::new(false)),
        })
    }

    /// 内置 + 已运行插件的节点类型合并注册表。
    pub fn rebuild_registry(&self) {
        let mut reg = voice_pipeline_core::native::builtin_registry();
        for st in self.plugins.list_status() {
            if st.state != "running" { continue; }
            // 从 plugin-host 获取握手后的 node_types
            if let Some(specs) = self.plugins.node_type_specs(&st.id) {
                for spec in specs { reg.register(spec); }
            }
        }
        *self.registry.write() = reg;
    }

    pub fn is_pipeline_running(&self) -> bool {
        self.engine.lock().as_ref().map(|e| e.state() == voice_pipeline_core::types::PipelineState::Running
            || e.state() == voice_pipeline_core::types::PipelineState::Starting).unwrap_or(false)
    }
}
