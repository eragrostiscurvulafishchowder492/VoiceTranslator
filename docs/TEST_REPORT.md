# Test Report — Voice Studio

日期：2026-08-16（发布前更新）· 环境：Windows 11 · RTX 4060 Laptop 8GB · Rust 1.97.1 · Python 3.12.9

> 全部结果来自真实运行，原始日志在 `logs/`。复现：`.\scripts\test.ps1`。

## 0. 发布前新增验证（本轮补齐）

| 项 | 结果 | 证据 |
|---|---|---|
| **实机麦克风采集** | PASS：HECATE G2 默认输入，3s 采集 131712 帧，RMS 0.0066 / peak 0.2544（检测到环境声），44.1kHz 自动处理，**溢出=0** | `cargo run -p voice-audio-engine --example mic_probe` |
| **GUI 十页视觉验证** | PASS：`--page=<id>` 深链接逐页截图（logs/screenshots/*.png），节点编辑器带预置管线 9 节点+连线完整渲染 | 10 张截图 |
| **桌面命令层 E2E** | PASS：text.manual_input → textkit.to_tts（真实 worker）经 **插件自动启动→Configure 下发→桥接→引擎调度** 产出正确 tts.request（3.9s） | logs/desktop_e2e.log |
| **Configure 缺失 bug 修复** | 发现并修复：start_pipeline 原先不下发节点参数（含 `__node_type__` 路由键），插件节点全部失效 | 同上测试覆盖 |
| **隔离 venv 闭环** | PASS：tonegen 声明 isolated，自动创建 venv + SDK 依赖 + 握手 + 节点缓存（17.2s） | registry 15→25 节点 |
| **节点类型缓存** | 插件未运行时编辑器也能加载/校验预置管线（Warning 提示"启动时自动启动"，不再阻断） | studio2.png |

## 1. Rust 单元 + 集成测试（21 通过 / 0 失败）

`cargo test --workspace --exclude voice-studio-desktop`（logs/rust_tests.log）

| 套件 | 数量 | 覆盖 |
|---|---|---|
| pipeline-core | 10 | 端口类型解析、图序列化往返、**类型不匹配校验**、**循环检测（DFS）**、必需输入、缺失插件、显存预检、导出脱敏（绝对路径剥离）、背压策略解析、Payload 类型映射 |
| plugin-host 单元 | 6 | manifest 解析/校验、**未知权限解析期拒绝**、**api_version 主版本协商**、ZIP 安装往返 + checksums、**zip-slip 路径穿越拒绝**、**重启退避递增 + 次数上限** |
| persistence | 2 | 版本化迁移、管线 CRUD + 默认唯一、last_known_good、会话状态、声音档案、事件 |
| plugin-host 集成 | 1 | **宿主⇄真实 Python worker 全生命周期**（见下） |
| 桌面命令层 E2E | 1 | **插件自动启动 + Configure 下发 + 桥接 + 引擎调度**（真实 worker，见第 0 节） |
| 桌面原生管线 | 1 | WAV 文件→+6dB 增益→录制（48000 样本数值验证） |

### 插件生命周期集成测试（最关键验收证据，logs/lifecycle_test.log）

```
[lifecycle] worker pid=Some(56688) port=Some(64988)
[lifecycle] crash detected → state=stopped
[lifecycle] PASS — finished in 4.60s
```

验证链：临时 app-data 安装 gain 插件 → discover → spawn 独立 worker 进程 →
gRPC 握手（协议 1.0 协商）→ node_types 返回 → 注册表合并 → 数据面双向流
（480 样本音频回环，0dB 原样断言）→ **taskkill 强杀 worker → 宿主进程存活、
状态正确转移** → 优雅停止幂等。

## 2. Python SDK 回环（tests/smoke_plugin_sdk.py）

```
[1] worker 就绪 OK            [4] 音频回环 OK: 0.25 -> 0.4988 (+6dB 数值精确)
[2] 握手 OK（节点类型返回）     [5] Health OK
[3] Configure OK              [6] 优雅退出 OK (exit 0)
SMOKE PASS
```

## 3. 真实 AI 管线冒烟（tests/smoke_ai_pipeline.py，logs/smoke_ai.log）

经 gRPC 插件 worker 全链路（非直接调用引擎）：

```
[1] textkit + cosyvoice worker 就绪（独立进程）
[3] TTS 输出 OK: 4.76s 真实音频, 写入 logs/smoke_ai_tts.wav
[5] 断句 OK: ['你们先过去，我拿一下东西，马上']
AI PIPELINE SMOKE PASS
```

- CosyVoice3-0.5B 真实推理（worker 显存 4.6GB），流式 chunk 经 gRPC 双向流回传。
- 断句器（稳定前缀算法，复用 app/pipeline/chunker.py）经 Configure→增量 partial→final 全链路正确切分。
- TTFA 43.9s 为**冷启动**（首请求触发模型懒加载）；模型常驻后由 PERFORMANCE_REPORT 的基准覆盖。

## 4. 桌面应用

- 构建成功（debug + release），**启动冒烟**：进程存活 6s+、app-data 目录结构
  （database/plugins/models/references/pipelines/presets/logs/cache/temp/runtimes）完整创建。
- GUI 页面/节点编辑器为声明式 Vue 组件；自动化点击未纳入本轮（无 GUI 自动化框架），
  需要人工验收的部分已在 FINAL_REPORT 第 8 节如实列出。

## 5. 长时间运行（Soak，沿用 Python 引擎层）

- 30.06 分钟 / 345 轮全链路：错误率 0.29%（1/345）、avg_sim 0.919、
  **VRAM 6523MB × 345/345 轮零增长**、TTS 耗时无漂移（5 区块均值无单调上升）。
- 原始数据：logs/simulate_results.json、logs/simulate_30min.log。
- 注：soak 在引擎层执行（ASR/TTS 与桌面插件共享同一 app/ 引擎代码）；
  桌面 GUI 层 30 分钟 soak 列入已知未完成项（FINAL_REPORT 8.2）。

## 6. 测试覆盖缺口（如实）

1. 设备拔插/OOM/断流的故障注入为部分实现（热插拔轮询已实现并有保护逻辑，
   自动化注入测试未写）。
2. GUI 交互级自动化（点击/拖拽）未实现；视觉渲染已用截图验证覆盖。
3. VB-CABLE 虚拟输出：本机未安装，无法实测（逻辑与检测已实现）。
