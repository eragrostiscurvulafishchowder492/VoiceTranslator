//! 预热：逐个启动轻量插件完成握手并把节点类型写入 DB 缓存，
//! 使编辑器在插件未运行时也能加载/校验预置管线。
//! cargo run -p voice-studio-desktop --example prime_plugins [-- --only <id>]
use voice_studio_desktop_lib::state::AppState;

fn main() {
    let only: Option<String> = std::env::args()
        .skip(1)
        .skip_while(|a| a != "--only")
        .nth(1);
    let root = std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .ancestors()
        .nth(3)
        .unwrap()
        .to_path_buf();
    std::env::set_var("VOICE_STUDIO_DATA", root.join("app-data"));
    let state = AppState::new(root).unwrap();
    state.plugins.discover();

    // 轻量插件（无 GPU 依赖，握手即缓存节点类型）
    let light = [
        "org.voicestudio.textkit",
        "org.voicestudio.vcpitch",
        "org.voicestudio.gain",
        "org.voicestudio.textreplace",
        "org.voicestudio.nullout",
        "org.voicestudio.extcmd",
        "org.voicestudio.tonegen",
    ];
    let mut ok = 0;
    for id in light {
        if let Some(o) = &only {
            if !id.contains(o) {
                continue;
            }
        }
        // isolated 插件：先确保独立环境存在
        if !state.plugins.env_exists(id) {
            match state.plugins.prepare_env(id) {
                Ok((ms, _)) => println!("env created for {id} in {ms}ms"),
                Err(e) => {
                    println!("env 创建失败 {id}: {e}");
                    continue;
                }
            }
        }
        print!("prime {id} ... ");
        match state.plugins.start_plugin(id) {
            Ok(_) => {
                state.rebuild_registry();
                state.plugins.stop_plugin(id).ok();
                println!("OK");
                ok += 1;
            }
            Err(e) => println!("失败: {e}"),
        }
    }
    state.rebuild_registry();
    println!(
        "完成：{ok} 个插件节点已缓存；注册表现有 {} 个节点",
        state.registry.read().all().len()
    );
}
