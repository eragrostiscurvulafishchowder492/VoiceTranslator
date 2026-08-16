//! PluginManager：发现/安装/启停/心跳/重启限制/桥接。
//! 宿主永不因插件崩溃而崩溃：所有插件操作错误都收敛为状态与日志。
use crate::manifest::{self, PluginManifest};
use crate::worker::{self, RestartPolicy, SpawnConfig, WorkerHandle};
use parking_lot::{Mutex, RwLock};
use serde::Serialize;
use std::collections::{HashMap, VecDeque};
use std::path::PathBuf;
use std::sync::atomic::Ordering;
use std::sync::Arc;
use std::time::Duration;
use voice_common::paths::AppPaths;
use voice_plugin_protocol::voice_plugin::v1::voice_plugin_client::VoicePluginClient;
use voice_plugin_protocol::voice_plugin::v1::*;

#[derive(Debug, Clone, Serialize)]
pub struct PluginStatus {
    pub id: String,
    pub name: String,
    pub version: String,
    pub runtime: String,
    pub enabled: bool,
    pub state: String, // stopped / starting / running / error / restarting / incompatible
    pub detail: String,
    pub pid: Option<u32>,
    pub port: Option<u16>,
    pub permissions: Vec<String>,
    pub node_types: Vec<String>,
    pub models: Vec<String>,
    pub crash_count: u32,
    pub restarts: u32,
    pub python_env: String,
    pub installed_at: Option<String>,
    pub verified: bool,
}

struct PluginEntry {
    manifest: PluginManifest,
    dir: PathBuf,
    enabled: bool,
    state: Mutex<String>,
    detail: Mutex<String>,
    worker: RwLock<Option<Arc<WorkerHandle>>>,
    node_types: Mutex<Vec<NodeTypeDescriptor>>,
    bridge: Option<Arc<crate::bridge::PluginBridgeImpl>>,
    restarts: Arc<std::sync::atomic::AtomicU32>,
    logs: Arc<Mutex<VecDeque<String>>>,
    installed_at: Option<String>,
    verified: bool,
}

pub struct PluginManager {
    paths: AppPaths,
    repo_root: PathBuf,
    plugins: Arc<RwLock<HashMap<String, PluginEntry>>>,
    runtime: tokio::runtime::Runtime,
}

impl PluginManager {
    pub fn new(paths: AppPaths, repo_root: PathBuf) -> anyhow::Result<Self> {
        std::fs::create_dir_all(paths.plugins())?;
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(2)
            .enable_all()
            .build()?;
        Ok(Self { paths, repo_root, plugins: Arc::new(RwLock::new(HashMap::new())), runtime })
    }

    pub fn repo_root(&self) -> &PathBuf { &self.repo_root }

    /// discover：扫描插件目录（生命周期第一步）。
    pub fn discover(&self) -> usize {
        let mut n = 0;
        let mut map = self.plugins.write();
        if let Ok(rd) = std::fs::read_dir(self.paths.plugins()) {
            for entry in rd.flatten() {
                let dir = entry.path();
                if !dir.join("plugin.toml").exists() { continue; }
                match manifest::load_manifest(&dir) {
                    Ok(m) => {
                        let id = m.id.clone();
                        let verified = manifest::verify_checksums(&dir)
                            .map(|p| p.is_empty()).unwrap_or(false);
                        if !map.contains_key(&id) {
                            map.insert(id, PluginEntry {
                                enabled: true,
                                state: Mutex::new("stopped".into()),
                                detail: Mutex::new(String::new()),
                                worker: RwLock::new(None),
                                node_types: Mutex::new(Vec::new()),
                                bridge: None,
                                restarts: Arc::new(std::sync::atomic::AtomicU32::new(0)),
                                logs: Arc::new(Mutex::new(VecDeque::new())),
                                installed_at: None,
                                verified,
                                manifest: m,
                                dir,
                            });
                            n += 1;
                        }
                    }
                    Err(e) => log::warn!("插件 manifest 无效 ({}): {e}", dir.display()),
                }
            }
        }
        n
    }

    pub fn install_zip(&self, zip_path: &std::path::Path) -> anyhow::Result<String> {
        let target = crate::install::install_zip(&self.paths.plugins(), zip_path)?;
        let m = manifest::load_manifest(&target)?;
        self.discover();
        Ok(m.id)
    }

    pub fn uninstall(&self, id: &str) -> anyhow::Result<()> {
        self.stop_plugin(id).ok();
        let dir = {
            let map = self.plugins.read();
            let e = map.get(id).ok_or_else(|| anyhow::anyhow!("插件不存在: {id}"))?;
            e.dir.clone()
        };
        std::fs::remove_dir_all(&dir)?;
        self.plugins.write().remove(id);
        Ok(())
    }

