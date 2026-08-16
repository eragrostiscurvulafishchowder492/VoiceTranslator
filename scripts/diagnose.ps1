# diagnose.ps1 — 环境诊断（生成 logs/diagnose_json.txt）
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = "$Root\sdk\python"

Write-Host "=== Voice Studio 诊断 ===" -ForegroundColor Cyan

Write-Host "`n[Rust 工具链]"
try { cargo --version } catch { Write-Host "未安装" -ForegroundColor Red }

Write-Host "`n[Node/pnpm]"
try { node --version; pnpm --version } catch { Write-Host "未安装" -ForegroundColor Red }

Write-Host "`n[Python 环境]"
& .\.venv\Scripts\python.exe scripts\diagnose.py

Write-Host "`n[音频设备]"
& .\.venv\Scripts\python.exe -c "import sounddevice as sd; [print(d['name']) for d in sd.list_devices()]"

Write-Host "`n[桌面宿主]"
if (Test-Path "target\debug\voice-studio-desktop.exe") {
    Write-Host "debug 构建存在: OK" -ForegroundColor Green
} else { Write-Host "debug 构建不存在（运行 scripts\setup.ps1）" -ForegroundColor Yellow }

Write-Host "`n[数据库]"
if (Test-Path "app-data\database\voice_studio.db") { Write-Host "app-data\database\voice_studio.db OK" -ForegroundColor Green }
else { Write-Host "首次运行应用时创建" -ForegroundColor Yellow }

Write-Host "`n[插件]"
Get-ChildItem app-data\plugins -Directory -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "  $($_.Name)" }
