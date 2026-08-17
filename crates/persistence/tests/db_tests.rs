//! persistence 测试：迁移、管线 CRUD、last_known_good、会话状态。
use voice_persistence::{open, VoiceProfileRow};

#[test]
fn migrations_and_pipeline_crud() {
    let dir = std::env::temp_dir().join(format!("vdb_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let store = open(&dir.join("t.db")).unwrap();

    store.set_setting("k", "v").unwrap();
    assert_eq!(store.get_setting("k").as_deref(), Some("v"));

    store
        .save_pipeline("p1", "管线一", r#"{"x":1}"#, true)
        .unwrap();
    store
        .save_pipeline("p2", "管线二", r#"{"x":2}"#, false)
        .unwrap();
    let ps = store.list_pipelines();
    assert_eq!(ps.len(), 2);
    // 默认唯一
    assert_eq!(ps.iter().filter(|p| p.is_default).count(), 1);
    assert_eq!(store.default_pipeline().unwrap().id, "p1");

    store.set_last_known_good(r#"{"lg":1}"#).unwrap();
    assert_eq!(store.last_known_good().as_deref(), Some(r#"{"lg":1}"#));

    store.delete_pipeline("p1").unwrap();
    assert_eq!(store.list_pipelines().len(), 1);

    store.mark_session("running").unwrap();
    assert_eq!(store.last_session_state(), "running");
}

#[test]
fn voice_profiles_and_events() {
    let dir = std::env::temp_dir().join(format!("vdb2_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let store = open(&dir.join("t.db")).unwrap();
    store
        .save_voice_profile(&VoiceProfileRow {
            id: "vp1".into(),
            name: "我的音色".into(),
            ref_path: "x.wav".into(),
            ref_text: "".into(),
            style_json: "{}".into(),
            tags: "main".into(),
            created_at: "2026-01-01".into(),
        })
        .unwrap();
    assert_eq!(store.list_voice_profiles().len(), 1);
    store.delete_voice_profile("vp1").unwrap();
    assert!(store.list_voice_profiles().is_empty());

    store.add_event("test", "事件");
    assert_eq!(store.recent_events(10).len(), 1);
}
