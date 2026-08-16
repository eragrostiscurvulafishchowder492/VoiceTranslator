# Voice Plugin Protocol v1

宿主（Rust）与插件 worker（Python 等）之间的唯一通信协议。
定义文件：`proto/voice_plugin_v1.proto`（Rust: tonic/prost 生成于
`crates/plugin-protocol`；Python: grpcio-tools 生成于 `sdk/python/voice_plugin_sdk/_gen`）。

## 传输

- 控制面：gRPC（localhost TCP，宿主为客户端）
- 数据面：`rpc Process(stream PluginMessage) returns (stream PluginMessage)` 双向流
- 所有消息携带 `protocol_version` + `schema_version`

## 生命周期（10.4）

```
discover → validate → install → prepare_runtime → start_worker → handshake
→ load → ready → process → interrupt/unload → shutdown
```

| 步骤 | RPC / 机制 |
|---|---|
| start_worker | 宿主 spawn：`python -m voice_plugin_sdk.server --manifest-dir <dir> --port <port>` |
| handshake | `Handshake(HandshakeRequest)` → `HandshakeResponse` |
| 配置节点 | `Configure(ConfigRequest{node_type, instance_id, params_json})` |
| 加载模型 | `LoadModel` → `{ok, error, load_ms, vram_mb}` |
| 数据处理 | `Process` 双向流 |
| 心跳 | `Health(Empty)`，宿主每 5s；3 次失败 kill → 重启 |
| 中断 | `Interrupt(instance_id)` |
| 停止 | `Shutdown` → 0.3s 后 worker 自行 `os._exit(0)`；宿主兜底 kill |

## 版本协商（10.5）

握手交换 `host_protocol_version` 与 `plugin_protocol_version`。
**主版本不一致即拒绝运行**（宿主显示原因，不崩溃）。当前 HOST_PROTOCOL_VERSION = "1.0"。

交换的能力：

```text
supported_features        stream_audio / stream_text / tts / interrupt / metrics
supported_audio_formats   pcm_f32le@48000:1、@16000:1、@24000:1
supported_execution_providers  cpu / cuda
```

## 消息信封

```protobuf
message PluginMessage {
  string protocol_version = 1;
  uint32 schema_version = 2;
  string source_node, source_port, target_node, target_port;
  oneof body { AudioFrame audio; TextEvent text; TtsRequest tts;
               ControlSignal control; MetricsSample metric; }
}
```

### AudioFrame（7.1 全字段）

stream_id / sequence / timestamp_ns / sample_rate / channels / sample_format /
frame_count / payload(f32le bytes) / end_of_stream / end_of_utterance / target_instance

### TextEvent（7.2 全字段）

stream_id / segment_id / sequence / text / language / is_partial / is_final /
stability / start_time / end_time / confidence

### TtsRequest（7.3 全字段）

request_id / text / language / voice_profile / style / speed / pitch / energy /
priority / interrupt_mode（QUEUE / INTERRUPT / REPLACE_PENDING / DROP_IF_BUSY）

### ControlSignal

vad_start / vad_end / ptt_down / ptt_up / flush / eos / interrupt / clear + payload_json

## 路由规则

- 宿主 → 插件：`target_node` = 节点实例 id；`target_instance` 冗余携带于各 body。
- 插件 → 宿主：`source_node` = 实例 id；宿主按管线图的出边投递（背压策略生效）。

## 延迟预算

gRPC 双向流在 localhost 实测 <2ms/帧（见 PERFORMANCE_REPORT）。
若未来音频吞吐成为瓶颈，规格预留了共享内存环 + 轻量控制信号的升级路径，
但**未实测瓶颈前不实现**（避免过早优化）。
