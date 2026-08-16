//! 日志初始化：文件 + 控制台，结构化字段（component/plugin/pipeline/node）。
use log::LevelFilter;
use std::io::Write;
use std::sync::Mutex;

pub fn init(log_dir: &std::path::Path, level: LevelFilter) -> anyhow::Result<()> {
    std::fs::create_dir_all(log_dir)?;
    let file = std::fs::OpenOptions::new()
        .create(true).append(true)
        .open(log_dir.join(format!("voice_{}.log", chrono::Local::now().format("%Y%m%d"))))?;
    let shared = Mutex::new(file);
    env_logger::Builder::new()
        .filter_level(level)
        .format(move |buf, record| {
            writeln!(
                buf,
                "{} {:>5} [{}] {}",
                chrono::Local::now().format("%Y-%m-%dT%H:%M:%S%.3f"),
                record.level(),
                record.target(),
                record.args()
            )
        })
        .target(env_logger::Target::Pipe(Box::new(MutexWriter(shared))))
        .try_init()
        .ok();
    Ok(())
}

struct MutexWriter(Mutex<std::fs::File>);
impl Write for MutexWriter {
    fn write(&mut self, buf: &[u8]) -> std::io::Result<usize> {
        self.0.lock().map(|mut f| f.write(buf)).unwrap_or(Ok(buf.len()))
    }
    fn flush(&mut self) -> std::io::Result<()> {
        self.0.lock().map(|mut f| f.flush()).unwrap_or(Ok(()))
    }
}
