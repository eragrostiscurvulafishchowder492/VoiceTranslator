fn main() -> Result<(), Box<dyn std::error::Error>> {
    let proto = "proto/voice_plugin_v1.proto";
    println!("cargo:rerun-if-changed={proto}");
    // 上级目录的 proto/（crate 位于 crates/plugin-protocol）
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../proto");
    let file = root.join("voice_plugin_v1.proto");
    let fds = protox::compile([file], [root])?;
    tonic_build::configure()
        .build_server(false)
        .build_client(true)
        .compile_fds(fds)?;
    Ok(())
}
