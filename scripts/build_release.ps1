# build_release.ps1 · 一键打包分发
# 用法: powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1
# 流程: 前端构建 -> PyInstaller 后端打包 -> 组装 voice-system/ -> 压缩 zip
# 产物: release\voice-system\（解压即用目录）与 release\voice-system.zip（分发包）
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

# 定位可执行文件：先查 PATH，再试常见安装位置（受限终端常解析不到 PATH，故保留回退）
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

$uvExe = Resolve-Tool "uv" @(
    (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
    (Join-Path $env:USERPROFILE ".cargo\bin\uv.exe")
)
if (-not $uvExe) {
    Fail "未找到 uv。请先安装: winget install astral-sh.uv，安装后重开终端"
}
function uv { & $script:uvExe @args }

# node 候选路径逐一构造：环境变量缺失时跳过该候选，不抛错。
# 优先级：NODE_EXE 环境变量 > PATH > 常见安装位置（含绿色版/托管版布局）。
$nodeFallbacks = @()
if ($env:NODE_EXE) { $nodeFallbacks += $env:NODE_EXE }
foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, "$env:LOCALAPPDATA\Programs")) {
    if ($base) { $nodeFallbacks += (Join-Path $base "nodejs\node.exe") }
}
# 绿色版/多版本管理布局：LOCALAPPDATA\hermes\node 与 .workbuddy 托管的版本目录（取版本号最大者）
$nodeFallbacks += (Join-Path $env:LOCALAPPDATA "hermes\node\node.exe")
$wbNodeRoot = Join-Path $env:USERPROFILE ".workbuddy\binaries\node\versions"
if (Test-Path $wbNodeRoot) {
    $latest = Get-ChildItem $wbNodeRoot -Directory | Sort-Object Name -Descending | Select-Object -First 1
    if ($latest) { $nodeFallbacks += (Join-Path $latest.FullName "node.exe") }
}
$nodeExe = Resolve-Tool "node" $nodeFallbacks
if (-not $nodeExe) { Fail "未找到 Node.js。请安装 LTS 版本: https://nodejs.org/ ，或设 NODE_EXE 指向 node.exe 后重试" }

# npm 与 node 同目录（npm.cmd）；非常规布局时回退 PATH 查找。
# 另备 node + npm-cli.js 直连通道：npm.cmd 是批处理，部分受限终端/沙盒
# 无法拉起 .cmd（LASTEXITCODE 保持为 null），此时经 node.exe 启动 npm-cli.js。
$nodeDir = Split-Path -Parent $nodeExe
$npmCmd = Join-Path $nodeDir "npm.cmd"
if (-not (Test-Path $npmCmd)) { $npmCmd = "npm.cmd" }
$npmCli = Join-Path $nodeDir "node_modules\npm\bin\npm-cli.js"

function Invoke-Npm {
    & $script:npmCmd @args
    if ($null -eq $LASTEXITCODE -and (Test-Path $script:npmCli)) {
        Write-Host "    (i) npm.cmd 未能启动，改用 node + npm-cli.js" -ForegroundColor Yellow
        & $script:nodeExe $script:npmCli @args
    }
}

$Release = Join-Path $Root "release"
$Stage   = Join-Path $Release "voice-system"

# ---------- 1. 前端构建 ----------
Step "[1/6] 前端构建 (npm run build)"
Push-Location (Join-Path $Root "web")
Use-NativeRedirect { Invoke-Npm run build }
$npmCode = $LASTEXITCODE
Pop-Location
if ($npmCode -ne 0) { Fail "前端构建失败 (exit $npmCode)" }
if (-not (Test-Path (Join-Path $Root "web\dist\index.html"))) { Fail "web\dist\index.html 未产出" }
Ok "web/dist 就绪"

# ---------- 2. 后端打包 ----------
Step "[2/6] PyInstaller 打包后端（首次约需数分钟）"
Use-NativeRedirect { uv sync }
if ($LASTEXITCODE -ne 0) { Fail "uv sync 失败" }
Use-NativeRedirect {
    uv run pyinstaller packaging/app.spec --noconfirm --clean `
        --distpath release/pyinstaller --workpath release/_build
}
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller 打包失败" }
$builtExe = Join-Path $Release "pyinstaller\app\app.exe"
if (-not (Test-Path $builtExe)) { Fail "未找到打包产物 app.exe" }
Ok "后端打包完成"

# ---------- 3. 组装分发目录 ----------
Step "[3/6] 组装 voice-system/"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Stage | Out-Null

# exe 与运行时（app.exe + _internal/）
Copy-Item (Join-Path $Release "pyinstaller\app\*") $Stage -Recurse -Force
# 前端静态资源（外置，由后端托管）
New-Item -ItemType Directory -Path (Join-Path $Stage "web") | Out-Null
Copy-Item (Join-Path $Root "web\dist") (Join-Path $Stage "web\dist") -Recurse -Force
Ok "已复制 app.exe 运行时与 web/dist"

# start.bat（内容纯 ASCII，规避控制台代码页问题）
$bat = @"
@echo off
rem Voice Processing System launcher
start "" "%~dp0app.exe"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8000/"
"@
[IO.File]::WriteAllText(
    (Join-Path $Stage "start.bat"),
    $bat.Replace("`n", "`r`n"),
    [Text.Encoding]::ASCII
)

# 使用说明.txt（UTF-8 带 BOM，记事本兼容）
$txt = @"
语音处理系统 · 使用说明
========================

一、启动
  1. 解压后进入 voice-system 文件夹
  2. 双击 start.bat —— 自动启动服务并打开浏览器
     （或先运行 app.exe，再手动访问 http://127.0.0.1:8000/ ）
  3. 关闭 app.exe 的控制台窗口即退出服务

二、环境要求
  - Windows 10/11 x64，无需安装 Python 或 Node.js
  - 录音/播放需要本机麦克风与扬声器（浏览器首次访问时允许权限）

三、常见问题
  - 端口占用：确保 8000 端口未被其他程序占用
  - 杀毒软件拦截：打包程序常见误报，添加信任即可
  - 无法访问：查看 app.exe 控制台窗口中的报错信息

四、说明
  - 本包不含语音克隆子服务及其模型权重（独立分发）
"@
[IO.File]::WriteAllText(
    (Join-Path $Stage "使用说明.txt"),
    $txt.Replace("`n", "`r`n"),
    [Text.UTF8Encoding]::new($true)
)
Ok "start.bat 与 使用说明.txt 已生成"

# ---------- 4. 压缩分发包 ----------
Step "[4/6] 压缩 zip"
$zip = Join-Path $Release "voice-system.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $Stage -DestinationPath $zip -CompressionLevel Optimal
Ok "release\voice-system.zip"

# ---------- 5. 清理中间产物 ----------
Step "[5/6] 清理中间产物"
foreach ($tmp in @("pyinstaller", "_build")) {
    $p = Join-Path $Release $tmp
    if (Test-Path $p) {
        Remove-Item $p -Recurse -Force
        Ok "已清理 release\$tmp"
    }
}

# ---------- 6. 完成 ----------
Step "[6/6] 完成"
$sizeMB = [math]::Round((Get-ChildItem $Stage -Recurse | Measure-Object Length -Sum).Sum / 1MB, 1)
$zipMB  = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Ok "分发目录: release\voice-system\ ($sizeMB MB)"
Ok "分发包:   release\voice-system.zip ($zipMB MB)"
