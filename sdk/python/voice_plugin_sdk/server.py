"""SDK gRPC worker 服务端。

用法（由 Rust 宿主 spawn，也可手动调试）：
  python -m voice_plugin_sdk.server --manifest-dir <插件目录> --port <端口>

职责：
- 加载 plugin.toml（身份/权限/依赖）
- 导入 entrypoint（默认在插件目录 python/ 下找 plugin_impl:create_plugin）
- 实现 VoicePlugin 服务：握手 / 配置 / 加载模型 / 双向流 / 心跳 / 中断 / 停止
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

import grpc

from . import PROTOCOL_VERSION
from ._gen import voice_plugin_v1_pb2 as pb
from ._gen import voice_plugin_v1_pb2_grpc as pb_grpc
from .base import (AudioFrame, ControlSignal, EmitAudio, PluginContext,
                   TextEvent, TtsRequest, VoicePlugin)


def load_manifest(manifest_dir: Path) -> dict:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(manifest_dir / "plugin.toml", "rb") as f:
        return tomllib.load(f)


def load_plugin(manifest_dir: Path, manifest: dict) -> VoicePlugin:
    """entrypoint = "module:attr"；module 从插件 python/ 目录按文件唯一加载。

    不同插件的模块可能同名（约定 plugin_impl），因此用文件路径 +
    唯一内部模块名加载，绝不复用 sys.modules 缓存。
    """
    entry = manifest.get("entrypoint", "")
    mod_name, _, attr = entry.partition(":")
    py_dir = manifest_dir / "python"
    if py_dir.exists():
        sys.path.insert(0, str(py_dir))
    mod_file = py_dir / f"{mod_name.replace('.', '/')}.py"
    if mod_file.exists():
        unique = f"_vp_{abs(hash(str(manifest_dir))) & 0xffffff:x}_{mod_name.replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(unique, mod_file)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    else:
        mod = importlib.import_module(mod_name)
    obj = getattr(mod, attr)
    if callable(obj):
        obj = obj()
    if not isinstance(obj, VoicePlugin):
        # 允许延迟实例化的工厂
        ret = obj()
        assert isinstance(ret, VoicePlugin), f"{entry} 必须返回 VoicePlugin 实例"
        return ret
    return obj


def _merge_runtime_manifest(manifest: dict, runtime: dict) -> dict:
    m = dict(manifest)
    if "node_types" in runtime:
        m["node_types"] = runtime["node_types"]
    if "models" in runtime:
        m["models"] = runtime["models"]
    return m


def node_type_to_pb(nt: dict) -> pb.NodeTypeDescriptor:
    def port(p):
        return pb.PortDescriptor(
            name=p.get("name", ""), port_type=p.get("port_type", "audio.pcm"),
            required=bool(p.get("required", False)),
            sample_rate=int(p.get("sample_rate", 0) or 0),
            channels=int(p.get("channels", 0) or 0))
    return pb.NodeTypeDescriptor(
        node_type=nt.get("node_type", ""),
        display_name=nt.get("display_name", nt.get("node_type", "")),
        category=nt.get("category", "other"),
        inputs=[port(p) for p in nt.get("inputs", [])],
        outputs=[port(p) for p in nt.get("outputs", [])],
        params_schema_json=json.dumps(nt.get("params_schema", {}), ensure_ascii=False),
        default_params_json=json.dumps(nt.get("default_params", {}), ensure_ascii=False),
        estimated_vram_mb=int(nt.get("estimated_vram_mb", 0) or 0))


def model_to_pb(md: dict) -> pb.ModelInfo:
    return pb.ModelInfo(
        model_id=md.get("model_id", ""), display_name=md.get("display_name", ""),
        local_path=md.get("local_path", ""), size_bytes=int(md.get("size_bytes", 0) or 0),
        license=md.get("license", ""), estimated_vram_mb=int(md.get("estimated_vram_mb", 0) or 0),
        download_url=md.get("download_url", ""), sha256=md.get("sha256", ""),
        file_glob=md.get("file_glob", ""))


class Servicer(pb_grpc.VoicePluginServicer):
    def __init__(self, plugin: VoicePlugin, manifest_dir: Path, manifest: dict):
        self.plugin = plugin
        self.manifest_dir = manifest_dir
        self.manifest = manifest
        self.out_queues: list[asyncio.Queue] = []
        self.ctx = PluginContext(emit=self._emit)
        self.ctx.data_dir = str(manifest_dir / "_data")
        Path(self.ctx.data_dir).mkdir(parents=True, exist_ok=True)
        self._tts_tasks: set[asyncio.Task] = set()

    # ---------- 输出发射 ----------
    async def _emit(self, instance_id: str, item) -> None:
        msg = self._wrap(instance_id, item)
        if os.environ.get("VOICE_SDK_TRACE"):
            kind = type(item).__name__
            detail = getattr(item, "text", "")[:20] if hasattr(item, "text") else ""
            print(f"[sdk-trace] emit {kind} -> {instance_id} queues={len(self.out_queues)} {detail}", flush=True)
        for q in list(self.out_queues):
            await q.put(msg)

    def _wrap(self, instance_id: str, item) -> pb.PluginMessage:
        src_node = instance_id
        if isinstance(item, EmitAudio):
            frame = pb.AudioFrame(
                stream_id="out", sequence=int(time.time() * 1000) % (1 << 31),
                timestamp_ns=time.time_ns(), sample_rate=item.sample_rate,
                channels=item.channels, sample_format="f32le",
                frame_count=len(item.samples) // 4,
                payload=item.samples, end_of_utterance=item.end_of_utterance)
            return pb.PluginMessage(
                protocol_version=PROTOCOL_VERSION, schema_version=1,
                source_node=src_node, source_port="out",
                target_node="", target_port="", audio=frame)
        elif isinstance(item, ControlSignal):
            ctrl = pb.ControlSignal(
                signal=item.signal, payload_json=json.dumps(item.payload, ensure_ascii=False))
            return pb.PluginMessage(
                protocol_version=PROTOCOL_VERSION, schema_version=1,
                source_node=src_node, source_port="control",
                target_node="", target_port="", control=ctrl)
        elif isinstance(item, TtsRequest):
            tts = pb.TtsRequest(
                request_id=item.request_id or f"tts{int(time.time()*1000)}",
                text=item.text, language=item.language,
                voice_profile=item.voice_profile, style=item.style,
                speed=item.speed, pitch=item.pitch, energy=item.energy,
                priority=item.priority, interrupt_mode=item.interrupt_mode)
            return pb.PluginMessage(
                protocol_version=PROTOCOL_VERSION, schema_version=1,
                source_node=src_node, source_port="out",
                target_node="", target_port="", tts=tts)
        elif isinstance(item, TextEvent):
            ev = pb.TextEvent(
                stream_id="asr", segment_id=item.segment_id, sequence=item.sequence,
                text=item.text, language=item.language, is_partial=item.is_partial,
                is_final=item.is_final, stability=item.stability,
                start_time=item.start_time, end_time=item.end_time,
                confidence=item.confidence)
            return pb.PluginMessage(
                protocol_version=PROTOCOL_VERSION, schema_version=1,
                source_node=src_node, source_port="text",
                target_node="", target_port="", text=ev)
        raise TypeError(f"不能发射的类型: {type(item)}")

    # ---------- 服务方法 ----------
    async def Handshake(self, request, context):
        m = _merge_runtime_manifest(self.manifest, self.plugin.manifest() or {})
        return pb.HandshakeResponse(
            plugin_protocol_version=PROTOCOL_VERSION,
            plugin_id=m.get("id", ""),
            plugin_version=m.get("version", ""),
            supported_features=["stream_audio", "stream_text", "tts", "interrupt", "metrics"],
            supported_audio_formats=["pcm_f32le@48000:1", "pcm_f32le@16000:1", "pcm_f32le@24000:1"],
            supported_execution_providers=["cpu", "cuda"] if _cuda_available() else ["cpu"],
            node_types=[node_type_to_pb(nt) for nt in m.get("node_types", [])],
            models=[model_to_pb(md) for md in m.get("models", [])],
            ok=True)

    async def Configure(self, request, context):
        try:
            params = json.loads(request.params_json or "{}")
        except json.JSONDecodeError:
            params = {}
        params["__node_type__"] = request.node_type
        self.ctx.node_params[request.instance_id] = params
        return pb.Empty()

    async def LoadModel(self, request, context):
        t0 = time.perf_counter()
        try:
            r = await self.plugin.load_model(request.instance_id, request.model_id, request.model_path)
            r = r or {}
            return pb.LoadModelResponse(
                ok=bool(r.get("ok", True)), error=r.get("error", ""),
                load_ms=int((time.perf_counter() - t0) * 1000),
                vram_mb=int(r.get("vram_mb", 0)))
        except Exception as e:
            return pb.LoadModelResponse(ok=False, error=f"{e}\n{traceback.format_exc()}")

    async def Interrupt(self, request, context):
        await self.plugin.interrupt(request.instance_id)
        return pb.InterruptResponse(ok=True)

    async def Health(self, request, context):
        try:
            h = await self.plugin.health() or {}
            import psutil
            proc = psutil.Process()
            rss = proc.memory_info().rss
            cpu = proc.cpu_percent(interval=0.05)
        except Exception:
            rss, cpu = 0, 0.0
        vram = _vram_bytes()
        return pb.HealthResponse(
            status=h.get("status", "ok"), uptime_ms=int((time.time() - self.ctx.started_at) * 1000),
            cpu_percent=cpu, rss_bytes=rss, vram_bytes=vram,
            detail=h.get("detail", ""))

    async def Shutdown(self, request, context):
        await self.plugin.shutdown()
        loop = asyncio.get_running_loop()
        loop.call_later(0.3, os._exit, 0)
        return pb.Empty()

    # ---------- 数据面 ----------
    async def Process(self, request_iterator, context):
        queue: asyncio.Queue = asyncio.Queue(maxsize=4096)
        self.out_queues.append(queue)

        async def pump_in():
            async for msg in request_iterator:
                try:
                    await self._dispatch(msg)
                except Exception:
                    traceback.print_exc()

        in_task = asyncio.create_task(pump_in())
        try:
            while True:
                if context.done():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                yield item
        finally:
            in_task.cancel()
            self.out_queues.remove(queue)

    async def _dispatch(self, msg: pb.PluginMessage) -> None:
        which = msg.WhichOneof("body")
        inst = _target_instance(msg)
        if which == "audio":
            frame = AudioFrame(
                stream_id=msg.audio.stream_id, sequence=msg.audio.sequence,
                timestamp_ns=msg.audio.timestamp_ns, sample_rate=msg.audio.sample_rate,
                channels=msg.audio.channels, samples=msg.audio.payload,
                frame_count=msg.audio.frame_count,
                end_of_stream=msg.audio.end_of_stream,
                end_of_utterance=msg.audio.end_of_utterance)
            await self.plugin.process_audio(inst, frame, self.ctx)
        elif which == "text":
            ev = TextEvent(
                stream_id=msg.text.stream_id, segment_id=msg.text.segment_id,
                sequence=msg.text.sequence, text=msg.text.text,
                language=msg.text.language, is_partial=msg.text.is_partial,
                is_final=msg.text.is_final, stability=msg.text.stability,
                start_time=msg.text.start_time, end_time=msg.text.end_time,
                confidence=msg.text.confidence)
            await self.plugin.process_text(inst, ev, self.ctx)
        elif which == "tts":
            req = TtsRequest(
                request_id=msg.tts.request_id, text=msg.tts.text,
                language=msg.tts.language, voice_profile=msg.tts.voice_profile,
                style=msg.tts.style, speed=msg.tts.speed, pitch=msg.tts.pitch,
                energy=msg.tts.energy, priority=msg.tts.priority,
                interrupt_mode=msg.tts.interrupt_mode)
            task = asyncio.create_task(self._run_tts(inst, req))
            self._tts_tasks.add(task)
            task.add_done_callback(self._tts_tasks.discard)
        elif which == "control":
            try:
                payload = json.loads(msg.control.payload_json or "{}")
            except json.JSONDecodeError:
                payload = {}
            await self.plugin.on_control(inst, ControlSignal(signal=msg.control.signal, payload=payload), self.ctx)

    async def _run_tts(self, inst: str, req: TtsRequest):
        try:
            gen = self.plugin.process_tts(inst, req, self.ctx)
            async for chunk in gen:
                await self._emit(inst, chunk)
        except Exception:
            traceback.print_exc()


def _target_instance(msg) -> str:
    which = msg.WhichOneof("body")
    if which == "audio" and msg.audio.target_instance:
        return msg.audio.target_instance
    if which == "text" and msg.text.target_instance:
        return msg.text.target_instance
    if which == "tts" and msg.tts.target_instance:
        return msg.tts.target_instance
    if which == "control" and msg.control.target_instance:
        return msg.control.target_instance
    return msg.target_node


def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


def _vram_bytes() -> int:
    try:
        import torch
        if torch.cuda.is_available():
            return torch.cuda.memory_allocated()
    except Exception:
        pass
    return 0


async def serve(manifest_dir: Path, port: int) -> None:
    manifest = load_manifest(manifest_dir)
    plugin = load_plugin(manifest_dir, manifest)
    servicer = Servicer(plugin, manifest_dir, manifest)
    servicer.ctx.loop = asyncio.get_running_loop()
    await plugin.initialize(servicer.ctx)

    server = grpc.aio.server()
    pb_grpc.add_VoicePluginServicer_to_server(servicer, server)
    addr = f"127.0.0.1:{port}"
    server.add_insecure_port(addr)
    await server.start()
    print(f"[voice-plugin-sdk] {manifest.get('id', '?')} serving on {addr}", flush=True)
    await server.wait_for_termination()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest-dir", required=True)
    ap.add_argument("--port", type=int, required=True)
    args = ap.parse_args()
    try:
        asyncio.run(serve(Path(args.manifest_dir), args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
