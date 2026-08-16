# run.ps1 — 启动 Voice Studio 桌面应用（开发模式）
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = "$Root\sdk\python"

# Rust 在 D:\_toolchains 时注入 PATH
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    if (Test-Path "D:\_toolchains\cargo\bin\cargo.exe") {
        $env:Path = "D:\_toolchains\cargo\bin;" + $env:Path
        $env:CARGO_HOME = "D:\_toolchains\cargo"
        $env:RUSTUP_HOME = "D:\_toolchains\rustup"
    }
}

$exe = "target\debug\voice-studio-desktop.exe"
if (-not (Test-Path $exe)) {
    Write-Host "未找到 $exe，先构建…" -ForegroundColor Yellow
    cargo build -p voice-studio-desktop
}
# 指向仓库数据目录（默认已自动探测，此处显式固定开发模式路径）
$env:VOICE_STUDIO_DATA = "$Root\app-data"
& $exe
