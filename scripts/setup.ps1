# scripts/setup.ps1 — Voice Studio 开发环境一键初始化
# 自动完成：系统/GPU/驱动/Rust/Node/pnpm/Python 检测、前端依赖、Rust 构建、
#           数据库初始化、内置插件安装、Smoke Test。
# 不做的事（明确）：不自动安装音频驱动、不以管理员执行不透明操作。
[CmdletBinding()]
param(
    [switch]$Offline
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    OK  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    !!  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "    XX  $m" -ForegroundColor Red }

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
        if ([string]::IsNullOrWhiteSpace($override) -or $override -match '[\r\n]') {
            Fail "VOICE_TRANSLATOR_CARGO 必须指向单一 cargo 可执行文件"
            exit 1
        }
        try {
            $resolved = @(Resolve-Path -LiteralPath $override -ErrorAction Stop)
        } catch {
            Fail "VOICE_TRANSLATOR_CARGO 不存在：$override"
            exit 1
        }
        if ($resolved.Count -ne 1 -or -not (Test-Path -LiteralPath $resolved[0].ProviderPath -PathType Leaf)) {
            Fail "VOICE_TRANSLATOR_CARGO 必须解析为单一文件：$override"
            exit 1
        }
        $application = @(Get-Command -Name $resolved[0].ProviderPath -CommandType Application -ErrorAction SilentlyContinue)
        if ($application.Count -ne 1) {
            Fail "VOICE_TRANSLATOR_CARGO 不是可执行 Application：$override"
            exit 1
        }
        return [string]$application[0].Source
    }

    $candidates = @(
        Get-Command cargo -All -CommandType Application -ErrorAction SilentlyContinue |
            ForEach-Object { [string]$_.Source } |
            Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
            Select-Object -Unique
    )
    if ($candidates.Count -eq 0) {
        Fail "未安装 Rust/Cargo；请通过 rustup 安装并加入 PATH，或设置 VOICE_TRANSLATOR_CARGO"
        exit 1
    }
    # Get-Command -All preserves PATH search order. Return exactly one string,
    # never the Source property of an array of command objects.
    return [string]$candidates[0]
}

function Get-GitExecutable {
    # Get-Command can return more than one Application when multiple PATH
    # directories contain git.  Resolve exactly one source in PATH order so
    # the call operator never receives an array.
    $gitCandidates = @(
        Get-Command git -All -CommandType Application -ErrorAction SilentlyContinue |
            ForEach-Object { [string]$_.Source }
    )
    if ($gitCandidates.Count -eq 0) { return $null }

    foreach ($pathEntry in ($env:Path -split [IO.Path]::PathSeparator)) {
        if ([string]::IsNullOrWhiteSpace($pathEntry)) { continue }
        $pathDirectory = [IO.Path]::GetFullPath($pathEntry).TrimEnd('\\')
        foreach ($candidate in $gitCandidates) {
            $candidateDirectory = [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($candidate)).TrimEnd('\\')
            if ([string]::Equals($candidateDirectory, $pathDirectory, [StringComparison]::OrdinalIgnoreCase)) {
                return [string]$candidate
            }
        }
    }

    Fail "检测到 git Application，但无法按 PATH 解析其可执行文件"
    exit 1
}

Step "1/10 系统检测"
$os = [Environment]::OSVersion.Version
Ok "Windows $($os.Major).$($os.Minor).$($os.Build)"

Step "2/10 GPU / 驱动检测"
try {
    $gpu = Get-CimInstance Win32_VideoController | Where-Object Name -match "NVIDIA|AMD|Intel" | Select-Object -First 3
    foreach ($g in $gpu) { Ok "$($g.Name)" }
} catch { Warn "GPU 检测失败（不影响 CPU 模式）" }

Step "3/10 Rust 工具链"
$cargoExe = Resolve-CargoExecutable
$env:CARGO = $cargoExe
$cargoVersion = Get-NativeVersion "cargo" { & $cargoExe --version }
Ok $cargoVersion

Step "4/10 Node / pnpm"
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { Fail "未安装 Node.js 24.x"; exit 1 }
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) { Fail "未安装 pnpm 9.15.0"; exit 1 }
$nodeVersion = Get-NativeVersion "node" { & node --version }
$pnpmVersion = Get-NativeVersion "pnpm" { & pnpm --version }
if ($nodeVersion -notmatch '^v24\.') { Fail "Node.js 版本不匹配：$nodeVersion（需要 24.x）"; exit 1 }
if ($pnpmVersion -ne '9.15.0') { Fail "pnpm 版本不匹配：$pnpmVersion（需要 9.15.0）"; exit 1 }
Ok "Node.js $nodeVersion; pnpm $pnpmVersion"

