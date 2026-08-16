# tests/ 说明

## 正式测试（CI / test.ps1 调用）

| 文件 | 内容 | 依赖 |
|---|---|---|
| `smoke_plugin_sdk.py` | SDK worker 全链路回环（握手/配置/数据面/健康/优雅退出） | .venv + sdk/python |
| `smoke_ai_pipeline.py` | 真实 AI 管线（textkit 断句 + CosyVoice TTS 经 gRPC） | 同上 + models/CosyVoice3-0.5B |
| `simulate.py [分钟]` | 全链路长稳 soak（TTS→ASR 回灌相似度/显存/漂移） | 同上 + 参考音频 |

Rust 侧测试在各 crate 的 `tests/` 与 `src`（`cargo test --workspace`）。

## 调参探测脚本（probe_*.py / tts_*.py）

历史调优过程的一次性脚本（fast LLM 等价性、流式 token 膨胀、ASR 增量合并验证等），
其结论已固化到 `app/` 代码与 docs/FINAL_REPORT.md。多数脚本需要一个用户自备的
测试音频：放到 `data/test_zh.wav`（或作为第一个命令行参数传入）。
不保证可重复运行，仅作方法记录。

## 隐私

任何测试音频/参考音频不入库（.gitignore 排除 data/references/ 与 *.wav）。
