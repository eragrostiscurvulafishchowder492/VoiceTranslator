# Security & Privacy

## 隐私（默认 Local First）

- 麦克风音频、参考音频、转写文本**全部本地处理**，不上传。
- 日志只写本地 `app-data/logs/`；日志不记录完整音频、令牌、密码。
- 管线导出（graph JSON）经 `export_sanitized` 剥离绝对路径；不含音频/API Key。
- 模型下载是唯一联网行为：一次性、官方源（ModelScope 等）。
- 不附带任何第三方角色语音；音色素材由用户导入（声音档案页明示）。

## 权限模型（10.3）

插件 manifest 必须声明权限，白名单：

```
microphone audio_output filesystem_read filesystem_write network gpu
process_spawn clipboard global_hotkey
```

- 未知权限在 manifest 解析期直接拒绝。
- `network` / `process_spawn` 在 GUI 插件页/安装时高亮警示。
- **第一版为声明式权限展示**：声明了权限不等于操作系统级强制。
  下述沙箱声明如实交代。

## ⚠️ 沙箱现状（如实声明）

> **进程隔离不等于完整安全沙箱。**

当前实现提供的隔离：

- 插件运行在独立操作系统进程（崩溃不拖垮宿主 ✔）
- 独立 gRPC 通道、独立日志、可独立停止/卸载（✔）
- 未授予管理员权限；不自动修改驱动/防火墙（✔）
- zip-slip 路径穿越防护、checksums 完整性校验（✔）

当前实现**不**提供：

- 文件系统/网络的强制隔离（插件进程理论上拥有当前用户权限）
- WebView 脚本注入面：第一版**禁止**插件向主 GUI 注入任意脚本，
  参数 UI 全部由宿主按 JSON Schema 生成（✔，这堵住了最大的攻击面）

结论：**只安装可信来源的插件**。企业/不可信场景需要真实沙箱（Job Object、
AppContainer、容器化 worker），已在架构上预留（Worker 抽象与权限位均支持扩展）。

## 完整性

- 插件 ZIP 安装：路径组件检查（拒绝 `..`/绝对路径）+ 临时目录解压 + 原子移动。
- `checksums.json` 存在时逐文件 SHA-256 校验，失败拒绝安装。
- 打包产物（安装包/ZIP）附 SHA256SUMS.txt。

## 热键与焦点

全局热键（F8~F11）通过 Tauri global-shortcut 注册；冲突时注册失败并写日志，
不影响其他热键。
