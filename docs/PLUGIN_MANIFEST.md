# Plugin Manifest（plugin.toml）

每个插件目录根部必须有 `plugin.toml`。

## 完整示例

```toml
id = "org.voicestudio.cosyvoice"          # 必填，反向域名
name = "CosyVoice3 零样本 TTS"             # 必填
version = "1.0.0"                          # 必填
api_version = "1.0"                        # 必填，与宿主主版本协商
runtime = "python"                         # 必填：python（当前）/ rust / external / http
entrypoint = "plugin_impl:create_plugin"   # 必填：module:attr（python/ 目录下）
description = "零样本流式 TTS"
author = "..."
homepage = "..."
license = "Apache-2.0"

# 权限白名单（10.3）。未知权限在解析期直接拒绝。
# microphone audio_output filesystem_read filesystem_write network gpu
# process_spawn clipboard global_hotkey
permissions = ["gpu", "filesystem_read"]

# 模型声明（GUI 模型页展示 + 显存预检）
[[models]]
model_id = "cosyvoice3-0.5b"
display_name = "CosyVoice3-0.5B"
local_path = "models/CosyVoice3-0.5B"      # 相对仓库根
size_bytes = 3200000000
license = "Apache-2.0"
estimated_vram_mb = 4200
file_glob = "llm.pt"                       # 完整性校验的目标文件

[runtime_requirements]
python_env = "main"                        # main = 仓库 .venv；isolated = 独立 venv
extra_python_path = ["deps/CosyVoice"]     # 追加 sys.path（相对仓库根）
```

## 字段校验规则

| 字段 | 规则 |
|---|---|
| id | 非空且含 `.`（反向域名） |
| api_version | 主版本 = 宿主主版本，否则拒绝运行 |
| permissions | 必须在白名单内 |
| entrypoint | `module:attr`；attr 可调用或为 VoicePlugin 实例 |

## 节点类型声明：TOML 或代码

两种方式，代码声明优先（握手时合并覆盖）：

1. TOML `[[node_types]]`（含 inputs/outputs/default_params/params_schema）
2. Python `VoicePlugin.manifest()` 返回 dict（本仓库所有插件采用此方式，
   因为 Schema 用 JSON 字面量更自然）

## 完整性（二十五.）

- `checksums.json`：`{相对路径: sha256}`。存在则安装/启动时全部校验，失败拒绝。
- 打包侧生成：`voice-plugin-host::install::write_checksums`（Rust）。

## 安装布局（10.1）

```
app-data/plugins/<id 下划线化>/
├─ plugin.toml
├─ python/            # entrypoint 模块查找根
│  └─ plugin_impl.py
├─ models/models.json # 可选
├─ checksums.json     # 可选但推荐
├─ README.md / LICENSES/
└─ _data/             # 插件私有数据（运行时创建）
```
