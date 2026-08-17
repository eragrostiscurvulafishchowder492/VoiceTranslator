# Contributing to Voice Studio

Thank you for contributing. Start with a focused GitHub issue or pull request, keep generated
artifacts, models, credentials, private audio, and personal paths out of the repository, and follow
[`SECURITY.md`](SECURITY.md) for sensitive reports. The contributor baseline is:

```text
cargo fmt --all -- --check
pnpm install --frozen-lockfile
pnpm --filter voice-studio-desktop check
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -SkipAi
```

Record exact commands, exit codes, and any model, GPU, hardware, GUI, packaging, or soak gates that
were not run. Contributions are submitted under Apache-2.0 unless explicitly stated otherwise, as
described in section 5 of the license. The project currently requires neither a CLA nor a DCO.

## 简体中文

感谢参与 Voice Studio。请通过本仓库的 GitHub issue 或 pull request 提交讨论和变更。

## 开始之前

1. 阅读 `README.md`、相关 `docs/` 文档以及根目录 `SECURITY.md`。
2. 对可能包含漏洞细节的内容先遵守 `SECURITY.md`，不要直接公开敏感 PoC、令牌、个人
   音频或绝对本机路径。
3. 保持改动单一、可审查；不要混入生成物、模型权重、虚拟环境、缓存或用户音色素材。
4. 不要猜测版权主体、联系方式、未来发布状态或支持承诺。

## 开发与验证

开发环境和常用脚本见 `README.md`。按改动范围至少完成相应检查，并在提交说明中记录
命令、exit code 和未执行项：

```text
cargo fmt --all -- --check
pnpm install --frozen-lockfile
pnpm --filter voice-studio-desktop check
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1 -SkipAi
```

`scripts/test.ps1 -SkipAi` 是贡献者非 AI 基线：它以 `--locked` 运行非桌面 workspace tests、
完整的 `voice-studio-desktop` tests（含标准 integration targets），再运行 Python SDK 回环。
AI/GPU/模型、Windows 音频设备、桌面 GUI 和 `-Soak` 长稳是单独门禁。不能执行时应明确
标为未验证，不要用无关的 smoke test 代替实机结论。

## 代码和文档约定

- Rust workspace package 和仓库内自有插件代码的 package-level license metadata 应为
  `Apache-2.0`。模型级 license 字段描述第三方模型，必须由上游材料支持，不能继承项目
  许可证。
- 修改依赖时同步更新相应 manifest、lockfile、`docs/DEPENDENCY_POLICY.md` 和
  `THIRD_PARTY_NOTICES.md`。不得仅凭包名或 lockfile 猜测许可证。
- 新插件应声明最小权限；`network`、`process_spawn`、文件写入等能力必须在说明中解释。
- 测试不得依赖个人凭据、私人模型或不可公开的语音素材。
- 用户可见行为、兼容性或治理变化应写入 `CHANGELOG.md` 的 Unreleased 部分。

## 贡献许可

本项目按 Apache License 2.0 发布。依据该许可证第 5 节，除非贡献者明确另行说明，主动
提交并被接收的贡献按相同许可提供。提交者必须有权提供其代码、文档和素材，并保留所有
适用的第三方署名和 NOTICE。仓库当前未声明额外 CLA 或 DCO 流程；项目所有者如要采用，
须另行明确决定并公开规则。

## 变更说明清单

- 说明问题、方案、用户影响和回退方式；
- 列出修改文件，标注生成文件或依赖变更；
- 提供一次性验证命令及结果，标明设备/GUI/模型相关未验证项；
- 确认没有加入秘密、个人数据、模型权重、未授权音频或未核实的第三方许可声明；
- 如影响发布或许可证义务，指出需要项目所有者决定的事项。
