"""Smoke Test：SDK worker 全链路回环（无需 GUI / Rust 宿主）。

验证：manifest 加载 → worker 启动 → gRPC 握手（协议协商）→ Configure →
音频流经 gain 节点（+6dB 数值精确验证）→ Health → 优雅 Shutdown。
退出码 0 = 通过。
"""
import asyncio
import os
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sdk" / "python"))

import grpc  # noqa: E402
from voice_plugin_sdk._gen import voice_plugin_v1_pb2 as pb  # noqa: E402
from voice_plugin_sdk._gen import voice_plugin_v1_pb2_grpc as pb_grpc  # noqa: E402


async def main() -> int:
    port = 5951
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "sdk" / "python")
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "voice_plugin_sdk.server",
         "--manifest-dir", str(ROOT / "plugins" / "examples" / "gain"),
         "--port", str(port)], env=env)
    try:
        # 1) 就绪等待
        stub = None
        for _ in range(60):
            try:
                ch = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
                stub = pb_grpc.VoicePluginStub(ch)
                await asyncio.wait_for(stub.Health(pb.Empty()), timeout=1)
                break
            except Exception:
                await asyncio.sleep(0.25)
        assert stub, "worker 未在 15s 内就绪"
        print("[1] worker 就绪 OK")

        # 2) 握手 + 协议版本
        hs = await stub.Handshake(pb.HandshakeRequest(
            host_protocol_version="1.0", host_app_version="smoke"))
        assert hs.ok and hs.plugin_id == "org.voicestudio.gain"
        assert hs.plugin_protocol_version.split(".")[0] == "1"
        assert any(n.node_type == "gain.audio_gain" for n in hs.node_types)
        print(f"[2] 握手 OK: {hs.plugin_id} v{hs.plugin_version}, "
              f"nodes={[n.node_type for n in hs.node_types]}")

        # 3) Configure
        await stub.Configure(pb.ConfigRequest(
            node_type="gain.audio_gain", instance_id="n1", params_json='{"gain_db": 6.0}'))
        print("[3] Configure OK")

        # 4) 音频回环（+6dB 精确验证）
        n = 480
        frame = pb.AudioFrame(stream_id="s", sequence=1, sample_rate=48000, channels=1,
                              sample_format="f32le", frame_count=n,
                              payload=struct.pack(f"<{n}f", *([0.25] * n)))
        msg = pb.PluginMessage(protocol_version="1.0", schema_version=1,
                               source_node="mic", source_port="out",
                               target_node="n1", target_port="in", audio=frame)

        async def gen():
            yield msg
            await asyncio.sleep(0.5)

        got = None
        async for resp in stub.Process(gen()):
            if resp.WhichOneof("body") == "audio":
                got = struct.unpack(f"<{resp.audio.frame_count}f", resp.audio.payload)[0]
                break
        expect = min(1.0, 0.25 * (10 ** (6.0 / 20.0)))
        assert got is not None and abs(got - expect) < 0.01, f"增益不符: {got} != {expect}"
        print(f"[4] 音频回环 OK: 0.25 -> {got:.4f} (+6dB)")

        # 5) Health
        h = await stub.Health(pb.Empty())
        assert h.status == "ok"
        print(f"[5] Health OK: uptime={h.uptime_ms}ms")

        # 6) 优雅停止
        await stub.Shutdown(pb.Empty())
        for _ in range(20):
            if proc.poll() is not None:
                break
            await asyncio.sleep(0.1)
        assert proc.poll() == 0, f"worker 退出码异常: {proc.poll()}"
        print("[6] 优雅退出 OK (exit 0)")
        print("\nSMOKE PASS")
        return 0
    finally:
        if proc.poll() is None:
            proc.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
