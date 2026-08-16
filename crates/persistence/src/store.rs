//! Store：类型化的数据库访问层。
use rusqlite::{params, OptionalExtension};
use serde::{Deserialize, Serialize};

pub struct Store {
    pub conn: parking_lot::Mutex<rusqlite::Connection>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PipelineRow {
    pub id: String,
    pub name: String,
    pub graph_json: String,
    pub updated_at: String,
    pub is_default: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoiceProfileRow {
    pub id: String,
    pub name: String,
    pub ref_path: String,
    pub ref_text: String,
    pub style_json: String,
    pub tags: String,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelRow {
    pub model_id: String,
    pub plugin_id: String,
    pub local_path: Option<String>,
    pub size_bytes: i64,
    pub license: String,
    pub verified: bool,
    pub last_used_at: Option<String>,
}

impl Store {
    // ---------- settings ----------
    pub fn get_setting(&self, key: &str) -> Option<String> {
        self.conn.lock().query_row("SELECT value FROM settings WHERE key=?1", params![key], |r| r.get(0))
            .optional().ok().flatten()
    }

    pub fn set_setting(&self, key: &str, value: &str) -> anyhow::Result<()> {
        self.conn.lock().execute(
            "INSERT INTO settings (key, value) VALUES (?1, ?2)
             ON CONFLICT(key) DO UPDATE SET value=?2", params![key, value])?;
        Ok(())
    }

    // ---------- pipelines ----------
    pub fn save_pipeline(&self, id: &str, name: &str, graph_json: &str, is_default: bool) -> anyhow::Result<()> {
        self.conn.lock().execute(
            "INSERT INTO pipelines (id, name, graph_json, updated_at, is_default)
             VALUES (?1, ?2, ?3, ?4, ?5)
             ON CONFLICT(id) DO UPDATE SET name=?2, graph_json=?3, updated_at=?4, is_default=?5",
            params![id, name, graph_json, chrono::Utc::now().to_rfc3339(), is_default as i64])?;
        if is_default {
            self.conn.lock().execute(
                "UPDATE pipelines SET is_default=0 WHERE id<>?1", params![id])?;
        }
        Ok(())
    }

    pub fn list_pipelines(&self) -> Vec<PipelineRow> {
        let conn = self.conn.lock();
        let mut stmt = conn.prepare("SELECT id, name, graph_json, updated_at, is_default FROM pipelines ORDER BY updated_at DESC").unwrap();
        stmt.query_map([], |r| Ok(PipelineRow {
            id: r.get(0)?, name: r.get(1)?, graph_json: r.get(2)?,
            updated_at: r.get(3)?, is_default: r.get::<_, i64>(4)? != 0,
        })).unwrap().flatten().collect()
    }

    pub fn delete_pipeline(&self, id: &str) -> anyhow::Result<()> {
        self.conn.lock().execute("DELETE FROM pipelines WHERE id=?1", params![id])?;
        Ok(())
    }

    pub fn default_pipeline(&self) -> Option<PipelineRow> {
        self.conn.lock().query_row(
            "SELECT id, name, graph_json, updated_at, is_default FROM pipelines WHERE is_default=1",
            [], |r| Ok(PipelineRow {
                id: r.get(0)?, name: r.get(1)?, graph_json: r.get(2)?,
                updated_at: r.get(3)?, is_default: true,
            })).optional().ok().flatten()
    }

    /// last_known_good（二十二.）
    pub fn set_last_known_good(&self, graph_json: &str) -> anyhow::Result<()> {
        self.set_setting("last_known_good_pipeline", graph_json)
    }

    pub fn last_known_good(&self) -> Option<String> {
        self.get_setting("last_known_good_pipeline")
    }

    /// 上次会话状态：正常退出写 "clean"，异常退出后读到非 clean → 安全模式提示。
    pub fn mark_session(&self, state: &str) -> anyhow::Result<()> {
        self.set_setting("last_session_state", state)
    }

    pub fn last_session_state(&self) -> String {
        self.get_setting("last_session_state").unwrap_or_else(|| "unknown".into())
    }

    // ---------- voice profiles ----------
    pub fn save_voice_profile(&self, p: &VoiceProfileRow) -> anyhow::Result<()> {
        self.conn.lock().execute(
            "INSERT INTO voice_profiles (id, name, ref_path, ref_text, style_json, tags, created_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
             ON CONFLICT(id) DO UPDATE SET name=?2, ref_path=?3, ref_text=?4, style_json=?5, tags=?6",
            params![p.id, p.name, p.ref_path, p.ref_text, p.style_json, p.tags, p.created_at])?;
        Ok(())
    }

    pub fn list_voice_profiles(&self) -> Vec<VoiceProfileRow> {
        let conn = self.conn.lock();
        let mut stmt = conn.prepare("SELECT id, name, ref_path, ref_text, style_json, tags, created_at FROM voice_profiles ORDER BY name").unwrap();
        stmt.query_map([], |r| Ok(VoiceProfileRow {
            id: r.get(0)?, name: r.get(1)?, ref_path: r.get(2)?, ref_text: r.get(3)?,
            style_json: r.get(4)?, tags: r.get(5)?, created_at: r.get(6)?,
        })).unwrap().flatten().collect()
    }

    pub fn delete_voice_profile(&self, id: &str) -> anyhow::Result<()> {
        self.conn.lock().execute("DELETE FROM voice_profiles WHERE id=?1", params![id])?;
        Ok(())
    }

    // ---------- models ----------
    pub fn upsert_model(&self, m: &ModelRow) -> anyhow::Result<()> {
        self.conn.lock().execute(
            "INSERT INTO models (model_id, plugin_id, local_path, size_bytes, license, verified, last_used_at)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
             ON CONFLICT(model_id) DO UPDATE SET plugin_id=?2, local_path=?3, size_bytes=?4, license=?5, verified=?6",
            params![m.model_id, m.plugin_id, m.local_path, m.size_bytes, m.license, m.verified as i64, m.last_used_at])?;
        Ok(())
    }

    pub fn list_models(&self) -> Vec<ModelRow> {
        let conn = self.conn.lock();
        let mut stmt = conn.prepare("SELECT model_id, plugin_id, local_path, size_bytes, license, verified, last_used_at FROM models").unwrap();
        stmt.query_map([], |r| Ok(ModelRow {
            model_id: r.get(0)?, plugin_id: r.get(1)?, local_path: r.get(2)?,
            size_bytes: r.get(3)?, license: r.get(4)?,
            verified: r.get::<_, i64>(5)? != 0, last_used_at: r.get(6)?,
        })).unwrap().flatten().collect()
    }

    pub fn delete_model(&self, model_id: &str) -> anyhow::Result<()> {
        self.conn.lock().execute("DELETE FROM models WHERE model_id=?1", params![model_id])?;
        Ok(())
    }

    // ---------- events / benchmarks ----------
    pub fn add_event(&self, kind: &str, detail: &str) {
        let _ = self.conn.lock().execute(
            "INSERT INTO recent_events (at, kind, detail) VALUES (?1, ?2, ?3)",
            params![chrono::Utc::now().to_rfc3339(), kind, detail]);
    }

    pub fn recent_events(&self, limit: u32) -> Vec<(String, String, String)> {
        let conn = self.conn.lock();
        let mut stmt = conn.prepare(
            "SELECT at, kind, detail FROM recent_events ORDER BY id DESC LIMIT ?1").unwrap();
        stmt.query_map(params![limit], |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)))
            .unwrap().flatten().collect()
    }

    pub fn save_benchmark(&self, kind: &str, results_json: &str) -> anyhow::Result<()> {
        self.conn.lock().execute(
            "INSERT INTO benchmarks (at, kind, results_json) VALUES (?1, ?2, ?3)",
            params![chrono::Utc::now().to_rfc3339(), kind, results_json])?;
        Ok(())
    }
}
