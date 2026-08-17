# run.ps1 - Build the locked frontend/desktop target, then start Voice Studio.
[CmdletBinding()]
param([switch]$Dev, [switch]$Offline)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = "$Root\sdk\python"
$env:VOICE_STUDIO_DATA = "$Root\app-data"

function Fail($message) {
    Write-Host "    XX  $message" -ForegroundColor Red
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    & $Command
    $nativeExit = $LASTEXITCODE
    if ($nativeExit -ne 0) {
        Fail "$Description 失败（exit $nativeExit）"
        exit $nativeExit
    }
}

function Resolve-CargoExecutable {
    if (Test-Path Env:VOICE_TRANSLATOR_CARGO) {
        $override = [string]$env:VOICE_TRANSLATOR_CARGO
        if ([string]::IsNullOrWhiteSpace($override) -or $override -match '[\r\n]') { Fail "VOICE_TRANSLATOR_CARGO 必须指向单一 cargo 可执行文件"; exit 1 }
        try { $resolved = @(Resolve-Path -LiteralPath $override -ErrorAction Stop) }
        catch { Fail "VOICE_TRANSLATOR_CARGO 不存在：$override"; exit 1 }
        if ($resolved.Count -ne 1 -or -not (Test-Path -LiteralPath $resolved[0].ProviderPath -PathType Leaf)) { Fail "VOICE_TRANSLATOR_CARGO 必须解析为单一文件：$override"; exit 1 }
        $application = @(Get-Command -Name $resolved[0].ProviderPath -CommandType Application -ErrorAction SilentlyContinue)
        if ($application.Count -ne 1) { Fail "VOICE_TRANSLATOR_CARGO 不是可执行 Application：$override"; exit 1 }
        return [string]$application[0].Source
    }
    $candidates = @(Get-Command cargo -All -CommandType Application -ErrorAction SilentlyContinue |
        ForEach-Object { [string]$_.Source } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object -Unique)
    if ($candidates.Count -eq 0) { Fail "未安装 Cargo；请通过 rustup 安装并加入 PATH，或设置 VOICE_TRANSLATOR_CARGO"; exit 1 }
    return [string]$candidates[0]
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "未安装 Node.js 24.x"; exit 1 }
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { Fail "未安装 pnpm 9.15.0"; exit 1 }
$cargoExe = Resolve-CargoExecutable
$env:CARGO = $cargoExe

if ($Offline) {
    Invoke-Native "离线安装前端依赖" { & pnpm install --frozen-lockfile --offline }
} else {
    Invoke-Native "安装前端依赖" { & pnpm install --frozen-lockfile }
}

if ($Dev) {
    if ($Offline) {
        Invoke-Native "启动离线 Tauri 开发模式" { & pnpm --filter voice-studio-desktop exec tauri dev --runner $cargoExe -- --locked --offline }
    } else {
        Invoke-Native "启动 Tauri 开发模式" { & pnpm --filter voice-studio-desktop exec tauri dev --runner $cargoExe -- --locked }
    }
    exit 0
} else {
    Invoke-Native "前端构建" { & pnpm --filter voice-studio-desktop build }
    if ($Offline) {
        Invoke-Native "离线 Rust release 构建" { & $cargoExe build --locked --offline --release -p voice-studio-desktop }
    } else {
        Invoke-Native "Rust release 构建" { & $cargoExe build --locked --release -p voice-studio-desktop }
    }
    $exe = Join-Path $Root "target\release\voice-studio-desktop.exe"
}

if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    Fail "构建返回成功但未生成应用：$exe"
    exit 1
}
Start-Process -FilePath $exe -WorkingDirectory $Root -ErrorAction Stop
Write-Host "Voice Studio 已启动（release）。" -ForegroundColor Green
exit 0
