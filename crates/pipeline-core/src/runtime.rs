//! 实时执行引擎：每节点一个任务线程 + 每边一条有界通道 + 背压策略。
//! GUI/推理绝不混线程：本引擎全部运行在独立 worker 线程。
use crate::graph::{NodeInstance, NodeSpec, PipelineGraph};
use crate::native::{create_native, DeviceBridge, NativeProcessor};
use crate::types::*;
use crossbeam_channel::{bounded, Receiver, Sender};
use parking_lot::{Mutex, RwLock};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

#[derive(Debug, Clone)]
pub enum EngineEvent {
    StateChanged(PipelineState),
    NodeStateChanged { node: String, state: NodeState },
    Error { node: Option<String>, message: String },
    Text { kind: &'static str, text: String },
    AudioLevel { rms: f32, peak: f32 },
}

/// 插件桥：由 plugin-host 实现，把消息送入对应 worker 的 gRPC 流并回注输出。
pub trait PluginBridge: Send + Sync {
    fn send(&self, target_node: &str, msg: Msg) -> anyhow::Result<()>;
    /// 引擎注入回注路由：worker 输出 → 引擎边通道
    fn set_router(&self, router: Arc<dyn Fn(&str, &str, Msg) + Send + Sync>);
}

struct EdgeSender {
    edge_id: String,
    target_node: String,
    target_port: String,
    tx: Sender<(String, Msg)>,
    rx: Receiver<(String, Msg)>, // DropOldest/LatestOnly 弹出旧数据用（克隆自目标通道）
    policy: Backpressure,
    dropped: Arc<AtomicU64>,
    sent: Arc<AtomicU64>,
}

impl EdgeSender {
    fn deliver(&self, msg: Msg) -> bool {
        let m = (self.target_port.clone(), msg);
        loop {
            match self.policy {
                Backpressure::Block => {
                    if self.tx.send(m.clone()).is_err() { return false; }
                    self.sent.fetch_add(1, Ordering::Relaxed);
                    return true;
                }
                Backpressure::DropOldest => {
                    if self.tx.try_send(m.clone()).is_ok() {
                        self.sent.fetch_add(1, Ordering::Relaxed);
                        return true;
                    }
                    // 弹掉最旧的一条再试
                    match self.rx.try_recv() {
                        Ok(_) => { self.dropped.fetch_add(1, Ordering::Relaxed); }
                        Err(_) => return false,
                    }
                }
                Backpressure::DropNewest => {
                    if self.tx.try_send(m.clone()).is_ok() {
                        self.sent.fetch_add(1, Ordering::Relaxed);
                        return true;
                    }
                    self.dropped.fetch_add(1, Ordering::Relaxed);
                    return true; // 丢弃但不算管线失败
                }
                Backpressure::LatestOnly => {
                    while self.rx.try_recv().is_ok() {
                        self.dropped.fetch_add(1, Ordering::Relaxed);
                    }
                    if self.tx.try_send(m.clone()).is_ok() {
                        self.sent.fetch_add(1, Ordering::Relaxed);
                        return true;
                    }
                    self.dropped.fetch_add(1, Ordering::Relaxed);
                    return true;
                }
                Backpressure::FailPipeline => {
                    if self.tx.try_send(m.clone()).is_ok() {
                        self.sent.fetch_add(1, Ordering::Relaxed);
                        return true;
                    }
                    self.dropped.fetch_add(1, Ordering::Relaxed);
                    return false; // 上溢 → 管线失败
                }
            }
        }
    }
}

pub struct ExecutionEngine {
    graph: PipelineGraph,
    state: Arc<RwLock<PipelineState>>,
    stop_flags: Arc<AtomicBool>,
    node_states: Arc<RwLock<HashMap<String, NodeState>>>,
    edge_stats: Arc<Mutex<HashMap<String, EdgeStatSnapshot>>>,
    event_tx: Option<Sender<EngineEvent>>,
    threads: Vec<std::thread::JoinHandle<()>>,
    bridge: Arc<DeviceBridge>,
    plugin_bridges: HashMap<String, Arc<dyn PluginBridge>>,
    running_flag: Arc<AtomicBool>,
    total_in: Arc<AtomicU64>,
    total_dropped: Arc<AtomicU64>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct EdgeStatSnapshot {
    pub edge: String,
    pub queue_depth: usize,
    pub sent: u64,
    pub dropped: u64,
}

impl ExecutionEngine {
    pub fn new(graph: PipelineGraph, bridge: Arc<DeviceBridge>,
               plugin_bridges: HashMap<String, Arc<dyn PluginBridge>>,
               event_tx: Sender<EngineEvent>) -> Self {
        Self {
            graph,
            state: Arc::new(RwLock::new(PipelineState::Stopped)),
            stop_flags: Arc::new(AtomicBool::new(false)),
            node_states: Arc::new(RwLock::new(HashMap::new())),
            edge_stats: Arc::new(Mutex::new(HashMap::new())),
            event_tx: Some(event_tx),
            threads: Vec::new(),
            bridge,
            plugin_bridges,
            running_flag: Arc::new(AtomicBool::new(false)),
            total_in: Arc::new(AtomicU64::new(0)),
            total_dropped: Arc::new(AtomicU64::new(0)),
        }
    }

