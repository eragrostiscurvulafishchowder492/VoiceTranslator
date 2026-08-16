# Troubleshooting

## 安装/构建

| 症状 | 处置 |
|---|---|
| `cargo` 不存在 | 安装 rustup（MSVC toolchain）。本机约定装 D 盘：`RUSTUP_HOME=D:\_toolchains\rustup`、`CARGO_HOME=D:\_toolchains\cargo` |
| Rust link 失败 | 需 VS2022「使用 C++ 的桌面开发」工作负载（MSVC v143 + Win10/11 SDK） |
| `pnpm` 不存在 | `npm i -g pnpm` |
| Tauri 白屏 | 先 `pnpm --filter voice-studio-desktop build` 生成 dist；release 包已内置 |
| 首次 cargo build 很慢 | 正常（Tauri/wry 依赖树 ~600 crate，10 分钟级） |

## 音频

| 症状 | 处置 |
|---|---|
| 检测不到 VB-CABLE | 从 vb-audio.com 安装（需管理员，手动执行）。不装也能用扬声器输出 |
| 没有声音 | ① 管线里输出节点参数的设备是否正确 ② 系统 mixer 静音 ③ 播放设备采样率异常（引擎会自动重采样，但独占模式设备请改共享） |
| 爆音/咔哒 | 查「性能与日志」页 underrun/overflow 计数；持续增长说明 CPU 不足 → 降低输入 block_ms 或关闭其他重负载程序 |
| 麦克风无输入 | Windows 隐私设置允许桌面应用访问麦克风 |
| 设备拔出后管线停了 | 预期行为（自动保护）。插回后重新启动管线 |

## 插件

| 症状 | 处置 |
|---|---|
| 插件启动失败 | 插件页看日志；常见：`.venv` 缺依赖（`pip install -r requirements.txt`）、模型目录不存在 |
| 协议不兼容拒绝运行 | 插件 api_version 主版本与宿主不同，需更新插件或宿主 |
| 插件反复重启后停 | 10 分钟内崩溃 5 次封顶。看日志定位；修复后手动「启动」 |
| wetext 前端下载 403 | ModelScope 限流。CosyVoice 回退基础正则前端，功能可用，数字读法略降级；稍后重试下载 |
| onnxruntime 无 CUDA provider | 当前为 CPU 构建，不影响主链路（VAD/ASR 均走 torch） |

## AI 管线

| 症状 | 处置 |
|---|---|
| TTS 首包慢（>3s） | 4060 8GB 上 0.5B LLM 的真实算力开销；确认 `fast_llm=true`、flow_steps=10；详见 PERFORMANCE_REPORT |
| ASR 同音字错误（火/我） | 在 funasr 节点参数配置热词（hotwords） |
| CUDA OOM | 关闭其他占显存程序；或减少同时运行的 AI 插件。宿主会显示真实错误，不伪装恢复 |
| speed≠1.0 无流式 | CosyVoice 模型限制，已自动回退整句合成 |

## 崩溃恢复

- 异常退出后重启会弹出恢复选项：**安全模式**（不自动加载任何插件/管线，推荐）或
  恢复 last_known_good 管线。
- 崩溃报告：`app-data/logs/crash/` + `app-data/logs/voice_YYYYMMDD.log`。

## 数据位置

`app-data/`（开发模式在仓库根；可用环境变量 `VOICE_STUDIO_DATA` 重定向）：
database/、plugins/、models/、references/、pipelines/、logs/、cache/、temp/。
