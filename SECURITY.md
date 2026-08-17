# Security Policy

[English](#english) | [简体中文](#简体中文)

## English

### Supported versions

Voice Studio does not yet have a tagged stable release series. Security fixes target the current
maintained default branch unless a future release policy says otherwise. The project does not
promise a response deadline, remediation SLA, bug bounty, or support lifetime.

The product's security boundaries, privacy properties, and sandbox limitations are documented in
[`docs/SECURITY.md`](docs/SECURITY.md). Plugin processes are not operating-system-level filesystem
or network sandboxes; install plugins only from sources you trust.

### Report a vulnerability privately

Use [GitHub private vulnerability reporting](https://github.com/RedeatI/VoiceTranslator/security/advisories/new)
for exploitable vulnerabilities, secrets, personal data exposure, or a complete proof of concept.
Do **not** disclose those details in a public issue, pull request, discussion, or log.

Non-sensitive hardening suggestions that contain no exploit details may use a normal GitHub issue.
Do not send vulnerability material to addresses inferred from commit history, package metadata, or
personal profiles.

Include the affected version or commit, platform, prerequisites, minimal reproduction, actual and
expected behavior, impact assessment, and suggested mitigation when available. Remove tokens,
private audio, transcripts, absolute personal paths, and unrelated personal data.

Maintainers will confirm scope, reproduce the issue where practical, assess impact, and coordinate
remediation and disclosure. No CVE, bounty, disclosure date, confidentiality term, or response time
is guaranteed. Vulnerabilities in third-party dependencies should also follow the upstream
project's reporting policy; this repository cannot accept reports on behalf of upstream projects.

## 简体中文

### 支持范围

Voice Studio 目前没有由 tag 证明的稳定发布系列。除非后续发布策略另有说明，安全修复以
当前维护的默认分支为准；项目不承诺响应时限、修复 SLA、漏洞奖励或支持周期。

产品安全边界、隐私属性和沙箱限制见 [`docs/SECURITY.md`](docs/SECURITY.md)。插件进程并非
操作系统级文件系统或网络沙箱，只应安装可信来源的插件。

### 私密报告漏洞

对于可利用漏洞、秘密或个人数据暴露、完整 PoC，请使用
[GitHub 私密漏洞报告](https://github.com/RedeatI/VoiceTranslator/security/advisories/new)。不要把
这些细节发布到公开 issue、pull request、discussion 或日志。

不含利用细节的非敏感加固建议可以提交普通 GitHub issue。不要把漏洞材料发送到从提交
历史、依赖元数据或个人主页推测出的地址。

报告尽量包含受影响版本或 commit、平台、前置条件、最小复现、实际与预期结果、影响判断
以及建议缓解方式。请删除令牌、私人音频、转写文本、绝对个人路径和无关个人数据。

维护者会确认范围，在可行时复现问题、评估影响，并协调修复和披露；不承诺 CVE、奖励、
披露日期、保密条款或响应时间。第三方依赖漏洞还应遵循对应上游的报告政策，本仓库不能
代表上游接收报告。