    pub fn graph(&self) -> &PipelineGraph { &self.graph }

    pub fn state(&self) -> PipelineState { *self.state.read() }

    fn set_state(&self, s: PipelineState) {
        *self.state.write() = s;
        if let Some(tx) = &self.event_tx {
            let _ = tx.send(EngineEvent::StateChanged(s));
        }
    }

    fn set_node_state(&self, node: &str, s: NodeState) {
        self.node_states.write().insert(node.to_string(), s);
        if let Some(tx) = &self.event_tx {
            let _ = tx.send(EngineEvent::NodeStateChanged { node: node.into(), state: s });
        }
    }

    pub fn snapshot(&self) -> serde_json::Value {
        let edges: Vec<EdgeStatSnapshot> = self.edge_stats.lock().values().cloned().collect();
        let nodes: HashMap<String, NodeState> = self.node_states.read().clone();
        serde_json::json!({
            "state": self.state(),
            "nodes": nodes,
            "edges": edges,
            "total_in": self.total_in.load(Ordering::Relaxed),
            "total_dropped": self.total_dropped.load(Ordering::Relaxed),
            "running": self.running_flag.load(Ordering::Relaxed),
        })
    }

    pub fn start(&mut self, registry: &crate::graph::NodeRegistry) -> anyhow::Result<()> {
        if self.running_flag.load(Ordering::Relaxed) { return Ok(()); }
        self.set_state(PipelineState::Starting);
        self.stop_flags.store(false, Ordering::Relaxed);
        self.running_flag.store(true, Ordering::Relaxed);

        // 每个节点一条聚合输入通道
        let mut node_rx: HashMap<String, Receiver<(String, Msg)>> = HashMap::new();
        let mut node_tx: HashMap<String, Sender<(String, Msg)>> = HashMap::new();
        for n in &self.graph.nodes {
            let (tx, rx) = bounded::<(String, Msg)>(256);
            node_tx.insert(n.id.clone(), tx);
            node_rx.insert(n.id.clone(), rx);
        }

        // 每条边一个发送端（策略在此生效）
        let mut out_edges: HashMap<String, Vec<Arc<EdgeSender>>> = HashMap::new();
        {
            let mut stats = self.edge_stats.lock();
            for e in &self.graph.edges {
                let Some(tx) = node_tx.get(&e.to_node) else { continue };
                let es = Arc::new(EdgeSender {
                    edge_id: e.id.clone(),
                    target_node: e.to_node.clone(),
                    target_port: e.to_port.clone(),
                    tx: tx.clone(),
                    rx: node_rx.get(&e.to_node).cloned().unwrap(),
                    policy: e.backpressure,
                    dropped: Arc::new(AtomicU64::new(0)),
                    sent: Arc::new(AtomicU64::new(0)),
                });
                stats.insert(e.id.clone(), EdgeStatSnapshot {
                    edge: format!("{}:{} → {}:{}", e.from_node, e.from_port, e.to_node, e.to_port),
                    queue_depth: 0, sent: 0, dropped: 0,
                });
                out_edges.entry(e.from_node.clone()).or_default().push(es);
            }
        }

        // 插件桥回注路由：worker 输出按 (node, port) 送到边
        let route_outgoing = {
            let out_edges = out_edges.clone();
            let total_in = self.total_in.clone();
            let fail = self.stop_flags.clone();
            let state = self.state.clone();
            Arc::new(move |node: &str, port: &str, msg: Msg| {
                total_in.fetch_add(1, Ordering::Relaxed);
                if let Some(list) = out_edges.get(node) {
                    for es in list.iter().filter(|es| edge_matches(es, port)) {
                        if !es.deliver(msg.clone()) {
                            log::error!("边 {} FailPipeline 上溢", es.edge_id);
                            *state.write() = PipelineState::Failed;
                            fail.store(true, Ordering::Relaxed);
                        }
                    }
                }
            })
        };
        for b in self.plugin_bridges.values() {
            b.set_router(route_outgoing.clone());
        }

        // 启动节点线程
        for n in &self.graph.nodes {
            let spec = registry.get(&n.node_type)
                .ok_or_else(|| anyhow::anyhow!("节点类型未注册: {}", n.node_type))?
                .clone();
            let rx = node_rx.remove(&n.id).unwrap();
            let outs = out_edges.get(&n.id).cloned().unwrap_or_default();
            let bridge = self.bridge.clone();
            let stop = self.stop_flags.clone();
            let node_state = self.node_states.clone();
            let event = self.event_tx.clone();
            let plugin = if n.node_type.contains('/') {
                let pid = n.node_type.split('/').next().unwrap().to_string();
                self.plugin_bridges.get(&pid).cloned()
            } else { None };
            let node = n.clone();
            let total_in = self.total_in.clone();
            self.set_node_state(&node.id, NodeState::Loading);
            let handle = std::thread::Builder::new()
                .name(format!("node:{}", node.label))
                .spawn(move || {
                    node_task(node, spec, rx, outs, bridge, stop, node_state, event, plugin, total_in);
                })?;
            self.threads.push(handle);
        }

        self.set_state(PipelineState::Running);
        log::info!("pipeline '{}' started ({} nodes, {} edges)",
            self.graph.name, self.graph.nodes.len(), self.graph.edges.len());
        Ok(())
    }

