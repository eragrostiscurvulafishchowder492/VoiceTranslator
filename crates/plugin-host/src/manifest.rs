//! Plugin Manifest（plugin.toml，10.2）解析与校验。
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PluginManifest {
    pub id: String,
    pub name: String,
    pub version: String,
    pub api_version: String,
    pub runtime: String, // python / rust / external / http
    pub entrypoint: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub author: String,
    #[serde(default)]
    pub homepage: String,
    #[serde(default)]
    pub license: String,
    #[serde(default)]
    pub supported_os: Vec<String>,   // 空 = 全部
    #[serde(default)]
    pub supported_arch: Vec<String>,
    #[serde(default)]
    pub minimum_host_version: String,
    #[serde(default)]
    pub maximum_host_version: String,
    #[serde(default)]
    pub capabilities: Vec<String>,
    #[serde(default)]
    pub permissions: Vec<String>,    // microphone / audio_output / filesystem_read / ...
    #[serde(default)]
    pub node_types: Vec<NodeTypeDef>,
    #[serde(default)]
    pub models: Vec<ModelDef>,
    #[serde(default)]
    pub runtime_requirements: RuntimeRequirements,
    #[serde(default = "default_healthcheck_s")]
    pub healthcheck_interval_s: u64,
    /// 声明的权限若含 network，安装时必须高亮（默认网络关闭）
    pub network: Option<bool>,
}

fn default_healthcheck_s() -> u64 { 5 }

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct NodeTypeDef {
    pub node_type: String,
    pub display_name: String,
    pub category: String,
    #[serde(default)]
    pub inputs: Vec<PortDef>,
    #[serde(default)]
    pub outputs: Vec<PortDef>,
    #[serde(default)]
    pub params_schema_json: String,
    #[serde(default)]
    pub default_params_json: String,
    #[serde(default)]
    pub estimated_vram_mb: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PortDef {
    pub name: String,
    pub port_type: String,
    #[serde(default)]
    pub required: bool,
    #[serde(default)]
    pub sample_rate: u32,
    #[serde(default)]
    pub channels: u16,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ModelDef {
    pub model_id: String,
    pub display_name: String,
    #[serde(default)]
    pub local_path: String,
    #[serde(default)]
    pub size_bytes: u64,
    #[serde(default)]
    pub license: String,
    #[serde(default)]
    pub estimated_vram_mb: i32,
    #[serde(default)]
    pub download_url: String,
    #[serde(default)]
    pub sha256: String,
    #[serde(default)]
    pub file_glob: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct RuntimeRequirements {
    /// "main" = 仓库主 .venv；"isolated" = 独立 venv（app-data/runtimes/plugin-envs/<id>）
    #[serde(default)]
    pub python_env: String,
    #[serde(default)]
    pub python_version: String,
    /// pip 安装的依赖文件（相对插件目录）
    #[serde(default)]
    pub requirements_file: String,
    #[serde(default)]
    pub extra_python_path: Vec<String>,
}

/// 已知的合法权限集合（10.3）。
pub const KNOWN_PERMISSIONS: &[&str] = &[
    "microphone", "audio_output", "filesystem_read", "filesystem_write",
    "network", "gpu", "process_spawn", "clipboard", "global_hotkey",
];

impl PluginManifest {
    pub fn parse_toml(text: &str) -> anyhow::Result<Self> {
        let m: PluginManifest = toml::from_str(text)?;
        m.validate()?;
        Ok(m)
    }

    pub fn validate(&self) -> anyhow::Result<()> {
        anyhow::ensure!(!self.id.is_empty() && self.id.contains('.'), "插件 id 必须是反向域名形式");
        anyhow::ensure!(!self.name.is_empty(), "缺少 name");
        anyhow::ensure!(!self.version.is_empty(), "缺少 version");
        anyhow::ensure!(!self.api_version.is_empty(), "缺少 api_version");
        anyhow::ensure!(!self.runtime.is_empty(), "缺少 runtime");
        anyhow::ensure!(!self.entrypoint.is_empty(), "缺少 entrypoint");
        for p in &self.permissions {
            if !KNOWN_PERMISSIONS.contains(&p.as_str()) {
                anyhow::bail!("未知权限: {p}");
            }
        }
        Ok(())
    }

    /// api_version 主版本协商。
    pub fn api_compatible(&self, host: &str) -> bool {
        let major = |v: &str| v.split('.').next().unwrap_or("0").to_string();
        major(&self.api_version) == major(host)
    }
}

/// 从插件目录读取（plugin.toml 必须在根）。
pub fn load_manifest(dir: &std::path::Path) -> anyhow::Result<PluginManifest> {
    let text = std::fs::read_to_string(dir.join("plugin.toml"))?;
    PluginManifest::parse_toml(&text)
}

/// 校验插件包完整性（checksums.json：{"relpath": "sha256", ...}）。
pub fn verify_checksums(plugin_dir: &std::path::Path) -> anyhow::Result<Vec<String>> {
    let cs_path = plugin_dir.join("checksums.json");
    if !cs_path.exists() { return Ok(vec![]); }
    let map: std::collections::HashMap<String, String> =
        serde_json::from_str(&std::fs::read_to_string(&cs_path)?)?;
    let mut problems = Vec::new();
    for (rel, expect) in &map {
        let p = plugin_dir.join(rel);
        if !p.exists() {
            problems.push(format!("缺失: {rel}"));
            continue;
        }
        use sha2::Digest;
        use std::io::Read;
        let mut hasher = sha2::Sha256::new();
        let mut f = std::fs::File::open(&p)?;
        let mut buf = [0u8; 65536];
        loop {
            let n = f.read(&mut buf)?;
            if n == 0 { break; }
            hasher.update(&buf[..n]);
        }
        let got = hex::encode(hasher.finalize());
        if !expect.is_empty() && got != *expect {
            problems.push(format!("校验失败: {rel}"));
        }
    }
    Ok(problems)
}