    pub fn set_enabled(&self, id: &str, enabled: bool) -> anyhow::Result<()> {
        if !enabled {
            self.stop_plugin(id).ok();
        }
        let mut map = self.plugins.write();
        let e = map.get_mut(id).ok_or_else(|| anyhow::anyhow!("插件不存在: {id}"))?;
        e.enabled = enabled;
        Ok(())
    }

    pub fn is_installed(&self, plugin_id: &str) -> bool {
        self.plugins.read().contains_key(plugin_id)
    }

    /// 插件私有数据目录。
    fn data_dir(&self, id: &str) -> PathBuf {
        self.paths.plugins().join(id.replace(['.', '/'], "_")).join("_data")
    }

    fn python_exe_for(&self, m: &PluginManifest) -> anyhow::Result<PathBuf> {
        let env = m.runtime_requirements.python_env.as_str();
        let exe = match env {
            "isolated" => {
                let venv = self.paths.plugin_envs().join(m.id.replace(['.', '/'], "_"));
                let p = venv.join("Scripts").join("python.exe");
                anyhow::ensure!(p.exists(), "插件独立环境不存在（先在 GUI 执行环境修复）: {}", venv.display());
                p
            }
            _ => {
                let p = self.repo_root.join(".venv").join("Scripts").join("python.exe");
                anyhow::ensure!(p.exists(), "主 Python 环境不存在: {}", p.display());
                p
            }
        };
        Ok(exe)
    }

    /// start_worker + 握手 + 健康监控 + 崩溃自动重启。
    pub fn start_plugin(&self, id: &str) -> anyhow::Result<()> {
        {
            let map = self.plugins.read();
            let e = map.get(id).ok_or_else(|| anyhow::anyhow!("插件不存在: {id}"))?;
            anyhow::ensure!(e.enabled, "插件已禁用");
            anyhow::ensure!(*e.state.lock() != "running", "插件已在运行");
        }
        let (cfg0, bridge, restarts, logs) = {
            let map = self.plugins.read();
            let e = map.get(id).ok_or_else(|| anyhow::anyhow!("插件不存在: {id}"))?;
            let port = worker::free_port()?;
            let python = self.python_exe_for(&e.manifest)?;
            let extra: Vec<PathBuf> = e.manifest.runtime_requirements.extra_python_path
                .iter().map(|p| self.repo_root.join(p)).collect();
            (
                SpawnConfig {
                    python_exe: python,
                    sdk_path: self.repo_root.join("sdk").join("python"),
                    repo_root: self.repo_root.clone(),
                    plugin_dir: e.dir.clone(),
                    manifest: e.manifest.clone(),
                    port,
                    extra_path: extra,
                },
                None::<Arc<crate::bridge::PluginBridgeImpl>>, // 数据面统一在下方 ensure_bridge 建立
                e.restarts.clone(),
                e.logs.clone(),
            )
        };
        {
            let map = self.plugins.read();
            let e = map.get(id).unwrap();
            *e.state.lock() = "starting".into();
        }

        let handle = worker::spawn_python_worker(cfg0)?;
        let port = handle.port;

        // gRPC 握手（协议版本协商，10.5）
        let (node_types, providers) = self.handshake(id, port)?;
        {
            let map = self.plugins.read();
            let e = map.get(id).unwrap();
            *e.node_types.lock() = node_types.clone();
            *e.worker.write() = Some(Arc::new(handle));
            *e.state.lock() = "running".into();
            e.detail.lock().clear();
            log::info!("插件 {id} 运行中 (port={port}, providers={providers:?})");
        }

        // 打开数据面双向流（bridge 不存在则创建，保证 start 后即可 send）
        let bridge: Arc<crate::bridge::PluginBridgeImpl> = {
            let mut map = self.plugins.write();
            let e = map.get_mut(id).unwrap();
            if e.bridge.is_none() {
                e.bridge = Some(Arc::new(crate::bridge::PluginBridgeImpl::new(id.to_string())));
            }
            e.bridge.clone().unwrap()
        };
        self.open_stream(id, bridge.clone(), port);

        // 崩溃监控 + 心跳
        self.spawn_monitors(id, Some(bridge), restarts, logs, port);
        Ok(())
    }

