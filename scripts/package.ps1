# package.ps1 — 打包：NSIS 安装包 + Portable ZIP + SHA-256
[CmdletBinding()]
param(
    [string]$TauriLogPath = "",
    [switch]$Offline
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

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

function Get-NativeVersion {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    $versionOutput = & $Command
    $nativeExit = $LASTEXITCODE
    if ($nativeExit -ne 0) {
        Fail "$Description 版本检测失败（exit $nativeExit）"
        exit $nativeExit
    }
    return ($versionOutput -join " ").Trim()
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

$cargoExe = Resolve-CargoExecutable
$env:CARGO = $cargoExe

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "未安装 Node.js 24.x"; exit 1 }
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { Fail "未安装 pnpm 9.15.0"; exit 1 }

$nodeVersion = Get-NativeVersion "Node.js" { & node --version }
$pnpmVersion = Get-NativeVersion "pnpm" { & pnpm --version }
$cargoVersion = Get-NativeVersion "cargo" { & $cargoExe --version }
if ($nodeVersion -notmatch '^v24\.') { Fail "Node.js 版本不匹配：$nodeVersion（需要 24.x）"; exit 1 }
if ($pnpmVersion -ne '9.15.0') { Fail "pnpm 版本不匹配：$pnpmVersion（需要 9.15.0）"; exit 1 }
Write-Host "工具链：Node.js $nodeVersion; pnpm $pnpmVersion; $cargoVersion"
if ($Offline) {
    $env:CARGO_NET_OFFLINE = "true"
    Invoke-Native "Cargo.lock 离线一致性检查" { & $cargoExe metadata --locked --offline --no-deps --format-version 1 | Out-Null }
} else {
    Invoke-Native "Cargo.lock 一致性检查" { & $cargoExe metadata --locked --no-deps --format-version 1 | Out-Null }
}

Write-Host "=== 冻结安装前端依赖 ===" -ForegroundColor Cyan
if ($Offline) {
    Invoke-Native "离线安装前端依赖" { & pnpm install --frozen-lockfile --offline }
} else {
    Invoke-Native "安装前端依赖" { & pnpm install --frozen-lockfile }
}

if ([string]::IsNullOrWhiteSpace($TauriLogPath)) {
    $TauriLogPath = Join-Path $Root "logs\tauri_build.log"
}
$tauriLogDirectory = Split-Path -Parent $TauriLogPath
if ($tauriLogDirectory) { New-Item -ItemType Directory -Force -Path $tauriLogDirectory | Out-Null }

Write-Host "=== 前端构建 ===" -ForegroundColor Cyan
Invoke-Native "前端构建" { & pnpm --filter voice-studio-desktop build }

Write-Host "`n=== Tauri Release 构建 + NSIS 安装包 ===" -ForegroundColor Cyan
# 大型模型与 Python 依赖绝不打入安装包（bundle.resources 为空）
$savedErrorActionPreference = $ErrorActionPreference
$tauriExit = $null
$pipelineSucceeded = $false
try {
    $ErrorActionPreference = "Continue"
    if ($Offline) {
        & pnpm --filter voice-studio-desktop exec tauri build --ci --runner $cargoExe -- --locked --offline 2>&1 | Tee-Object -FilePath $TauriLogPath
    } else {
        & pnpm --filter voice-studio-desktop exec tauri build --ci --runner $cargoExe -- --locked 2>&1 | Tee-Object -FilePath $TauriLogPath
    }
    $pipelineSucceeded = $?
    $tauriExit = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $savedErrorActionPreference
}
if ($null -eq $tauriExit) { Fail "Tauri/NSIS 打包未返回 native exit code"; exit 1 }
if ($tauriExit -ne 0) {
    Fail "Tauri/NSIS 打包失败（exit $tauriExit）；不回退到普通 cargo build"
    exit $tauriExit
}
if (-not $pipelineSucceeded) { Fail "Tauri 日志管道失败"; exit 1 }

$releaseExe = Join-Path $Root "target\release\voice-studio-desktop.exe"
$nsisCandidates = @(Get-ChildItem (Join-Path $Root "target\release\bundle\nsis\*.exe") -File -ErrorAction SilentlyContinue)
if (-not (Test-Path $releaseExe -PathType Leaf)) { Fail "Tauri 返回成功，但缺少 $releaseExe"; exit 1 }
if ($nsisCandidates.Count -ne 1) { Fail "Tauri 返回成功，但 NSIS 产物数量为 $($nsisCandidates.Count)（期望 1）"; exit 1 }
$nsis = $nsisCandidates[0]

Write-Host "`n=== Portable ZIP ===" -ForegroundColor Cyan
$dist = "dist-package"
if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$port = "$dist\VoiceStudio-Portable"
New-Item -ItemType Directory -Force -Path "$port" | Out-Null
Copy-Item $releaseExe $port
Copy-Item -Recurse "plugins" "$port\plugins"
Copy-Item -Recurse "sdk" "$port\sdk"
Compress-Archive -Path $port -DestinationPath "$dist\VoiceStudio-Portable.zip" -Force

Write-Host "`n=== SHA-256 ===" -ForegroundColor Cyan
$out = "# SHA-256 checksums`n"
$h1 = (Get-FileHash $nsis.FullName -Algorithm SHA256).Hash
$out += "$($nsis.Name): $h1`n"
Copy-Item $nsis.FullName $dist
$h2 = (Get-FileHash "$dist\VoiceStudio-Portable.zip" -Algorithm SHA256).Hash
$out += "VoiceStudio-Portable.zip: $h2`n"
$out | Out-File "$dist\SHA256SUMS.txt" -Encoding utf8
Write-Host $out
Write-Host "打包成功：NSIS + Portable ZIP + SHA-256 均已生成，产物位于 $dist\" -ForegroundColor Green
