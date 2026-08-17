//! 诊断：dump 节点注册表与插件状态（无需 GUI）。
//! cargo run -p voice-studio-desktop --example registry_dump
use voice_studio_desktop_lib::state::AppState;

fn main() {
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();
    std::env::set_var("VOICE_STUDIO_DATA", root.join("app-data"));
    let state = AppState::new(root.clone()).unwrap();
    let n = state.plugins.discover();
    state.rebuild_registry();
    let reg = state.registry.read();
    println!("discovered_plugins={n}");
    for s in state.plugins.list_status() {
        println!("PLUGIN {} state={}", s.id, s.state);
    }
    println!("registry_nodes={}", reg.all().len());
    for s in reg.all() {
        println!("NODE {} [{}]", s.node_type, s.category);
    }
}