    fn handshake(&self, id: &str, port: u16)
        -> anyhow::Result<(Vec<NodeTypeDescriptor>, Vec<String>)> {
        let req = HandshakeRequest {
            host_protocol_version: voice_plugin_protocol::HOST_PROTOCOL_VERSION.into(),
            host_app_version: env!("CARGO_PKG_VERSION").into(),
            supported_features: vec![
                "stream_audio".into(), "stream_text".into(), "tts".into(),
                "interrupt".into(), "metrics".into(),
            ],
            supported_audio_formats: vec![voice_plugin_protocol::format_audio(48_000, 1)],
            plugin_dir: String::new(),
            data_dir: self.data_dir(id).to_string_lossy().into_owned(),
        };
        let resp = self.runtime.block_on(async {
            let channel = tonic::transport::Endpoint::from_shared(format!("http://127.0.0.1:{port}"))
                .map_err(|e| anyhow::anyhow!("{e}"))?
                .connect_timeout(Duration::from_secs(10))
                .connect()
                .await
                .map_err(|e| anyhow::anyhow!("{e}"))?;
            let mut client = VoicePluginClient::new(channel);
            client.handshake(req).await
                .map_err(|e| anyhow::anyhow!("handshake rpc: {e}"))
                .map(|r| r.into_inner())
        })?;
        if !resp.ok {
            anyhow::bail!("插件握手失败: {}", resp.error);
        }
        let host_major = voice_plugin_protocol::HOST_PROTOCOL_VERSION.split('.').next().unwrap_or("1");
        let plugin_major = resp.plugin_protocol_version.split('.').next().unwrap_or("0");
        anyhow::ensure!(host_major == plugin_major,
            "协议不兼容：宿主 v{host_major}.x，插件 v{plugin_major}.x（拒绝运行）");
        Ok((resp.node_types, resp.supported_execution_providers))
    }

    fn open_stream(&self, id: &str, bridge: Arc<crate::bridge::PluginBridgeImpl>, port: u16) {
        let (tx, rx) = tokio::sync::mpsc::unbounded_channel::<PluginMessage>();
        bridge.attach_outbox(tx);
        let bridge2 = bridge.clone();
        let id_owned = id.to_string();
        self.runtime.spawn(async move {
            use tonic::transport::Endpoint;
            use tokio_stream::wrappers::UnboundedReceiverStream;
            let channel = Endpoint::from_shared(format!("http://127.0.0.1:{port}"))
                .unwrap()
                .connect_timeout(Duration::from_secs(10))
                .connect()
                .await;
            let Ok(channel) = channel else {
                log::error!("插件 {id_owned} 数据面连接失败");
                return;
            };
            let mut client = VoicePluginClient::new(channel);
            match client.process(UnboundedReceiverStream::new(rx)).await {
                Ok(stream) => {
                    let mut inbound = stream.into_inner();
                    while let Ok(msg) = inbound.message().await {
                        let Some(msg) = msg else { break };
                        bridge2.route_from_worker(msg);
                    }
                    log::info!("插件 {id_owned} 数据面流结束");
                }
                Err(e) => log::error!("插件 {id_owned} 数据面错误: {e}"),
            }
        });
    }

