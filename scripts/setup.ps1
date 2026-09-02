# setup.ps1 · 一键环境初始化
# 用法: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# 功能: 检查前置依赖 -> 后端 uv sync -> 前端 npm install -> 验证
# 说明: 语音克隆子服务(services/clone)使用独立环境，不包含在本脚本中。
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok([string]$msg)   { Write-Host "    [ok] $msg" -ForegroundColor Green }
function Fail([string]$msg) { Write-Host "[x] $msg" -ForegroundColor Red; exit 1 }

# EAP=Stop 时，原生命令带 stderr 重定向（如 2>&1）会误抛 NativeCommandError。
# 包一层临时降级为 Continue，用完恢复。
function Use-NativeRedirect([scriptblock]$body) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $body } finally { $ErrorActionPreference = $prev }
}

# 定位可执行文件：先查 PATH，再试常见安装位置。
# 返回完整路径，调用处用函数包装直接执行——不再依赖 PATH 解析。
# 原因：安装器写入 ~/.local/bin 后旧终端 PATH 未刷新时，
# 「改 $env:PATH 再 Get-Command」在部分受限终端下仍会解析失败。
function Resolve-Tool([string]$name, [string[]]$fallbacks) {
    $src = (Get-Command $name -ErrorAction SilentlyContinue).Source
    if ($src) { return $src }
    foreach ($p in $fallbacks) {
        if (Test-Path $p) {
            Write-Host "    (i) 在 $p 找到 $name" -ForegroundColor Yellow
            return $p
        }
    }
    return $null
}

# ---------- 1. 前置依赖 ----------
Step "[1/4] 检查前置依赖"

$uvExe = Resolve-Tool "uv" @(
    (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
    (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe")
)
if (-not $uvExe) {
    Fail "未找到 uv。请先安装: winget install astral-sh.uv （或 pip install uv），安装后重开终端"
}
function uv { & $script:uvExe @args }
Ok (uv --version)

$nodeExe = Resolve-Tool "node" @(
    (Join-Path ${env:ProgramFiles} "nodejs\node.exe")
)
if (-not $nodeExe) {
    Fail "未找到 Node.js。请先安装 LTS 版本: https://nodejs.org/"
}
function node { & $script:nodeExe @args }

# npm 与 node 同目录（npm.cmd）；非常规布局时回退 PATH 查找
$npmCmd = Join-Path (Split-Path -Parent $nodeExe) "npm.cmd"
if (-not (Test-Path $npmCmd)) { $npmCmd = "npm" }
function npm { & $npmCmd @args }
Ok "node $(node -v) / npm $(npm -v)"

# ---------- 2. 后端依赖 ----------
Step "[2/4] 后端依赖 (uv sync, Python 版本由 .python-version 锁定 3.11)"
uv sync
if ($LASTEXITCODE -ne 0) { Fail "uv sync 失败，请检查网络或 uv.lock" }
Ok "后端依赖就绪"

# ---------- 3. 前端依赖 ----------
Step "[3/4] 前端依赖 (npm install)"
Push-Location (Join-Path $Root "web")
try {
    npm install
    if ($LASTEXITCODE -ne 0) { Fail "npm install 失败" }
    Ok "前端依赖就绪"
}
finally {
    Pop-Location
}

# ---------- 4. 环境验证 ----------
Step "[4/4] 环境验证 (ruff + pytest)"

uv run ruff check .
if ($LASTEXITCODE -ne 0) { Fail "ruff 检查未通过" }
Ok "ruff 通过"

Use-NativeRedirect { uv run pytest -q --no-header 2>&1 | Select-Object -Last 3 }
if ($LASTEXITCODE -ne 0) { Fail "pytest 未通过" }
Ok "pytest 通过"

# 麦克风为温和提示：缺失不中断（纯后端开发/演示播放仍可用）
$micOut = uv run python -c "import sounddevice as sd; n=sum(1 for d in sd.query_devices() if d['max_input_channels']>0); print('OK: %d input device(s)' % n if n else 'WARN: no audio input device found')"
if ($LASTEXITCODE -eq 0) {
    if ($micOut -like "WARN*") { Write-Host "    [!] 未检测到麦克风输入设备，录音功能将不可用" -ForegroundColor Yellow }
    else { Ok $micOut }
}
else {
    Write-Host "    [!] sounddevice 检测失败（可能是 PortAudio 缺失），录音功能可能不可用" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==================== 环境初始化完成 ====================" -ForegroundColor Green
Write-Host "  启动后端:  uv run python -m server.main    http://127.0.0.1:8000/docs"
Write-Host "  启动前端:  cd web && npm run dev           http://127.0.0.1:5173"
Write-Host "  提示: services/clone 语音克隆子服务使用独立环境，按需另行配置。"
