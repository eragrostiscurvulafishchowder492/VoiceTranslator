//! Graph Validator：连接前/启动前的全部校验与自动转换建议（八.）。
use crate::graph::{NodeRegistry, PipelineGraph};
use crate::types::PortType;
use std::collections::{HashMap, HashSet};

#[derive(Debug, Clone, serde::Serialize)]
pub struct ValidationIssue {
    pub level: Severity,
    pub code: String,
    pub message: String,
    pub node_id: Option<String>,
    pub edge_id: Option<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize)]
pub enum Severity {
    Error,
    Warning,
    Info,
}

/// 外部依赖检查（由宿主注入：插件安装状态、模型存在性、显存）。
pub type ModelAvailabilityCheck<'a> = dyn Fn(&str, &str) -> bool + 'a;

pub struct ExternalChecks<'a> {
    pub is_plugin_installed: Box<dyn Fn(&str) -> bool + 'a>,
    pub has_model: Box<ModelAvailabilityCheck<'a>>,
    pub total_vram_mb: u32,
    pub used_vram_mb: u32,
}

impl<'a> Default for ExternalChecks<'a> {
    fn default() -> Self {
        Self {
            is_plugin_installed: Box::new(|_| false),
            has_model: Box::new(|_, _| false),
            total_vram_mb: 0,
            used_vram_mb: 0,
        }
    }
}

pub fn validate(
    graph: &PipelineGraph,
    registry: &NodeRegistry,
    ext: &ExternalChecks,
) -> Vec<ValidationIssue> {
    let mut issues = Vec::new();
    let node_ids: HashSet<&str> = graph.nodes.iter().map(|n| n.id.as_str()).collect();

    // 1) 节点类型已知 & 插件已安装
    for n in &graph.nodes {
        let is_plugin_node = n.node_type.contains('/');
        if registry.get(&n.node_type).is_none() {
            let (level, code, msg) = if is_plugin_node {
                let plugin_id = n.node_type.split('/').next().unwrap_or("");
                if !(ext.is_plugin_installed)(plugin_id) {
                    (
                        Severity::Error,
                        "PLUGIN_MISSING",
                        format!("插件 {plugin_id} 未安装或被禁用"),
                    )
                } else {
                    // 已安装未运行：启动管线时会自动拉起 worker，可校验性受限但不阻塞
                    (
                        Severity::Warning,
                        "PLUGIN_NOT_RUNNING",
                        format!("插件 {plugin_id} 未运行，端口暂无法校验（启动管线时自动启动）"),
                    )
                }
            } else {
                (
                    Severity::Error,
                    "UNKNOWN_NODE_TYPE",
                    format!("未知节点类型 {}", n.node_type),
                )
            };
            issues.push(ValidationIssue {
                level,
                code: code.into(),
                message: msg,
                node_id: Some(n.id.clone()),
                edge_id: None,
            });
            continue;
        }
        if is_plugin_node {
            let plugin_id = n.node_type.split('/').next().unwrap_or("");
            if !(ext.is_plugin_installed)(plugin_id) {
                issues.push(ValidationIssue {
                    level: Severity::Error,
                    code: "PLUGIN_MISSING".into(),
                    message: format!("插件 {plugin_id} 未安装或被禁用"),
                    node_id: Some(n.id.clone()),
                    edge_id: None,
                });
            }
        }
    }

    // 2) 边引用存在 + 端口存在 + 类型/采样率/声道兼容
    let mut in_degree: HashMap<&str, usize> = HashMap::new();
    for e in &graph.edges {
        let edge_err = |code: &str, msg: String| ValidationIssue {
            level: Severity::Error,
            code: code.into(),
            message: msg,
            node_id: None,
            edge_id: Some(e.id.clone()),
        };
        let (Some(from), Some(to)) = (graph.node(&e.from_node), graph.node(&e.to_node)) else {
            issues.push(edge_err("DANGLING_EDGE", "边引用了不存在的节点".into()));
            continue;
        };
        let (Some(fs), Some(ts)) = (registry.get(&from.node_type), registry.get(&to.node_type))
        else {
            continue; // 上面的 UNKNOWN_NODE_TYPE 已报
        };
        let Some(fport) = fs.outputs.iter().find(|p| p.name == e.from_port) else {
            issues.push(edge_err(
                "PORT_MISSING",
                format!("节点 {} 无输出端口 {}", from.label, e.from_port),
            ));
            continue;
        };
        let Some(tport) = ts.inputs.iter().find(|p| p.name == e.to_port) else {
            issues.push(edge_err(
                "PORT_MISSING",
                format!("节点 {} 无输入端口 {}", to.label, e.to_port),
            ));
            continue;
        };
        if fport.port_type != tport.port_type {
            issues.push(edge_err(
                "TYPE_MISMATCH",
                format!(
                    "端口类型不兼容：{} ({}) → {} ({})",
                    e.from_port,
                    fport.port_type.as_str(),
                    e.to_port,
                    tport.port_type.as_str()
                ),
            ));
            continue;
        }
        if fport.port_type == PortType::AudioPcm {
            if fport.sample_rate != 0
                && tport.sample_rate != 0
                && fport.sample_rate != tport.sample_rate
            {
                issues.push(ValidationIssue {
                    level: Severity::Warning,
                    code: "RATE_MISMATCH".into(),
                    message: format!(
                        "采样率 {} → {}，可自动插入 Resampler",
                        fport.sample_rate, tport.sample_rate
                    ),
                    node_id: None,
                    edge_id: Some(e.id.clone()),
                });
            }
            if fport.channels != 0 && tport.channels != 0 && fport.channels != tport.channels {
                issues.push(ValidationIssue {
                    level: Severity::Warning,
                    code: "CHANNEL_MISMATCH".into(),
                    message: format!(
                        "声道 {} → {}，可自动插入 Channel Converter",
                        fport.channels, tport.channels
                    ),
                    node_id: None,
                    edge_id: Some(e.id.clone()),
                });
            }
        }
        *in_degree.entry(e.to_node.as_str()).or_default() += 1;
    }

    // 3) 必需输入端口必须连线
    for n in &graph.nodes {
        let Some(spec) = registry.get(&n.node_type) else {
            continue;
        };
        for p in &spec.inputs {
            if p.required {
                let connected = graph
                    .edges
                    .iter()
                    .any(|e| e.to_node == n.id && e.to_port == p.name);
                if !connected {
                    issues.push(ValidationIssue {
                        level: Severity::Error,
                        code: "REQUIRED_INPUT".into(),
                        message: format!("必需输入端口 {} 未连接", p.name),
                        node_id: Some(n.id.clone()),
                        edge_id: None,
                    });
                }
            }
        }
    }

    // 4) 必需参数（schema required 字段）
    for n in &graph.nodes {
        let Some(spec) = registry.get(&n.node_type) else {
            continue;
        };
        if let Some(schema) = &spec.params_schema {
            if let Some(req) = schema.get("required").and_then(|r| r.as_array()) {
                for r in req.iter().filter_map(|v| v.as_str()) {
                    let has = n.params.get(r).map(|v| !v.is_null()).unwrap_or(false);
                    if !has {
                        issues.push(ValidationIssue {
                            level: Severity::Error,
                            code: "REQUIRED_PARAM".into(),
                            message: format!("缺少必需参数 {r}"),
                            node_id: Some(n.id.clone()),
                            edge_id: None,
                        });
                    }
                }
            }
        }
    }

    // 5) 循环检测（DFS 三色标记）
    if let Some(cycle) = find_cycle(graph) {
        issues.push(ValidationIssue {
            level: Severity::Error,
            code: "CYCLE".into(),
            message: format!("存在非法循环：{}", cycle.join(" → ")),
            node_id: None,
            edge_id: None,
        });
    }

    // 6) 模型存在性 + 显存预检
    let mut est_vram = 0u32;
    for n in &graph.nodes {
        let Some(spec) = registry.get(&n.node_type) else {
            continue;
        };
        est_vram += spec.estimated_vram_mb.max(0) as u32;
        if let Some(model_id) = n.params.get("model").and_then(|m| m.as_str()) {
            if !model_id.is_empty() && !(ext.has_model)(model_id, &n.node_type) {
                issues.push(ValidationIssue {
                    level: Severity::Error,
                    code: "MODEL_MISSING".into(),
                    message: format!("模型 {model_id} 不存在或未完成下载"),
                    node_id: Some(n.id.clone()),
                    edge_id: None,
                });
            }
        }
    }
    if ext.total_vram_mb > 0 && est_vram > 0 {
        let avail = ext.total_vram_mb.saturating_sub(ext.used_vram_mb);
        if est_vram > avail {
            issues.push(ValidationIssue {
                level: Severity::Warning,
                code: "VRAM_TIGHT".into(),
                message: format!(
                    "显存预检：预计 {}MB > 可用 {}MB（可能 OOM）",
                    est_vram, avail
                ),
                node_id: None,
                edge_id: None,
            });
        }
    }

    let _ = node_ids;
    let _ = &in_degree;
    issues
}

