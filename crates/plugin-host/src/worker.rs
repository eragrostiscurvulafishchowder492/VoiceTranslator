//! Worker 进程管理：spawn、就绪等待、握手、心跳、崩溃重启（次数/退避限制）、日志采集。
use crate::manifest::PluginManifest;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

pub struct WorkerHandle {
    pub pid: u32,
    pub port: u16,
    pub started_at: Instant,
    pub child: parking_lot::Mutex<Child>,
    pub stopping: Arc<AtomicBool>,
    pub crash_count: Arc<AtomicU32>,
    pub restarts: Arc<AtomicU32>,
}

impl WorkerHandle {
    pub fn kill(&self) {
        self.stopping.store(true, Ordering::Relaxed);
        let mut c = self.child.lock();
        let _ = c.kill();
    }

    pub fn try_wait_exited(&self) -> bool {
        matches!(self.child.lock().try_wait(), Ok(Some(_)))
    }
}

pub struct SpawnConfig {
    pub python_exe: std::path::PathBuf,
    pub sdk_path: std::path::PathBuf,     // sdk/python（PYTHONPATH 注入）
    pub repo_root: std::path::PathBuf,    // AI 插件导入 app/ 需要
    pub plugin_dir: std::path::PathBuf,
    pub manifest: PluginManifest,
    pub port: u16,
    /// 额外 PYTHONPATH（manifest.runtime_requirements.extra_python_path）
    pub extra_path: Vec<std::path::PathBuf>,
}

/// 选一个空闲 TCP 端口。
pub fn free_port() -> anyhow::Result<u16> {
    let l = std::net::TcpListener::bind("127.0.0.1:0")?;
    Ok(l.local_addr()?.port())
}

/// 启动 Python Worker 进程并等待 gRPC 端口就绪。
pub fn spawn_python_worker(cfg: SpawnConfig) -> anyhow::Result<WorkerHandle> {
    let mut pythonpath = vec![cfg.sdk_path.clone(), cfg.repo_root.clone()];
    pythonpath.extend(cfg.extra_path.iter().cloned());
    let pp = std::env::join_paths(pythonpath.iter())
        .map_err(|e| anyhow::anyhow!("join path: {e}"))?;

    let mut cmd = Command::new(&cfg.python_exe);
    cmd.arg("-m").arg("voice_plugin_sdk.server")
        .arg("--manifest-dir").arg(&cfg.plugin_dir)
        .arg("--port").arg(cfg.port.to_string())
        .env("PYTHONPATH", pp)
        .env("PYTHONUNBUFFERED", "1")
        .env("VOICE_PLUGIN_ID", &cfg.manifest.id)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .current_dir(&cfg.plugin_dir);

    // 进程独立性：宿主退出后 worker 不悬挂
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NEW_PROCESS_GROUP: u32 = 0x00000200;
        cmd.creation_flags(CREATE_NEW_PROCESS_GROUP);
    }

    let mut child = cmd.spawn().map_err(|e| anyhow::anyhow!("spawn worker 失败: {e}"))?;
    let pid = child.id();

    // 日志采集线程（stdout/stderr 合并进内存环形缓冲，由 manager 持有）
    if let Some(out) = child.stdout.take() {
        std::thread::spawn(move || collect_logs(out, "stdout"));
    }
    if let Some(err) = child.stderr.take() {
        std::thread::spawn(move || collect_logs(err, "stderr"));
    }

    // 等待端口就绪（最多 120s —— 大模型插件加载慢）
    let deadline = Instant::now() + Duration::from_secs(120);
    let addr = format!("127.0.0.1:{}", cfg.port);
    while Instant::now() < deadline {
        if std::net::TcpStream::connect_timeout(&addr.parse()?, Duration::from_millis(300)).is_ok() {
            return Ok(WorkerHandle {
                pid, port: cfg.port, started_at: Instant::now(),
                child: parking_lot::Mutex::new(child),
                stopping: Arc::new(AtomicBool::new(false)),
                crash_count: Arc::new(AtomicU32::new(0)),
                restarts: Arc::new(AtomicU32::new(0)),
            });
        }
        if let Ok(Some(_)) = child.try_wait() {
            anyhow::bail!("worker 进程提前退出（pid={pid}），查看插件日志");
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    let _ = child.kill();
    anyhow::bail!("worker 启动超时（120s）")
}

fn collect_logs<R: std::io::Read + Send + 'static>(mut r: R, tag: &'static str) {
    use std::io::Read;
    let mut buf = [0u8; 4096];
    loop {
        match r.read(&mut buf) {
            Ok(0) | Err(_) => break,
            Ok(n) => {
                let s = String::from_utf8_lossy(&buf[..n]);
                for line in s.lines() {
                    log::info!(target: "plugin", "[{tag}] {line}");
                }
            }
        }
    }
}

/// 崩溃重启决策：指数退避 1s→2s→4s→8s→16s；10 分钟窗口内超过 5 次则放弃。
pub struct RestartPolicy {
    pub max_crashes: u32,
    pub window: Duration,
    pub base_delay: Duration,
    crashes: Vec<Instant>,
}

impl Default for RestartPolicy {
    fn default() -> Self {
        Self { max_crashes: 5, window: Duration::from_secs(600), base_delay: Duration::from_secs(1), crashes: Vec::new() }
    }
}

impl RestartPolicy {
    /// 返回 None = 达到崩溃上限，不再重启。
    pub fn next_delay(&mut self) -> Option<Duration> {
        let now = Instant::now();
        self.crashes.retain(|t| now.duration_since(*t) < self.window);
        if self.crashes.len() as u32 >= self.max_crashes {
            return None;
        }
        self.crashes.push(now);
        let n = self.crashes.len().saturating_sub(1);
        Some(self.base_delay * (1u32 << n.min(4)))
    }
}
