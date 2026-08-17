# Changelog

本文件记录对用户和贡献者可见的重要变化。仓库目前没有可由 tag 证明的正式版本；在项目
所有者批准版本号和发布日期前，所有新条目保留在 Unreleased。

格式参考 Keep a Changelog，版本语义在正式发布策略确定后再由项目所有者确认。

## [Unreleased]

### Added

- 增加根级贡献指南、安全报告门禁、变更日志和依赖许可治理规则。
- 增加按 Cargo、pnpm、Python 和外部模型分层的第三方许可审计记录。
- 增加英文与简体中文图文 README、结构化 issue 表单、pull request 清单和 CODEOWNERS。
- 启用 GitHub private vulnerability reporting，并在根安全策略中提供经验证的私密入口。

### Changed

- 将 9 个 Rust workspace package 和 9 个仓库内插件的 package-level license metadata
  与根 `LICENSE` 统一为 Apache-2.0。
- README 明确区分项目代码许可与第三方依赖、模型、声音素材各自的条款。

### Known release gates

- 尚未确定稳定版本支持周期、响应 SLA 和二进制发布策略。
- Python 传递依赖/hash lock、PyTorch wheel、模型 revision 与完整依赖许可证/NOTICE 包
  尚未冻结。
- 第三方模型与 LGPL 等条件性许可仍需按最终发行物人工审核。

## Prior history

本文件建立前的提交历史未被追溯改写成发布记录。需要历史细节时应查看 Git 历史；不要
把既有 commit 自动视为正式发布版本。