/// DFS 环检测，返回一条环路径。
fn find_cycle(graph: &PipelineGraph) -> Option<Vec<String>> {
    #[derive(Clone, Copy, PartialEq)]
    enum Mark {
        White,
        Gray,
        Black,
    }
    let mut marks: HashMap<&str, Mark> = graph
        .nodes
        .iter()
        .map(|n| (n.id.as_str(), Mark::White))
        .collect();
    let mut adj: HashMap<&str, Vec<&str>> = HashMap::new();
    for e in &graph.edges {
        adj.entry(e.from_node.as_str())
            .or_default()
            .push(e.to_node.as_str());
    }
    fn dfs<'g>(
        u: &'g str,
        adj: &HashMap<&'g str, Vec<&'g str>>,
        marks: &mut HashMap<&'g str, Mark>,
        path: &mut Vec<String>,
    ) -> Option<Vec<String>> {
        marks.insert(u, Mark::Gray);
        path.push(u.to_string());
        for &v in adj.get(u).map(|v| v.as_slice()).unwrap_or(&[]) {
            match marks.get(v).copied().unwrap_or(Mark::White) {
                Mark::Gray => {
                    let start = path.iter().position(|p| p == v).unwrap_or(0);
                    return Some(path[start..].to_vec());
                }
                Mark::White => {
                    if let Some(c) = dfs(v, adj, marks, path) {
                        return Some(c);
                    }
                }
                Mark::Black => {}
            }
        }
        path.pop();
        marks.insert(u, Mark::Black);
        None
    }
    for n in &graph.nodes {
        if marks.get(n.id.as_str()).copied() == Some(Mark::White) {
            let mut path = Vec::new();
            if let Some(c) = dfs(n.id.as_str(), &adj, &mut marks, &mut path) {
                return Some(c);
            }
        }
    }
    None
}
