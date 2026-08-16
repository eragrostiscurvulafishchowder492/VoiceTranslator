//! SQLite 持久化（二十三.）：版本化迁移 + 管线/预设/声音档案/模型/设置/基准。
use rusqlite::{params, Connection};
use std::path::Path;

pub mod store;
pub use store::{ModelRow, PipelineRow, Store, VoiceProfileRow};

/// 打开并迁移数据库。
pub fn open(db_path: &Path) -> anyhow::Result<Store> {
    if let Some(dir) = db_path.parent() { std::fs::create_dir_all(dir)?; }
    let conn = Connection::open(db_path)?;
    conn.pragma_update(None, "journal_mode", "WAL")?;
    migrate(&conn)?;
    Ok(Store { conn: parking_lot::Mutex::new(conn) })
}

const MIGRATIONS: &[&str] = &[
    // v1
    "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
     CREATE TABLE IF NOT EXISTS pipelines (id TEXT PRIMARY KEY, name TEXT NOT NULL,
         graph_json TEXT NOT NULL, updated_at TEXT NOT NULL, is_default INTEGER DEFAULT 0);
     CREATE TABLE IF NOT EXISTS presets (id TEXT PRIMARY KEY, name TEXT NOT NULL,
         graph_json TEXT NOT NULL, builtin INTEGER DEFAULT 0);
     CREATE TABLE IF NOT EXISTS voice_profiles (id TEXT PRIMARY KEY, name TEXT NOT NULL,
         ref_path TEXT NOT NULL, ref_text TEXT DEFAULT '', style_json TEXT DEFAULT '{}',
         tags TEXT DEFAULT '', created_at TEXT NOT NULL);
     CREATE TABLE IF NOT EXISTS models (model_id TEXT PRIMARY KEY, plugin_id TEXT NOT NULL,
         local_path TEXT, size_bytes INTEGER DEFAULT 0, license TEXT DEFAULT '',
         verified INTEGER DEFAULT 0, last_used_at TEXT);
     CREATE TABLE IF NOT EXISTS recent_events (id INTEGER PRIMARY KEY AUTOINCREMENT,
         at TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
     CREATE TABLE IF NOT EXISTS benchmarks (id INTEGER PRIMARY KEY AUTOINCREMENT,
         at TEXT NOT NULL, kind TEXT NOT NULL, results_json TEXT NOT NULL);
     CREATE TABLE IF NOT EXISTS session_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);",
];

fn migrate(conn: &Connection) -> anyhow::Result<()> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);")?;
    let current: i64 = conn.query_row(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations", [], |r| r.get(0))?;
    for (i, sql) in MIGRATIONS.iter().enumerate() {
        let v = (i + 1) as i64;
        if v > current {
            conn.execute_batch(sql)?;
            conn.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?1, ?2)",
                params![v, chrono::Utc::now().to_rfc3339()])?;
            log::info!("db migrated to v{v}");
        }
    }
    Ok(())
}
