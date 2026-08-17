//! 设备枚举与热插拔检测。
use cpal::traits::{DeviceTrait, HostTrait};
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceInfo {
    pub name: String,
    pub is_input: bool,
    pub is_output: bool,
    pub default_input: bool,
    pub default_output: bool,
    pub max_input_channels: u16,
    pub max_output_channels: u16,
    pub default_sample_rate: u32,
    /// 稳定键：名称+方向（Windows 设备索引在热插拔后会变化，禁止持久化索引）
    pub key: String,
}

fn host() -> cpal::Host {
    cpal::default_host()
}

pub fn list_devices() -> Vec<DeviceInfo> {
    let h = host();
    let def_in = h.default_input_device().and_then(|d| d.name().ok());
    let def_out = h.default_output_device().and_then(|d| d.name().ok());
    let mut out = Vec::new();
    if let Ok(devs) = h.input_devices() {
        for d in devs {
            let Ok(name) = d.name() else { continue };
            let Ok(cfg) = d.default_input_config() else {
                continue;
            };
            out.push(DeviceInfo {
                name: name.clone(),
                is_input: true,
                is_output: false,
                default_input: def_in.as_deref() == Some(name.as_str()),
                default_output: false,
                max_input_channels: cfg.channels(),
                max_output_channels: 0,
                default_sample_rate: cfg.sample_rate().0,
                key: format!("in|{name}"),
            });
        }
    }
    if let Ok(devs) = h.output_devices() {
        for d in devs {
            let Ok(name) = d.name() else { continue };
            let Ok(cfg) = d.default_output_config() else {
                continue;
            };
            out.push(DeviceInfo {
                name: name.clone(),
                is_input: false,
                is_output: true,
                default_input: false,
                default_output: def_out.as_deref() == Some(name.as_str()),
                max_input_channels: 0,
                max_output_channels: cfg.channels(),
                default_sample_rate: cfg.sample_rate().0,
                key: format!("out|{name}"),
            });
        }
    }
    out
}

pub fn find_by_key(key: &str) -> Option<cpal::Device> {
    let (dir, name) = key.split_once('|')?;
    let h = host();
    let devs = if dir == "in" {
        h.input_devices().ok()?
    } else {
        h.output_devices().ok()?
    };
    devs.into_iter()
        .find(|d| d.name().map(|n| n == name).unwrap_or(false))
}

/// VB-CABLE 检测（名称包含 CABLE Input/Output）。
pub fn find_virtual_output() -> Option<DeviceInfo> {
    list_devices()
        .into_iter()
        .find(|d| d.is_output && d.name.to_lowercase().contains("cable input"))
}

/// 热插拔轮询：上一帧设备键集合 vs 当前，返回 (新增, 消失)。
pub fn diff_devices(prev: &[String]) -> (Vec<DeviceInfo>, Vec<String>) {
    let now = list_devices();
    let now_keys: Vec<String> = now.iter().map(|d| d.key.clone()).collect();
    let added = now
        .iter()
        .filter(|d| !prev.contains(&d.key))
        .cloned()
        .collect();
    let removed = prev
        .iter()
        .filter(|k| !now_keys.contains(k))
        .cloned()
        .collect();
    (added, removed)
}
