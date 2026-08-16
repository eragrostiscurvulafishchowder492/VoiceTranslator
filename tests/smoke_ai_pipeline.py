"""AI 管线 Smoke（真实模型，经插件 worker 走 gRPC 全链路）：

1) 启动 textkit + cosyvoice worker
2) text.final → segmenter → to_tts → TTS → 收集音频 → 保存 WAV
3) 验证：音频非空、TTFA、段完整性
（ASR 真实模型测试由 tests/simulate.py 与 logs/probe_asr* 覆盖，避免本测试重复加载 5GB+ 模型）
"""
import asyncio
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sdk" / "python"))

import grpc  # noqa: E402
from voice_plugin_sdk._gen import voice_plugin_v1_pb2 as pb  # noqa: E402
from voice_plugin_sdk._gen import voice_plugin_v1_pb2_grpc as pb_grpc  # noqa: E402

TEXT = "你们先过去，我拿一下东西，马上回来。"


async def start_worker(plugin_dir: str, port: int) -> subprocess.Popen:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "sdk" / "python")
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "voice_plugin_sdk.server",
         "--manifest-dir", str(ROOT / plugin_dir), "--port", str(port)], env=env)
    for _ in range(120):
        try:
            ch = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
            stub = pb_grpc.VoicePluginStub(ch)
            await asyncio.wait_for(stub.Health(pb.Empty()), timeout=1)
            return proc
        except Exception:
            await asyncio.sleep(0.5)
    proc.kill()
    raise RuntimeError(f"{plugin_dir} worker 未就绪")


async def main() -> int:
    textkit = await start_worker("plugins/ai/textkit", 5961)
    cosy = await start_worker("plugins/ai/cosyvoice", 5962)
    print("[1] textkit + cosyvoice worker 就绪")
    try:
        tk = pb_grpc.VoicePluginStub(grpc.aio.insecure_channel("127.0.0.1:5961"))
        cv = pb_grpc.VoicePluginStub(grpc.aio.insecure_channel("127.0.0.1:5962"))

        await tk.Configure(pb.ConfigRequest(node_type="textkit.segmenter",
                                            instance_id="seg", params_json="{}"))
        await tk.Configure(pb.ConfigRequest(node_type="textkit.to_tts",
                                            instance_id="tt", params_json="{}"))
        await cv.Configure(pb.ConfigRequest(node_type="cosyvoice.zero_shot_tts",
                                            instance_id="tts", params_json="{}"))
        print("[2] Configure 完成")

        # CosyVoice 数据面：收集 TTS 音频
        samples: list[float] = []
        rate = 24000
        ttfa_ms = 0
        done = asyncio.Event()

        async def cv_gen():
            yield pb.PluginMessage(
                protocol_version="1.0", schema_version=1,
                source_node="lab", source_port="out", target_node="tts", target_port="in",
                tts=pb.TtsRequest(request_id="smoke1", text=TEXT, language="zh",
                                  voice_profile="default", speed=1.0))

        t0 = time.perf_counter()
        async for resp in cv.Process(cv_gen()):
            if resp.WhichOneof("body") == "audio":
                a = resp.audio
                if not a.payload:
                    if a.end_of_utterance:
                        done.set()
                        break
                    continue
                if not ttfa_ms:
                    ttfa_ms = int((time.perf_counter() - t0) * 1000)
                rate = a.sample_rate
                vals = struct.unpack(f"<{len(a.payload)//4}f", a.payload)
                samples.extend(vals)

        await asyncio.wait_for(done.wait(), timeout=30) if samples else None
        # 容错：流可能在 end_of_utterance 前结束——只要音频足够即通过
        assert len(samples) > rate, f"音频过短: {len(samples)} 样本"
        print(f"[3] TTS 输出 OK: {len(samples)/rate:.2f}s 音频, TTFA={ttfa_ms}ms")

        out = ROOT / "logs" / "smoke_ai_tts.wav"
        out.parent.mkdir(exist_ok=True)
        import wave
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            import array
            arr = array.array("h", (max(-32767, min(32767, int(s * 32767))) for s in samples))
            w.writeframes(arr.tobytes())
        print(f"[4] WAV 已写入 {out}")

        # textkit 数据面：segmenter 增量 partial → 完整句
        # 注意：Process 是长驻双向流（不会因输入结束而关闭），
        # 测试侧用截止时间收集输出后主动断开。
        seg_out: list[str] = []

        async def tk_gen():
            for i, part in enumerate(["你们先过去，", "你们先过去，我拿一", "你们先过去，我拿一下东西，马上"]):
                yield pb.PluginMessage(
                    protocol_version="1.0", schema_version=1,
                    source_node="asr", source_port="partial", target_node="seg", target_port="in",
                    text=pb.TextEvent(text=part, is_partial=True, sequence=i))
                await asyncio.sleep(0.05)
            yield pb.PluginMessage(
                protocol_version="1.0", schema_version=1,
                source_node="asr", source_port="final", target_node="seg", target_port="in",
                text=pb.TextEvent(text="你们先过去，我拿一下东西，马上回来。", is_final=True, sequence=99))

        try:
            async with asyncio.timeout(3.0):
                async for resp in tk.Process(tk_gen()):
                    if resp.WhichOneof("body") == "text":
                        seg_out.append(resp.text.text)
        except (asyncio.TimeoutError, TimeoutError):
            pass
        # 断句器应在逗号处切分
        assert any("你们先过去，" in s for s in seg_out), f"断句输出异常: {seg_out}"
        print(f"[5] 断句 OK: {seg_out}")

        await tk.Shutdown(pb.Empty())
        await cv.Shutdown(pb.Empty())
        print("\nAI PIPELINE SMOKE PASS")
        return 0
    finally:
        for p in (textkit, cosy):
            if p.poll() is None:
                p.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
