//! 插件包安装（本地 ZIP）：解压、manifest 校验、校验和验证、原子完成。
use std::io::Read;
use std::path::{Path, PathBuf};

/// 安装 ZIP 到 plugins/，返回插件目录。
/// ZIP 根（或唯一子目录）必须含 plugin.toml。
pub fn install_zip(plugins_dir: &Path, zip_path: &Path) -> anyhow::Result<PathBuf> {
    let file = std::fs::File::open(zip_path)?;
    let mut archive = zip::ZipArchive::new(file)?;

    // 先在临时目录解压（原子完成：成功后才移动到位）
    let tmp = plugins_dir.join("_install_tmp");
    if tmp.exists() {
        std::fs::remove_dir_all(&tmp)?;
    }
    std::fs::create_dir_all(&tmp)?;

    for i in 0..archive.len() {
        let mut entry = archive.by_index(i)?;
        // 路径安全：拒绝 .. 与绝对路径组件
        let name = entry.name().to_string();
        let safe = !name.split(['/', '\\']).any(|c| c == "..") && !name.starts_with(['/', '\\']);
        anyhow::ensure!(safe, "插件包含非法路径: {name}");
        let out_path = tmp.join(&name);
        if entry.is_dir() {
            std::fs::create_dir_all(&out_path)?;
        } else {
            if let Some(p) = out_path.parent() {
                std::fs::create_dir_all(p)?;
            }
            let mut buf = Vec::new();
            entry.read_to_end(&mut buf)?;
            // zip-slip 已由上面的组件检查挡住
            std::fs::write(&out_path, &buf)?;
        }
    }

    // 定位 manifest：ZIP 根或唯一一级子目录
    let manifest_dir = if tmp.join("plugin.toml").exists() {
        tmp.clone()
    } else {
        let mut candidates = Vec::new();
        for e in std::fs::read_dir(&tmp)?.flatten() {
            if e.path().join("plugin.toml").exists() {
                candidates.push(e.path());
            }
        }
        anyhow::ensure!(
            candidates.len() == 1,
            "ZIP 中必须恰好有一个 plugin.toml（根目录或唯一子目录）"
        );
        candidates.remove(0)
    };

    let m = crate::manifest::load_manifest(&manifest_dir)?;
    // 目标目录：plugins/<id 反斜线/点 → _>
    let target = plugins_dir.join(m.id.replace(['.', '/'], "_"));
    if target.exists() {
        std::fs::remove_dir_all(&target)?;
    }
    std::fs::rename(&manifest_dir, &target)?;
    // 清理解压残留
    if tmp.exists() {
        let _ = std::fs::remove_dir_all(&tmp);
    }

    // 完整性：checksums.json 存在则必须全过
    let problems = crate::manifest::verify_checksums(&target)?;
    anyhow::ensure!(
        problems.is_empty(),
        "插件包校验失败: {}",
        problems.join("; ")
    );
    log::info!("插件 {} v{} 安装到 {}", m.id, m.version, target.display());
    Ok(target)
}

/// 生成 checksums.json（打包脚本用）。
pub fn write_checksums(plugin_dir: &Path) -> anyhow::Result<()> {
    use sha2::Digest;
    let mut map = std::collections::BTreeMap::new();
    fn walk(
        dir: &Path,
        base: &Path,
        map: &mut std::collections::BTreeMap<String, String>,
    ) -> anyhow::Result<()> {
        for e in std::fs::read_dir(dir)?.flatten() {
            let p = e.path();
            if p.is_dir() {
                if p.file_name().map(|n| n == "_data").unwrap_or(false) {
                    continue;
                }
                walk(&p, base, map)?;
            } else {
                let rel = p.strip_prefix(base)?.to_string_lossy().replace('\\', "/");
                let mut h = sha2::Sha256::new();
                h.update(std::fs::read(&p)?);
                map.insert(rel, hex::encode(h.finalize()));
            }
        }
        Ok(())
    }
    walk(plugin_dir, plugin_dir, &mut map)?;
    std::fs::write(
        plugin_dir.join("checksums.json"),
        serde_json::to_string_pretty(&map)?,
    )?;
    Ok(())
}
