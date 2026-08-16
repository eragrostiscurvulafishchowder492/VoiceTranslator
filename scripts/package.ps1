# package.ps1 — 打包：NSIS 安装包 + Portable ZIP + SHA-256
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (Test-Path "D:\_toolchains\cargo\bin\cargo.exe") {
    $env:Path = "D:\_toolchains\cargo\bin;" + $env:Path
    $env:CARGO_HOME = "D:\_toolchains\cargo"; $env:RUSTUP_HOME = "D:\_toolchains\rustup"
}

Write-Host "=== 前端构建 ===" -ForegroundColor Cyan
pnpm --filter voice-studio-desktop build

Write-Host "`n=== Tauri Release 构建 + NSIS 安装包 ===" -ForegroundColor Cyan
# 大型模型与 Python 依赖绝不打入安装包（bundle.resources 为空）
cargo tauri build 2>&1 | Tee-Object -FilePath logs\tauri_build.log
if ($LASTEXITCODE -ne 0) {
    Write-Host "cargo tauri 不可用时回退：cargo build --release" -ForegroundColor Yellow
    cargo build --release -p voice-studio-desktop
}

Write-Host "`n=== Portable ZIP ===" -ForegroundColor Cyan
$dist = "dist-package"
if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$port = "$dist\VoiceStudio-Portable"
New-Item -ItemType Directory -Force -Path "$port" | Out-Null
Copy-Item "target\release\voice-studio-desktop.exe" $port
Copy-Item -Recurse "plugins" "$port\plugins"
Copy-Item -Recurse "sdk" "$port\sdk"
Compress-Archive -Path $port -DestinationPath "$dist\VoiceStudio-Portable.zip" -Force

Write-Host "`n=== SHA-256 ===" -ForegroundColor Cyan
$out = "# SHA-256 校验（生成于 $(Get-Date -Format 'yyyy-MM-dd HH:mm')）`n"
$nsis = Get-ChildItem "target\release\bundle\nsis\*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if ($nsis) {
    $h1 = (Get-FileHash $nsis.FullName -Algorithm SHA256).Hash
    $out += "$($nsis.Name): $h1`n"
    Copy-Item $nsis.FullName $dist
}
$h2 = (Get-FileHash "$dist\VoiceStudio-Portable.zip" -Algorithm SHA256).Hash
$out += "VoiceStudio-Portable.zip: $h2`n"
$out | Out-File "$dist\SHA256SUMS.txt" -Encoding utf8
Write-Host $out
Write-Host "打包产物位于 $dist\" -ForegroundColor Green
