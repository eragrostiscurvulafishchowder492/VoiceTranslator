//! 管线图（版本化 JSON，可导入/导出/迁移）。
use crate::types::{Backpressure, PortType};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// 管线格式版本（旧格式迁移入口）。
pub const PORT: u32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeInstance {
    pub id: String,
    /// 内置节点："audio.gain"；插件节点："plugin_id/node_type"
    pub node_type: String,
    pub label: String,
    pub params: serde_json::Value,
    /// 编辑器坐标（x, y）
    pub position: (f32, f32),
    #[serde(default)]
    pub bypassed: bool,
    #[serde(default)]
    pub notes: String,
    #[serde(default)]
    pub group: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Edge {
    pub id: String,
    pub from_node: String,
    pub from_port: String,
    pub to_node: String,
    pub to_port: String,
    #[serde(default)]
    pub backpressure: Backpressure,
    #[serde(default = "default_capacity")]
    pub capacity: usize,
}

fn default_capacity() -> usize {
    64
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PipelineGraph {
    pub format_version: u32,
    pub id: String,
    pub name: String,
    pub nodes: Vec<NodeInstance>,
    pub edges: Vec<Edge>,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub tags: Vec<String>,
}

impl PipelineGraph {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            format_version: PORT,
            id: voice_common::ids::new_id("pl"),
            name: name.into(),
            nodes: Vec::new(),
            edges: Vec::new(),
            description: String::new(),
            tags: Vec::new(),
        }
    }

    pub fn node(&self, id: &str) -> Option<&NodeInstance> {
        self.nodes.iter().find(|n| n.id == id)
    }

    pub fn node_mut(&mut self, id: &str) -> Option<&mut NodeInstance> {
        self.nodes.iter_mut().find(|n| n.id == id)
    }

    pub fn edge(&self, id: &str) -> Option<&Edge> {
        self.edges.iter().find(|e| e.id == id)
    }

    pub fn save_json(&self, path: &std::path::Path) -> anyhow::Result<()> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir)?;
        }
        std::fs::write(path, serde_json::to_string_pretty(self)?)?;
        Ok(())
    }

    pub fn load_json(path: &std::path::Path) -> anyhow::Result<Self> {
        let raw = std::fs::read_to_string(path)?;
        let mut g: PipelineGraph = serde_json::from_str(&raw)?;
        g.migrate();
        Ok(g)
    }

    /// 旧格式迁移：目前只有 v1。未来 v2 出现时在此链式升级。
    pub fn migrate(&mut self) {
        if self.format_version == 0 {
            self.format_version = 1;
        }
    }

    /// 导出安全化：去除绝对路径等隐私（二十三.）。
    pub fn export_sanitized(&self) -> anyhow::Result<String> {
        let mut g = self.clone();
        for n in &mut g.nodes {
            if let Some(obj) = n.params.as_object_mut() {
                for (k, v) in obj.iter_mut() {
                    if k.contains("path") || k.contains("dir") {
                        *v = serde_json::json!("$USER_FILE");
                    }
                }
            }
        }
        Ok(serde_json::to_string_pretty(&g)?)
    }
}

/// 端口描述（节点规格声明，内置与插件共用）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PortSpec {
    pub name: String,
    pub port_type: PortType,
    #[serde(default)]
    pub required: bool,
    /// 0 = 任意
    #[serde(default)]
    pub sample_rate: u32,
    #[serde(default)]
    pub channels: u16,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeSpec {
    pub node_type: String,
    pub display_name: String,
    pub category: String,
    pub inputs: Vec<PortSpec>,
    pub outputs: Vec<PortSpec>,
    pub default_params: serde_json::Value,
    /// JSON Schema（插件节点由 manifest 提供；内置节点为 null）
    #[serde(default)]
    pub params_schema: Option<serde_json::Value>,
    #[serde(default)]
    pub estimated_vram_mb: i32,
}

/// 节点类型注册表：内置 + 已安装插件提供的类型合并视图。
#[derive(Default)]
pub struct NodeRegistry {
    specs: HashMap<String, NodeSpec>,
}

impl NodeRegistry {
    pub fn register(&mut self, spec: NodeSpec) {
        self.specs.insert(spec.node_type.clone(), spec);
    }

    pub fn get(&self, node_type: &str) -> Option<&NodeSpec> {
        self.specs.get(node_type)
    }

    pub fn all(&self) -> Vec<&NodeSpec> {
        let mut v: Vec<_> = self.specs.values().collect();
        v.sort_by(|a, b| a.node_type.cmp(&b.node_type));
        v
    }

    pub fn categories(&self) -> Vec<(String, Vec<&NodeSpec>)> {
        let mut by_cat: HashMap<String, Vec<&NodeSpec>> = HashMap::new();
        for s in self.specs.values() {
            by_cat.entry(s.category.clone()).or_default().push(s);
        }
        let mut out: Vec<_> = by_cat.into_iter().collect();
        out.sort_by(|a, b| a.0.cmp(&b.0));
        out
    }
}