Step "5/10 Python venv（模型运行环境）"
if (-not (Test-Path ".venv\Scripts\python.exe" -PathType Leaf)) {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail "未安装 Python 3.12.x"; exit 1 }
    $pythonVersion = Get-NativeVersion "Python" { & python --version }
    if ($pythonVersion -notmatch '^Python 3\.12\.') { Fail "Python 版本不匹配：$pythonVersion（需要 3.12.x）"; exit 1 }
    Invoke-Native "创建 Python venv" { & python -m venv .venv }
}
$pythonVersion = Get-NativeVersion ".venv Python" { & .\.venv\Scripts\python.exe --version }
if ($pythonVersion -notmatch '^Python 3\.12\.') { Fail "Python 版本不匹配：$pythonVersion（需要 3.12.x）"; exit 1 }
Ok ".venv 已就绪（$pythonVersion）"
if ($Offline) {
    Invoke-Native "离线同步 Python 依赖" { & .\.venv\Scripts\python.exe -m pip install --no-index --requirement requirements.txt }
} else {
    Invoke-Native "同步 Python 依赖" { & .\.venv\Scripts\python.exe -m pip install --requirement requirements.txt }
}
Warn "torch 需单独安装 cu126 版本（见 docs/TROUBLESHOOTING.md）"

# deps/CosyVoice（Apache-2.0，git clone 获取，不入库）
$cosyVoiceCommit = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
$gitExe = Get-GitExecutable
if (-not $gitExe) { Fail "未安装 git，无法验证或获取 CosyVoice"; exit 1 }
if (-not (Test-Path "deps\CosyVoice\.git")) {
    if ($Offline) { Fail "离线模式需要预先准备 deps\CosyVoice @ $cosyVoiceCommit"; exit 1 }
    Write-Host "    克隆 CosyVoice 并检出已验证提交 $cosyVoiceCommit …"
    Invoke-Native "克隆 CosyVoice" { & $gitExe clone --filter=blob:none --no-checkout https://github.com/FunAudioLLM/CosyVoice.git deps/CosyVoice }
    Invoke-Native "检出 CosyVoice 锁定提交" { & $gitExe -C deps/CosyVoice checkout --detach $cosyVoiceCommit }
}
$actualCosyVoiceCommit = Get-NativeVersion "CosyVoice commit" { & $gitExe -C deps/CosyVoice rev-parse HEAD }
if ($actualCosyVoiceCommit -ne $cosyVoiceCommit) {
    Fail "deps\CosyVoice 为 $actualCosyVoiceCommit，需要 $cosyVoiceCommit；不自动覆盖现有副本"
    exit 1
}
if ($Offline) {
    $submoduleStatus = & $gitExe -C deps/CosyVoice submodule status --recursive
    $submoduleExit = $LASTEXITCODE
    if ($submoduleExit -ne 0 -or ($submoduleStatus | Where-Object { $_ -match '^[+-]' })) {
        Fail "离线模式下 CosyVoice 子模块未就绪"
        exit $(if ($submoduleExit -ne 0) { $submoduleExit } else { 1 })
    }
} else {
    Invoke-Native "初始化 CosyVoice 锁定子模块" { & $gitExe -C deps/CosyVoice submodule update --init --recursive }
}
if (-not (Test-Path "deps\CosyVoice\cosyvoice")) { Fail "CosyVoice 检出不完整：缺少 cosyvoice/"; exit 1 }
Ok "deps/CosyVoice @ $actualCosyVoiceCommit"

# 模型（可选，首次较大；下载脚本为官方源）
if (-not (Test-Path "models\CosyVoice3-0.5B\llm.pt")) {
    Warn "未检测到 CosyVoice3 模型。需要 AI 插件时先运行：.venv\Scripts\python.exe scripts\download_models.py --help（并阅读 docs\BUILDING.md）"
} else { Ok "模型已就位 models/" }

Step "6/10 前端依赖"
if ($Offline) {
    Invoke-Native "离线安装前端依赖" { & pnpm install --frozen-lockfile --offline }
} else {
    Invoke-Native "安装前端依赖" { & pnpm install --frozen-lockfile }
}
Ok "前端依赖完成"

Step "7/10 前端构建"
Invoke-Native "前端构建" { & pnpm --filter voice-studio-desktop build }
Ok "前端构建完成（apps/desktop/dist）"

Step "8/10 Rust 构建（首次较慢）"
if ($Offline) {
    Invoke-Native "离线 Rust 构建" { & $cargoExe build --locked --offline -p voice-studio-desktop }
} else {
    Invoke-Native "Rust 构建" { & $cargoExe build --locked -p voice-studio-desktop }
}
Ok "桌面宿主构建完成"

Step "9/10 数据目录 + 内置插件安装"
New-Item -ItemType Directory -Force -Path app-data\plugins | Out-Null
$builtin = @("examples\gain", "examples\text_replace", "examples\tone_gen",
             "examples\null_output", "examples\external_cmd",
             "ai\funasr", "ai\cosyvoice", "ai\textkit", "ai\vc_pitch")
foreach ($p in $builtin) {
    $name = Split-Path -Leaf $p
    $dst = "app-data\plugins\$name"
    if (-not (Test-Path $dst)) {
        Copy-Item -Recurse "plugins\$p" $dst
        Ok "安装插件 $name"
    }
}

Step "10/10 Smoke Test（SDK worker 回环）"
$env:PYTHONPATH = "$root\sdk\python"
Invoke-Native "Smoke Test" { & .\.venv\Scripts\python.exe tests\smoke_plugin_sdk.py }
Ok "Smoke Test 通过"

Write-Host "`n安装完成。启动：.\scripts\run.ps1" -ForegroundColor Green