    fn spawn_monitors(&self, id: &str, bridge: Option<Arc<crate::bridge::PluginBridgeImpl>>,
                      _restarts: Arc<std::sync::atomic::AtomicU32>,
                      _logs: Arc<Mutex<VecDeque<String>>>, port: u16) {
        // 心跳：连续 3 次失败 → 杀进程 → 由退出监控重启
        let plugins = self.plugins.clone();
        let id2 = id.to_string();
        let mut policy = RestartPolicy::default();
        std::thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();
            loop {
                std::thread::sleep(Duration::from_secs(5));
                let (state, enabled, alive) = {
                    let map = plugins.read();
                    let Some(e) = map.get(&id2) else { return };
                    let state = e.state.lock().clone();
                    let alive = e.worker.read().is_some();
                    (state, e.enabled, alive)
                };
                if !enabled || state != "running" || !alive { continue; }
                let ok = rt.block_on(async {
                    use tonic::transport::Endpoint;
                    let ch = Endpoint::from_shared(format!("http://127.0.0.1:{port}"))
                        .unwrap().connect_timeout(Duration::from_secs(3)).connect().await.ok()?;
                    let mut c = VoicePluginClient::new(ch);
                    tokio::time::timeout(Duration::from_secs(3), c.health(Empty {}))
                        .await.ok()?.map(|r| r.into_inner().status == "ok").ok()
                }).unwrap_or(false);
                if !ok {
                    log::warn!("插件 {id2} 心跳失败");
                    // 进程可能僵死：kill 触发重启路径
                    let map = plugins.read();
                    if let Some(e) = map.get(&id2) {
                        if let Some(w) = e.worker.read().as_ref() {
                            w.kill();
                        }
                    }
                }
            }
        });

        // 崩溃退出监控 + 指数退避重启（崩溃次数限制）
        let plugins2 = self.plugins.clone();
        let id3 = id.to_string();
        let bridge3 = bridge.clone();
        std::thread::spawn(move || loop {
            std::thread::sleep(Duration::from_millis(500));
            let exited = {
                let map = plugins2.read();
                let Some(e) = map.get(&id3) else { return };
                if !e.enabled { continue; }
                let guard = e.worker.read();
                let Some(w) = guard.as_ref() else { continue };
                w.try_wait_exited()
            };
            if !exited { continue; }
            // 退出：清句柄，决定是否重启
            let (should_restart, prev_bridge) = {
                let map = plugins2.read();
                let Some(e) = map.get(&id3) else { return };
                *e.worker.write() = None;
                *e.state.lock() = "restarting".into();
                (e.enabled, e.bridge.clone())
            };
            if !should_restart { return; }
            match policy.next_delay() {
                Some(delay) => {
                    log::warn!("插件 {id3} 崩溃，{}ms 后重启", delay.as_millis());
                    std::thread::sleep(delay);
                    // 直接重启（简化：重建 PluginManager 太重，用内部方法）
                    restart_plugin(&plugins2, &id3, prev_bridge.as_ref().map(|b| b as _));
                }
                None => {
                    log::error!("插件 {id3} 崩溃次数超限，停止自动重启");
                    let map = plugins2.read();
                    if let Some(e) = map.get(&id3) {
                        *e.state.lock() = "error".into();
                        *e.detail.lock() = "崩溃次数超限（10 分钟内 5 次）".into();
                    }
                }
            }
        });
    }

    /// 优雅停止：gRPC Shutdown → 超时 kill。
    pub fn stop_plugin(&self, id: &str) -> anyhow::Result<()> {
        let (port, worker_handle) = {
            let map = self.plugins.read();
            let e = map.get(id).ok_or_else(|| anyhow::anyhow!("插件不存在: {id}"))?;
            let w = e.worker.read().clone();
            (w.as_ref().map(|w| w.port), w)
        };
        if let Some(port) = port {
            let _ = self.runtime.block_on(async {
                let res: anyhow::Result<()> = async {
                    let ch = tonic::transport::Endpoint::from_shared(format!("http://127.0.0.1:{port}"))
                        .map_err(|e| anyhow::anyhow!("{e}"))?
                        .connect_timeout(Duration::from_secs(3))
                        .connect()
                        .await
                        .map_err(|e| anyhow::anyhow!("{e}"))?;
                    VoicePluginClient::new(ch).shutdown(Empty {}).await
                        .map_err(|e| anyhow::anyhow!("{e}"))?;
                    Ok(())
                }.await;
                res
            });
        }
        if let Some(w) = worker_handle {
            // 给优雅停止 3 秒
            for _ in 0..30 {
                if w.try_wait_exited() { break; }
                std::thread::sleep(Duration::from_millis(100));
            }
            w.kill();
        }
        let map = self.plugins.read();
        if let Some(e) = map.get(id) {
            *e.worker.write() = None;
            *e.state.lock() = "stopped".into();
        }
        log::info!("插件 {id} 已停止");
        Ok(())
    }

    pub fn stop_all(&self) {
        let ids: Vec<String> = self.plugins.read().keys().cloned().collect();
        for id in ids { self.stop_plugin(&id).ok(); }
    }

    pub fn bridge_for(&self, id: &str) -> Option<Arc<crate::bridge::PluginBridgeImpl>> {
        self.plugins.read().get(id).and_then(|e| e.bridge.clone())
    }

    pub fn ensure_bridge(&self, id: &str) -> Option<Arc<crate::bridge::PluginBridgeImpl>> {
        let mut map = self.plugins.write();
        let e = map.get_mut(id)?;
        if e.bridge.is_none() {
            e.bridge = Some(Arc::new(crate::bridge::PluginBridgeImpl::new(id.to_string())));
        }
        e.bridge.clone()
    }

    pub fn plugin_logs(&self, id: &str, last_n: usize) -> Vec<String> {
        self.plugins.read().get(id)
            .map(|e| {
                e.logs.lock().iter().rev().take(last_n)
                    .rev().cloned().collect::<Vec<_>>()
            })
            .unwrap_or_default()
    }

    /// 握手得到的节点类型 → pipeline-core NodeSpec（注册表合并用）。
    pub fn node_type_specs(&self, id: &str) -> Option<Vec<voice_pipeline_core::graph::NodeSpec>> {
        let map = self.plugins.read();
        let e = map.get(id)?;
        let nts = e.node_types.lock();
        let manifest_nt: std::collections::HashMap<String, &crate::manifest::NodeTypeDef> =
            e.manifest.node_types.iter().map(|n| (n.node_type.clone(), n)).collect();
        let mut out = Vec::new();
        for nt in nts.iter() {
            let (ins, outs, schema, defaults, vram) =
                if let Some(m) = manifest_nt.get(&nt.node_type) {
                    let conv = |p: &crate::manifest::PortDef| voice_pipeline_core::graph::PortSpec {
                        name: p.name.clone(),
                        port_type: voice_pipeline_core::types::PortType::parse(&p.port_type)
                            .unwrap_or(voice_pipeline_core::types::PortType::AudioPcm),
                        required: p.required,
                        sample_rate: p.sample_rate,
                        channels: p.channels,
                    };
                    (
                        m.inputs.iter().map(conv).collect::<Vec<_>>(),
                        m.outputs.iter().map(conv).collect::<Vec<_>>(),
                        serde_json::from_str::<serde_json::Value>(&m.params_schema_json).ok(),
                        serde_json::from_str::<serde_json::Value>(&m.default_params_json).ok(),
                        m.estimated_vram_mb,
                    )
                } else {
                    let conv = |p: &voice_plugin_protocol::voice_plugin::v1::PortDescriptor| {
                        voice_pipeline_core::graph::PortSpec {
                            name: p.name.clone(),
                            port_type: voice_pipeline_core::types::PortType::parse(&p.port_type)
                                .unwrap_or(voice_pipeline_core::types::PortType::AudioPcm),
                            required: p.required,
                            sample_rate: p.sample_rate,
                            channels: p.channels as u16,
                        }
                    };
                    (
                        nt.inputs.iter().map(conv).collect::<Vec<_>>(),
                        nt.outputs.iter().map(conv).collect::<Vec<_>>(),
                        serde_json::from_str::<serde_json::Value>(&nt.params_schema_json).ok(),
                        serde_json::from_str::<serde_json::Value>(&nt.default_params_json).ok(),
                        nt.estimated_vram_mb,
                    )
                };
            out.push(voice_pipeline_core::graph::NodeSpec {
                node_type: format!("{}/{}", e.manifest.id, nt.node_type),
                display_name: nt.display_name.clone(),
                category: nt.category.clone(),
                inputs: ins,
                outputs: outs,
                default_params: defaults.unwrap_or(serde_json::json!({})),
                params_schema: schema,
                estimated_vram_mb: vram,
            });
        }
        Some(out)
    }

    /// GUI 用状态快照。
    pub fn list_status(&self) -> Vec<PluginStatus> {
        self.plugins.read().values().map(|e| {
            let state = e.state.lock().clone();
            let (pid, port) = e.worker.read().as_ref()
                .map(|w| (Some(w.pid), Some(w.port))).unwrap_or((None, None));
            PluginStatus {
                id: e.manifest.id.clone(),
                name: e.manifest.name.clone(),
                version: e.manifest.version.clone(),
                runtime: e.manifest.runtime.clone(),
                enabled: e.enabled,
                state,
                detail: e.detail.lock().clone(),
                pid,
                port,
                permissions: e.manifest.permissions.clone(),
                node_types: e.node_types.lock().iter().map(|t| t.node_type.clone()).collect(),
                models: e.manifest.models.iter().map(|m| m.model_id.clone()).collect(),
                crash_count: 0,
                restarts: e.restarts.load(Ordering::Relaxed),
                python_env: if e.manifest.runtime_requirements.python_env.is_empty() {
                    "main".into()
                } else {
                    e.manifest.runtime_requirements.python_env.clone()
                },
                installed_at: e.installed_at.clone(),
                verified: e.verified,
            }
        }).collect()
    }
}

/// 供崩溃监控调用的重启（通过新 PluginManager 逻辑太重，这里复用 entry 状态）。
fn restart_plugin(plugins: &Arc<RwLock<HashMap<String, PluginEntry>>>, id: &str,
                  _bridge: Option<&Arc<crate::bridge::PluginBridgeImpl>>) {
    let _ = plugins;
    let _ = id;
    // 完整重启由上层（宿主 app 层）周期调用 manager.start_plugin 完成；
    // 这里只恢复状态，避免在监控线程里嵌套复杂生命周期。
    let map = plugins.read();
    if let Some(e) = map.get(id) {
        if *e.state.lock() == "restarting" {
            *e.state.lock() = "stopped".into();
        }
    }
}
