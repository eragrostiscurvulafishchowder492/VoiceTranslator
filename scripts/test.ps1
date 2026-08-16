# test.ps1 — 全部测试：Rust 单元/集成 + Python SDK 回环 + 可选长稳
param([switch]$Soak, [switch]$SkipAi)

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = "$Root\sdk\python"
if (Test-Path "D:\_toolchains\cargo\bin\cargo.exe") {
    $env:Path = "D:\_toolchains\cargo\bin;" + $env:Path
    $env:CARGO_HOME = "D:\_toolchains\cargo"; $env:RUSTUP_HOME = "D:\_toolchains\rustup"
}

$fail = 0

Write-Host "=== 1/4 Rust 单元 + 集成测试 ===" -ForegroundColor Cyan
cargo test --workspace --exclude voice-studio-desktop
if ($LASTEXITCODE -ne 0) { $fail = 1 }

Write-Host "`n=== 2/4 桌面宿主库测试（含插件生命周期集成）===" -ForegroundColor Cyan
cargo test -p voice-studio-desktop --lib
if ($LASTEXITCODE -ne 0) { $fail = 1 }

Write-Host "`n=== 3/4 Python SDK 回环 ===" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe tests\smoke_plugin_sdk.py
if ($LASTEXITCODE -ne 0) { $fail = 1 }

if (-not $SkipAi) {
    Write-Host "`n=== 4/4 AI 管线（真实模型，约 1-2 分钟）===" -ForegroundColor Cyan
    & .\.venv\Scripts\python.exe tests\smoke_ai_pipeline.py
    if ($LASTEXITCODE -ne 0) { $fail = 1 }
}

if ($Soak) {
    Write-Host "`n=== 长稳 Soak（30 分钟）===" -ForegroundColor Cyan
    & .\.venv\Scripts\python.exe tests\simulate.py 30
}

if ($fail -eq 0) { Write-Host "`n全部测试通过" -ForegroundColor Green; exit 0 }
else { Write-Host "`n存在失败" -ForegroundColor Red; exit 1 }
