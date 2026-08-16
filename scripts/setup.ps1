# scripts/setup.ps1 — Voice Studio 开发环境一键初始化
# 自动完成：系统/GPU/驱动/Rust/Node/pnpm/Python 检测、前端依赖、Rust 构建、
#           数据库初始化、内置插件安装、Smoke Test。
# 不做的事（明确）：不自动安装音频驱动、不以管理员执行不透明操作。
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    OK  $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    !!  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "    XX  $m" -ForegroundColor Red }

Step "1/9 系统检测"
$os = [Environment]::OSVersion.Version
Ok "Windows $($os.Major).$($os.Minor).$($os.Build)"

Step "2/9 GPU / 驱动检测"
try {
    $gpu = Get-CimInstance Win32_VideoController | Where-Object Name -match "NVIDIA|AMD|Intel" | Select-Object -First 3
    foreach ($g in $gpu) { Ok "$($g.Name)" }
} catch { Warn "GPU 检测失败（不影响 CPU 模式）" }

Step "3/9 Rust 工具链"
if (Get-Command cargo -ErrorAction SilentlyContinue) {
    Ok "cargo $(cargo --version)"
} else {
    $cargoHome = "D:\_toolchains\cargo"
    if (Test-Path "$cargoHome\bin\cargo.exe") {
        $env:Path += ";$cargoHome\bin"; $env:CARGO_HOME = $cargoHome
        $env:RUSTUP_HOME = "D:\_toolchains\rustup"
        Ok "cargo (D:\_toolchains)"
    } else { Fail "未安装 Rust（rustup）"; exit 1 }
}

Step "4/9 Node / pnpm"
if (Get-Command pnpm -ErrorAction SilentlyContinue) { Ok "pnpm $(pnpm --version)" }
else { Fail "未安装 pnpm（npm i -g pnpm）"; exit 1 }

Step "5/9 Python venv（模型运行环境）"
if (Test-Path ".venv\Scripts\python.exe") { Ok ".venv 已存在" }
else {
    python -m venv .venv
    .\.venv\Scripts\pip install -r requirements.txt
    Warn "torch 需单独安装 cu126 版本（见 docs/TROUBLESHOOTING.md）"
}

# deps/CosyVoice（Apache-2.0，git clone 获取，不入库）
if (-not (Test-Path "deps\CosyVoice\cosyvoice")) {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Host "    克隆 CosyVoice（约 1 分钟）…"
        git clone --depth 1 https://github.com/FunAudioLLM/CosyVoice deps/CosyVoice
        if ($LASTEXITCODE -ne 0) { Warn "CosyVoice 克隆失败；TTS 插件需要它（可手动 clone 到 deps/CosyVoice）" }
        else { Ok "deps/CosyVoice 就绪" }
    } else { Warn "无 git：请手动 clone https://github.com/FunAudioLLM/CosyVoice 到 deps/CosyVoice" }
} else { Ok "deps/CosyVoice 已存在" }

# 模型（可选，首次较大；下载脚本为官方源）
if (-not (Test-Path "models\CosyVoice3-0.5B\llm.pt")) {
    Warn "未检测到 CosyVoice3 模型。需要 AI 插件时运行：.venv\Scripts\python.exe scripts\download_models.py"
} else { Ok "模型已就位 models/" }

Step "6/9 前端依赖"
pnpm install
Ok "前端依赖完成"

Step "7/9 Rust 构建（首次较慢）"
cargo build -p voice-studio-desktop
Ok "桌面宿主构建完成"

Step "8/9 数据目录 + 内置插件安装"
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

Step "9/9 Smoke Test（SDK worker 回环）"
$env:PYTHONPATH = "$root\sdk\python"
& .\.venv\Scripts\python.exe tests\smoke_plugin_sdk.py
if ($LASTEXITCODE -eq 0) { Ok "Smoke Test 通过" } else { Fail "Smoke Test 失败（查看上方输出）" }

Write-Host "`n安装完成。启动：.\scripts\run.ps1" -ForegroundColor Green
