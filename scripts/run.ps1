# run.ps1 - Start Voice Studio desktop app
# Default: release exe (self-contained GUI). Use -Dev for debug build (requires vite dev server).
param([switch]$Dev)
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = "$Root\sdk\python"
$env:VOICE_STUDIO_DATA = "$Root\app-data"

# Inject Rust toolchain PATH when installed on D drive
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    if (Test-Path "D:\_toolchains\cargo\bin\cargo.exe") {
        $env:Path = "D:\_toolchains\cargo\bin;" + $env:Path
        $env:CARGO_HOME = "D:\_toolchains\cargo"
        $env:RUSTUP_HOME = "D:\_toolchains\rustup"
    }
}

if ($Dev) {
    $exe = "target\debug\voice-studio-desktop.exe"
    if (-not (Test-Path $exe)) { cargo build -p voice-studio-desktop }
    Write-Host "Dev mode: make sure vite dev server is running (pnpm --filter voice-studio-desktop dev)" -ForegroundColor Yellow
    Start-Process -FilePath "$Root\$exe" -WorkingDirectory $Root
} else {
    $exe = "target\release\voice-studio-desktop.exe"
    if (-not (Test-Path $exe)) {
        Write-Host "Release build not found, building (first time takes a few minutes)..." -ForegroundColor Yellow
        cargo build --release -p voice-studio-desktop
    }
    if (Test-Path $exe) {
        Start-Process -FilePath "$Root\$exe" -WorkingDirectory $Root
        Write-Host "Voice Studio launched (release)." -ForegroundColor Green
    } else {
        Write-Host "Build failed. Run scripts\setup.ps1 first." -ForegroundColor Red
    }
}