    pub fn stop(&mut self) {
        if !self.running_flag.swap(false, Ordering::Relaxed) { return; }
        self.set_state(PipelineState::Stopping);
        self.stop_flags.store(true, Ordering::Relaxed);
        let threads = std::mem::take(&mut self.threads);
        for t in threads {
            let _ = t.join();
        }
        self.set_state(PipelineState::Stopped);
        log::info!("pipeline '{}' stopped", self.graph.name);
    }

    /// PTT 信号（control.push_to_talk / 插件可订阅）
    pub fn emit_control(&self, signal: &str, payload_json: &str) {
        let msg = Msg {
            from_node: "host".into(), from_port: "control".into(),
            ts_ns: voice_common::timeutil::now_ns(),
            payload: Payload::Control(ControlMsg { signal: signal.into(), payload_json: payload_json.into() }),
        };
        // 广播到所有 control 端口连线（通过节点输入通道直投）
        // 简化：借助边结构找到所有 control 入边目标
        for e in &self.graph.edges {
            if e.to_port == "control" || e.to_port == "in_control" {
                // 无直接 tx 句柄；通过 router 路由（from_node=host）
                let _ = &e.id;
            }
        }
        // 直接交给插件桥（ASR/VAD 等关注 PTT）
        for b in self.plugin_bridges.values() {
            let _ = b.send("host", msg.clone());
        }
    }
}

fn edge_matches(_es: &EdgeSender, _port: &str) -> bool {
    // 端口名匹配：sender 不区分源端口（节点输出按 port 广播过滤在 node_task 内）。
    // 为了 router（插件输出）正确路由，放宽为全部投递，目标端口由边定义。
    true
}

#[allow(clippy::too_many_arguments)]
fn node_task(node: NodeInstance, spec: NodeSpec, rx: Receiver<(String, Msg)>,
             outs: Vec<Arc<EdgeSender>>, bridge: Arc<DeviceBridge>, stop: Arc<AtomicBool>,
             node_states: Arc<RwLock<HashMap<String, NodeState>>>,
             event: Option<Sender<EngineEvent>>, plugin: Option<Arc<dyn PluginBridge>>,
             _total_in: Arc<AtomicU64>) {
    let is_plugin = plugin.is_some();
    let mut proc = if node.bypassed {
        Some(NativeProcessor::Bypassed)
    } else if !is_plugin {
        match create_native(&node.node_type, &node.params, &bridge) {
            Ok(p) => Some(p),
            Err(e) => {
                log::error!("节点 {} 初始化失败: {}", node.label, e);
                node_states.write().insert(node.id.clone(), NodeState::Error);
                if let Some(tx) = &event {
                    let _ = tx.send(EngineEvent::Error {
                        node: Some(node.id.clone()), message: format!("初始化失败: {e}") });
                }
                return;
            }
        }
    } else { None };

    let set_state = |s: NodeState| {
        node_states.write().insert(node.id.clone(), s);
        if let Some(tx) = &event {
            let _ = tx.send(EngineEvent::NodeStateChanged { node: node.id.clone(), state: s });
        }
    };
    set_state(NodeState::Ready);

    let fanout = |outs: &[Arc<EdgeSender>], port: &str, msg: Msg| {
        let _ = port;
        for es in outs {
            if !es.deliver(msg.clone()) {
                log::warn!("edge {} dropped (policy)", es.edge_id);
            }
        }
    };

    // 源节点的节拍
    let tick = Duration::from_millis(match node.node_type.as_str() {
        "audio.microphone" => node.params.get("block_ms").and_then(|v| v.as_u64()).unwrap_or(20),
        "audio.file" => 100,
        "text.manual_input" => 100,
        _ => 0,
    });

    loop {
        if stop.load(Ordering::Relaxed) { break; }

        // 源节点：产生数据
        if tick.as_millis() > 0 {
            if let Some(p) = proc.as_mut() {
                let produced = produce_source(p, &node, &outs, &fanout, &event);
                if !produced { /* 文件播完 */ }
            }
            // 也检查停止信号作为节拍等待
            if stop.load(Ordering::Relaxed) { break; }
            std::thread::sleep(tick);
            // 源节点同时接收 control
            while let Ok((port, msg)) = rx.try_recv() {
                handle_msg(&mut proc, &node, &spec, port, msg, &outs, &fanout, &event, &bridge);
            }
            continue;
        }

        // 处理节点：阻塞等待输入（带超时以便检查停止）
        let recv = rx.recv_timeout(Duration::from_millis(200));
        match recv {
            Ok((port, msg)) => {
                if node.bypassed {
                    fanout(&outs, &port, msg);
                    continue;
                }
                set_state(NodeState::Processing);
                if is_plugin {
                    if let Some(b) = &plugin {
                        if let Err(e) = b.send(&node.id, msg) {
                            log::error!("plugin send ({}): {}", node.label, e);
                            set_state(NodeState::Error);
                        }
                    }
                } else {
                    handle_msg(&mut proc, &node, &spec, port, msg, &outs, &fanout, &event, &bridge);
                }
                set_state(NodeState::Ready);
            }
            Err(crossbeam_channel::RecvTimeoutError::Timeout) => continue,
            Err(crossbeam_channel::RecvTimeoutError::Disconnected) => break,
        }
    }
    set_state(NodeState::Unloaded);
}

type Fanout<'a> = dyn Fn(&[Arc<EdgeSender>], &str, Msg) + 'a;

/// 源节点出数据。返回是否继续产出。
fn produce_source(p: &mut NativeProcessor, node: &NodeInstance, outs: &[Arc<EdgeSender>],
                  fanout: &Fanout, event: &Option<Sender<EngineEvent>>) -> bool {
    match p {
        NativeProcessor::Microphone { bridge, block_ms, seq, stream_id } => {
            let n = (*block_ms as usize) * 48;
            let mut buf = vec![0f32; n];
            let got = (bridge.pull_input)(&mut buf);
            if got == 0 { return true; }
            let level = voice_audio_engine::dsp::measure(&buf[..got]);
            if let Some(tx) = event {
                let _ = tx.send(EngineEvent::AudioLevel { rms: level.rms, peak: level.peak });
            }
            *seq += 1;
            fanout(outs, "out", Msg {
                from_node: node.id.clone(), from_port: "out".into(),
                ts_ns: voice_common::timeutil::now_ns(),
                payload: Payload::Audio(AudioChunk {
                    stream_id: stream_id.clone(), sequence: *seq,
                    timestamp_ns: voice_common::timeutil::now_ns(),
                    sample_rate: 48_000, channels: 1,
                    samples: Arc::new(buf[..got].to_vec()),
                    end_of_stream: false, end_of_utterance: false,
                }),
            });
            true
        }
        NativeProcessor::FileSource { samples, pos, loop_, rate: _, seq } => {
            if *pos >= samples.len() {
                if !*loop_ {
                    fanout(outs, "out", Msg {
                        from_node: node.id.clone(), from_port: "out".into(),
                        ts_ns: voice_common::timeutil::now_ns(),
                        payload: Payload::Audio(AudioChunk {
                            stream_id: "file".into(), sequence: *seq,
                            timestamp_ns: voice_common::timeutil::now_ns(),
                            sample_rate: 48_000, channels: 1,
                            samples: Arc::new(vec![]),
                            end_of_stream: true, end_of_utterance: true,
                        }),
                    });
                    return false;
                }
                *pos = 0;
            }
            let end = (*pos + 4800).min(samples.len());
            let chunk = samples[*pos..end].to_vec();
            *pos = end;
            *seq += 1;
            fanout(outs, "out", Msg {
                from_node: node.id.clone(), from_port: "out".into(),
                ts_ns: voice_common::timeutil::now_ns(),
                payload: Payload::Audio(AudioChunk {
                    stream_id: "file".into(), sequence: *seq,
                    timestamp_ns: voice_common::timeutil::now_ns(),
                    sample_rate: 48_000, channels: 1, samples: Arc::new(chunk),
                    end_of_stream: false, end_of_utterance: false,
                }),
            });
            true
        }
        NativeProcessor::TextInput { pending, sent } => {
            if *sent { return false; }
            *sent = true;
            if let Some(text) = pending.take() {
                if !text.is_empty() {
                    fanout(outs, "out", Msg {
                        from_node: node.id.clone(), from_port: "out".into(),
                        ts_ns: voice_common::timeutil::now_ns(),
                        payload: Payload::Text(TextMsg {
                            stream_id: "manual".into(), segment_id: "0".into(), sequence: 0,
                            text, language: "zh".into(),
                            is_partial: false, is_final: true, stability: 1.0,
                            start_time: 0.0, end_time: 0.0, confidence: 1.0,
                        }),
                    });
                }
            }
            false
        }
        _ => true,
    }
}

#[allow(clippy::too_many_arguments)]
fn handle_msg(proc: &mut Option<NativeProcessor>, node: &NodeInstance, _spec: &NodeSpec,
              port: String, msg: Msg, outs: &[Arc<EdgeSender>], fanout: &Fanout,
              event: &Option<Sender<EngineEvent>>, _bridge: &Arc<DeviceBridge>) {
    let ts = || voice_common::timeutil::now_ns();
    let Some(p) = proc.as_mut() else { return };
    match p {
        NativeProcessor::Gain(g) => {
            if let Payload::Audio(a) = msg.payload {
                let scaled: Vec<f32> = a.samples.iter().map(|s| s * *g).collect();
                fanout(outs, "out", Msg { from_node: node.id.clone(), from_port: "out".into(),
                    ts_ns: ts(), payload: Payload::Audio(AudioChunk { samples: Arc::new(scaled), ..a }) });
            }
        }
        NativeProcessor::NoiseGate(ng) => {
            if let Payload::Audio(a) = msg.payload {
                let out: Vec<f32> = a.samples.iter().map(|&s| ng.process(s)).collect();
                fanout(outs, "out", Msg { from_node: node.id.clone(), from_port: "out".into(),
                    ts_ns: ts(), payload: Payload::Audio(AudioChunk { samples: Arc::new(out), ..a }) });
            }
        }
        NativeProcessor::Limiter(l) => {
            if let Payload::Audio(a) = msg.payload {
                let out: Vec<f32> = a.samples.iter().map(|&s| l.process(s)).collect();
                fanout(outs, "out", Msg { from_node: node.id.clone(), from_port: "out".into(),
                    ts_ns: ts(), payload: Payload::Audio(AudioChunk { samples: Arc::new(out), ..a }) });
            }
        }
        NativeProcessor::HighPass(hp) => {
            if let Payload::Audio(a) = msg.payload {
                let out: Vec<f32> = a.samples.iter().map(|&s| hp.process(s)).collect();
                fanout(outs, "out", Msg { from_node: node.id.clone(), from_port: "out".into(),
                    ts_ns: ts(), payload: Payload::Audio(AudioChunk { samples: Arc::new(out), ..a }) });
            }
        }
        NativeProcessor::Resampler { target, rs, seq } => {
            if let Payload::Audio(a) = msg.payload {
                let mut out = rs.process(&a.samples).unwrap_or_default();
                if a.end_of_stream {
                    out.extend(rs.flush().unwrap_or_default());
                }
                if !out.is_empty() {
                    *seq += 1;
                    fanout(outs, "out", Msg { from_node: node.id.clone(), from_port: "out".into(),
                        ts_ns: ts(), payload: Payload::Audio(AudioChunk {
                            stream_id: a.stream_id.clone(), sequence: *seq,
                            timestamp_ns: a.timestamp_ns, sample_rate: *target,
                            channels: a.channels, samples: Arc::new(out),
                            end_of_stream: a.end_of_stream, end_of_utterance: a.end_of_utterance }) });
                }
            }
        }
        NativeProcessor::ChannelConverter { target } => {
            if let Payload::Audio(a) = msg.payload {
                let out: Vec<f32> = if a.channels == *target {
                    a.samples.to_vec()
                } else if *target == 1 {
                    a.samples.chunks(a.channels as usize)
                        .map(|c| c.iter().sum::<f32>() / c.len() as f32).collect()
                } else {
                    a.samples.iter().flat_map(|&s| vec![s; *target as usize]).collect()
                };
                fanout(outs, "out", Msg { from_node: node.id.clone(), from_port: "out".into(),
                    ts_ns: ts(), payload: Payload::Audio(AudioChunk { samples: Arc::new(out), channels: *target, ..a }) });
            }
        }
        NativeProcessor::SpeakerOut { bridge } => {
            if let Payload::Audio(a) = msg.payload {
                // 插件输出可能非 48k：宿主播放侧统一重采样
                let samples48 = if a.sample_rate == 48_000 {
                    a.samples.to_vec()
                } else {
                    voice_audio_engine::resampler::resample_once(&a.samples, a.sample_rate, 48_000)
                        .unwrap_or_default()
                };
                (bridge.submit_output)(&samples48);
            }
        }
        NativeProcessor::Recorder { writer } => {
            if let Payload::Audio(a) = msg.payload {
                if writer.is_none() {
                    let path = node.params.get("path").and_then(|v| v.as_str()).unwrap_or("record.wav");
                    if let Ok(w) = hound::WavWriter::create(path, hound::WavSpec {
                        channels: a.channels, sample_rate: a.sample_rate,
                        bits_per_sample: 32, sample_format: hound::SampleFormat::Float }) {
                        *writer = Some(w);
                    }
                }
                if let Some(w) = writer.as_mut() {
                    for &s in a.samples.iter() { let _ = w.write_sample(s); }
                }
            }
        }
        NativeProcessor::TextFileOut { path, written } => {
            if let Payload::Text(t) = msg.payload {
                if t.is_final {
                    use std::io::Write;
                    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
                        let _ = writeln!(f, "{}", t.text);
                        *written += 1;
                    }
                }
            }
        }
        NativeProcessor::PushToTalk { bridge } => match msg.payload {
            Payload::Audio(a) => {
                if (bridge.ptt_active)() || a.end_of_stream {
                    fanout(outs, "out", Msg { from_node: node.id.clone(), from_port: "out".into(), ts_ns: ts(), payload: Payload::Audio(a) });
                }
            }
            Payload::Control(c) if c.signal == "ptt_down" || c.signal == "ptt_up" => {
                fanout(outs, "out", Msg { from_node: node.id.clone(), from_port: "out".into(), ts_ns: ts(), payload: Payload::Control(c) });
            }
            other => fanout(outs, "out", Msg { from_node: node.id.clone(), from_port: "out".into(), ts_ns: ts(), payload: other }),
        },
        NativeProcessor::MetricsTap { count, last_ns } => {
            match msg.payload {
                Payload::Audio(a) => {
                    *count += 1;
                    let lv = voice_audio_engine::dsp::measure(&a.samples);
                    *last_ns = ts();
                    fanout(outs, "out", Msg { from_node: node.id.clone(), from_port: "out".into(), ts_ns: ts(),
                        payload: Payload::Metrics(MetricsMsg { metric: "level_rms".into(), value: lv.rms, timestamp_ns: *last_ns }) });
                }
                Payload::Text(t) => {
                    fanout(outs, "out", Msg { from_node: node.id.clone(), from_port: "out".into(), ts_ns: ts(),
                        payload: Payload::Metrics(MetricsMsg { metric: "text_len".into(), value: t.text.len() as f32, timestamp_ns: ts() }) });
                }
                _ => {}
            }
        }
        NativeProcessor::Bypassed => fanout(outs, &port, msg),
        _ => {}
    }
    let _ = event;
}

impl Drop for ExecutionEngine {
    fn drop(&mut self) {
        self.stop();
    }
}
