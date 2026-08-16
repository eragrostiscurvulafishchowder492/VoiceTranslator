//! 应用数据目录布局（app-data/，全部本地）。
use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct AppPaths {
    pub root: PathBuf,
}

impl Default for AppPaths {
    fn default() -> Self {
        Self::new(default_root())
    }
}

/// 默认根目录：仓库内 app-data（开发/Portable 模式）。
/// 打包后可用环境变量 VOICE_STUDIO_DATA 覆盖。
pub fn default_root() -> PathBuf {
    if let Ok(p) = std::env::var("VOICE_STUDIO_DATA") {
        return PathBuf::from(p);
    }
    // 可执行文件位于 target/... 或安装目录；向上查找仓库标志
    let mut dir = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("."));
    for _ in 0..6 {
        dir.pop();
        if dir.join("pnpm-workspace.yaml").exists() || dir.join(".git").exists() {
            return dir.join("app-data");
        }
    }
    PathBuf::from("app-data")
}

impl AppPaths {
    pub fn new(root: impl Into<PathBuf>) -> Self {
        Self { root: root.into() }
    }

    pub fn database(&self) -> PathBuf { self.root.join("database") }
    pub fn db_file(&self) -> PathBuf { self.database().join("voice_studio.db") }
    pub fn plugins(&self) -> PathBuf { self.root.join("plugins") }
    pub fn runtimes(&self) -> PathBuf { self.root.join("runtimes") }
    pub fn plugin_envs(&self) -> PathBuf { self.runtimes().join("plugin-envs") }
    pub fn models(&self) -> PathBuf { self.root.join("models") }
    pub fn references(&self) -> PathBuf { self.root.join("references") }
    pub fn pipelines(&self) -> PathBuf { self.root.join("pipelines") }
    pub fn presets(&self) -> PathBuf { self.root.join("presets") }
    pub fn logs(&self) -> PathBuf { self.root.join("logs") }
    pub fn cache(&self) -> PathBuf { self.root.join("cache") }
    pub fn temp(&self) -> PathBuf { self.root.join("temp") }
    pub fn crash_reports(&self) -> PathBuf { self.logs().join("crash") }

    pub fn ensure_all(&self) -> std::io::Result<()> {
        for d in [self.database(), self.plugins(), self.runtimes(), self.models(),
                  self.references(), self.pipelines(), self.presets(), self.logs(),
                  self.cache(), self.temp()] {
            std::fs::create_dir_all(d)?;
        }
        Ok(())
    }
}
