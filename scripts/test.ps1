# test.ps1 — 全部测试：Rust 单元/集成 + Python SDK 回环 + 可选长稳
param([switch]$Soak, [switch]$SkipAi)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = "$Root\sdk\python"

function Fail($message) {
    Write-Host $message -ForegroundColor Red
}

function Resolve-CargoExecutable {
    if (Test-Path Env:VOICE_TRANSLATOR_CARGO) {
        $override = [string]$env:VOICE_TRANSLATOR_CARGO
        if ([string]::IsNullOrWhiteSpace($override) -or $override -match '[\r\n]') {
            Fail "VOICE_TRANSLATOR_CARGO 必须指向单一 cargo 可执行文件"; exit 1
        }
        try { $resolved = @(Resolve-Path -LiteralPath $override -ErrorAction Stop) }
        catch { Fail "VOICE_TRANSLATOR_CARGO 不存在：$override"; exit 1 }
        if ($resolved.Count -ne 1 -or -not (Test-Path -LiteralPath $resolved[0].ProviderPath -PathType Leaf)) {
            Fail "VOICE_TRANSLATOR_CARGO 必须解析为单一文件：$override"; exit 1
        }
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
if (-not (Test-Path ".venv\Scripts\python.exe" -PathType Leaf)) {
    Write-Host "缺少 .venv\Scripts\python.exe" -ForegroundColor Red
    exit 1
}

function Invoke-TestStep {
    param(
        [Parameter(Mandatory = $true)][string]$Step,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )
    & $Command
    $nativeExit = $LASTEXITCODE
    if ($nativeExit -ne 0) {
        Write-Host "`n$Step 失败（exit $nativeExit）；停止后续测试。" -ForegroundColor Red
        exit $nativeExit
    }
}

Write-Host "=== 1/4 Rust 单元 + 集成测试 ===" -ForegroundColor Cyan
Invoke-TestStep "Rust 单元 + 集成测试" { & $cargoExe test --locked --workspace --exclude voice-studio-desktop }

Write-Host "`n=== 2/4 桌面宿主完整测试（lib + 标准 integration targets）===" -ForegroundColor Cyan
Invoke-TestStep "桌面宿主完整测试" { & $cargoExe test --locked -p voice-studio-desktop }

Write-Host "`n=== 3/4 Python SDK 回环 ===" -ForegroundColor Cyan
Invoke-TestStep "Python SDK 回环" { & .\.venv\Scripts\python.exe tests\smoke_plugin_sdk.py }

if (-not $SkipAi) {
    Write-Host "`n=== 4/4 AI 管线（真实模型，约 1-2 分钟）===" -ForegroundColor Cyan
    Invoke-TestStep "AI 管线" { & .\.venv\Scripts\python.exe tests\smoke_ai_pipeline.py }
}

if ($Soak) {
    Write-Host "`n=== 长稳 Soak（30 分钟）===" -ForegroundColor Cyan
    Invoke-TestStep "长稳 Soak" { & .\.venv\Scripts\python.exe tests\simulate.py 30 }
}

Write-Host "`n全部测试通过" -ForegroundColor Green
exit 0
