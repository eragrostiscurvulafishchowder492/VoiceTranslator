//! 插件桥：pipeline-core 消息 ⇄ gRPC PluginMessage 转换与路由。
use parking_lot::RwLock;
use std::sync::Arc;
use voice_pipeline_core::runtime::PluginOutputRouter;
use voice_pipeline_core::types::*;
use voice_plugin_protocol::voice_plugin::v1 as pb;

pub struct PluginBridgeImpl {
    pub plugin_id: String,
    /// 宿主 → worker（tokio mpsc，由 manager.open_stream 挂载）
    outbox: RwLock<Option<tokio::sync::mpsc::UnboundedSender<pb::PluginMessage>>>,
    /// worker → 引擎边通道
    router: RwLock<Option<Arc<PluginOutputRouter>>>,
    seq: std::sync::atomic::AtomicU64,
}

impl PluginBridgeImpl {
    pub fn new(plugin_id: String) -> Self {
        Self {
            plugin_id,
            outbox: RwLock::new(None),
            router: RwLock::new(None),
            seq: std::sync::atomic::AtomicU64::new(0),
        }
    }

    pub fn attach_outbox(&self, tx: tokio::sync::mpsc::UnboundedSender<pb::PluginMessage>) {
        *self.outbox.write() = Some(tx);
    }

    /// worker 输出 → 引擎路由。
    pub fn route_from_worker(&self, msg: pb::PluginMessage) {
        let Some(router) = self.router.read().clone() else {
            return;
        };
        let node = msg.source_node.clone();
        let port = msg.source_port.clone();
        if let Some(m) = pb_to_msg(&msg) {
            router(&node, &port, m);
        }
    }
}

impl voice_pipeline_core::runtime::PluginBridge for PluginBridgeImpl {
    fn send(&self, target_node: &str, msg: Msg) -> anyhow::Result<()> {
        let outbox = self.outbox.read();
        let Some(tx) = outbox.as_ref() else {
            anyhow::bail!("插件 {} 数据面未打开", self.plugin_id);
        };
        let pbmsg = msg_to_pb(
            target_node,
            msg,
            self.seq.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
        );
        tx.send(pbmsg)
            .map_err(|_| anyhow::anyhow!("插件 {} 流已关闭", self.plugin_id))?;
        Ok(())
    }

    fn set_router(&self, router: Arc<PluginOutputRouter>) {
        *self.router.write() = Some(router);
    }
}

fn msg_to_pb(target: &str, m: Msg, seq: u64) -> pb::PluginMessage {
    let _ = seq;
    let body = match m.payload {
        Payload::Audio(a) => pb::plugin_message::Body::Audio(pb::AudioFrame {
            stream_id: a.stream_id,
            sequence: a.sequence,
            timestamp_ns: a.timestamp_ns,
            sample_rate: a.sample_rate,
            channels: a.channels as u32,
            sample_format: "f32le".into(),
            frame_count: a.samples.len() as u32,
            payload: bytemuck::cast_slice(&a.samples).to_vec(),
            end_of_stream: a.end_of_stream,
            end_of_utterance: a.end_of_utterance,
            target_instance: target.into(),
        }),
        Payload::Text(t) => pb::plugin_message::Body::Text(pb::TextEvent {
            stream_id: t.stream_id,
            segment_id: t.segment_id,
            sequence: t.sequence,
            text: t.text,
            language: t.language,
            is_partial: t.is_partial,
            is_final: t.is_final,
            stability: t.stability,
            start_time: t.start_time,
            end_time: t.end_time,
            confidence: t.confidence,
            target_instance: target.into(),
        }),
        Payload::TtsRequest(r) => pb::plugin_message::Body::Tts(pb::TtsRequest {
            request_id: r.request_id,
            text: r.text,
            language: r.language,
            voice_profile: r.voice_profile,
            style: r.style,
            speed: r.speed,
            pitch: r.pitch,
            energy: r.energy,
            priority: r.priority,
            interrupt_mode: r.interrupt_mode,
            target_instance: target.into(),
        }),
        Payload::Control(c) => pb::plugin_message::Body::Control(pb::ControlSignal {
            signal: c.signal,
            payload_json: c.payload_json,
            target_instance: target.into(),
        }),
        Payload::Metrics(mm) => pb::plugin_message::Body::Metric(pb::MetricsSample {
            node_type: String::new(),
            instance_id: target.into(),
            metric: mm.metric,
            value: mm.value,
            timestamp_ns: mm.timestamp_ns,
        }),
    };
    pb::PluginMessage {
        protocol_version: "1.0".into(),
        schema_version: 1,
        source_node: m.from_node,
        source_port: m.from_port,
        target_node: target.into(),
        target_port: String::new(),
        body: Some(body),
    }
}

fn pb_to_msg(m: &pb::PluginMessage) -> Option<Msg> {
    let body = m.body.as_ref()?;
    let payload = match body {
        pb::plugin_message::Body::Audio(a) => Payload::Audio(AudioChunk {
            stream_id: a.stream_id.clone(),
            sequence: a.sequence,
            timestamp_ns: a.timestamp_ns,
            sample_rate: a.sample_rate,
            channels: a.channels as u16,
            samples: Arc::new(bytemuck::cast_slice(&a.payload).to_vec()),
            end_of_stream: a.end_of_stream,
            end_of_utterance: a.end_of_utterance,
        }),
        pb::plugin_message::Body::Text(t) => Payload::Text(TextMsg {
            stream_id: t.stream_id.clone(),
            segment_id: t.segment_id.clone(),
            sequence: t.sequence,
            text: t.text.clone(),
            language: t.language.clone(),
            is_partial: t.is_partial,
            is_final: t.is_final,
            stability: t.stability,
            start_time: t.start_time,
            end_time: t.end_time,
            confidence: t.confidence,
        }),
        pb::plugin_message::Body::Tts(r) => Payload::TtsRequest(TtsRequestMsg {
            request_id: r.request_id.clone(),
            text: r.text.clone(),
            language: r.language.clone(),
            voice_profile: r.voice_profile.clone(),
            style: r.style.clone(),
            speed: r.speed,
            pitch: r.pitch,
            energy: r.energy,
            priority: r.priority,
            interrupt_mode: r.interrupt_mode.clone(),
        }),
        pb::plugin_message::Body::Control(c) => Payload::Control(ControlMsg {
            signal: c.signal.clone(),
            payload_json: c.payload_json.clone(),
        }),
        pb::plugin_message::Body::Metric(mm) => Payload::Metrics(MetricsMsg {
            metric: mm.metric.clone(),
            value: mm.value,
            timestamp_ns: mm.timestamp_ns,
        }),
    };
    Some(Msg {
        from_node: m.source_node.clone(),
        from_port: m.source_port.clone(),
        ts_ns: voice_common::timeutil::now_ns(),
        payload,
    })
}
