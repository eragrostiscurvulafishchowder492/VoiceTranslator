//! plugin-host 测试：manifest 校验、协议协商、ZIP 安装（含 zip-slip 防护）、重启退避。
use std::io::Write as _;
use voice_plugin_host::manifest::{load_manifest, verify_checksums, PluginManifest};

fn repo_root() -> std::path::PathBuf {
    let mut d = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    d.pop();
    d.pop();
    d
}

#[test]
fn manifest_parse_and_validate() {
    let m = load_manifest(&repo_root().join("plugins/examples/gain")).unwrap();
    assert_eq!(m.id, "org.voicestudio.gain");
    assert_eq!(m.runtime, "python");
    assert_eq!(m.entrypoint, "plugin_impl:create_plugin");
    m.validate().unwrap();
}

#[test]
fn manifest_rejects_unknown_permission() {
    let r = PluginManifest::parse_toml(r#"
id = "org.x.y"
name = "X"
version = "1.0"
api_version = "1.0"
runtime = "python"
entrypoint = "a:b"
permissions = ["superuser"]
"#);
    assert!(r.is_err(), "未知权限必须被拒绝（解析期拒绝）: {r:?}");
}

#[test]
fn api_version_major_negotiation() {
    let m = PluginManifest::parse_toml(r#"
id = "org.x.y"
name = "X"
version = "1.0"
api_version = "1.4"
runtime = "python"
entrypoint = "a:b"
"#).unwrap();
    assert!(m.api_compatible("1.0"));  // 主版本一致
    assert!(!m.api_compatible("2.0")); // 主版本不同 → 拒绝
}

#[test]
fn install_zip_roundtrip_and_checksum() {
    let tmp = std::env::temp_dir().join(format!("vph_{}", std::process::id()));
    std::fs::create_dir_all(&tmp).unwrap();
    let plugins_dir = tmp.join("plugins");
    std::fs::create_dir_all(&plugins_dir).unwrap();
    // 构造插件 ZIP
    let zip_path = tmp.join("p.zip");
    {
        let f = std::fs::File::create(&zip_path).unwrap();
        let mut w = zip::ZipWriter::new(f);
        w.start_file("plugin.toml", zip::write::SimpleFileOptions::default()).unwrap();
        w.write_all(b"id = \"org.test.zipper\"\nname = \"Z\"\nversion = \"1.0\"\napi_version = \"1.0\"\nruntime = \"python\"\nentrypoint = \"a:b\"\n").unwrap();
        w.start_file("python/a.py", zip::write::SimpleFileOptions::default()).unwrap();
        w.write_all(b"print('hi')\n").unwrap();
        w.finish().unwrap();
    }
    let target = voice_plugin_host::install::install_zip(&plugins_dir, &zip_path).unwrap();
    assert!(target.join("plugin.toml").exists());
    let m = load_manifest(&target).unwrap();
    assert_eq!(m.id, "org.test.zipper");
    // checksums 不存在 → 空问题列表
    assert!(verify_checksums(&target).unwrap().is_empty());
}

#[test]
fn install_zip_rejects_path_traversal() {
    let tmp = std::env::temp_dir().join(format!("vph2_{}", std::process::id()));
    std::fs::create_dir_all(&tmp).unwrap();
    let zip_path = tmp.join("evil.zip");
    {
        let f = std::fs::File::create(&zip_path).unwrap();
        let mut w = zip::ZipWriter::new(f);
        w.start_file("../evil.txt", zip::write::SimpleFileOptions::default()).unwrap();
        w.write_all(b"pwn").unwrap();
        w.finish().unwrap();
    }
    let err = voice_plugin_host::install::install_zip(&tmp, &zip_path);
    assert!(err.is_err(), "zip-slip 路径必须被拒绝");
    assert!(!tmp.parent().unwrap().join("evil.txt").exists());
}

#[test]
fn restart_policy_backoff_and_limit() {
    let mut p = voice_plugin_host::worker::RestartPolicy::default();
    let d1 = p.next_delay().unwrap();
    let d2 = p.next_delay().unwrap();
    assert!(d2 > d1, "退避应递增: {d1:?} → {d2:?}");
    // 次数超限 → None（不再重启）
    for _ in 0..5 { let _ = p.next_delay(); }
    assert!(p.next_delay().is_none());
}
