# Magpie Quota Widget - installer (Windows PowerShell 5.1+)
# 用法: powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Definition
Write-Host ''
Write-Host '  Magpie Quota Widget 安装程序' -ForegroundColor Cyan
Write-Host '  -----------------------------' -ForegroundColor DarkGray

# ---------- 1. 找 Python ----------
function Find-Pythonw {
    $cands = @()
    if ($env:PYTHONW) { $cands += $env:PYTHONW }
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py) { $cands += (Join-Path (Split-Path $py.Source) 'pythonw.exe') }
    $cands += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\pythonw.exe')
    $cands += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\pythonw.exe')
    $cands += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\pythonw.exe')
    foreach ($c in $cands) {
        if ($c -and (Test-Path -LiteralPath $c)) { return $c }
    }
    $w = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($w) { return $w.Source }
    return $null
}

$pythonw = Find-Pythonw
if (-not $pythonw) {
    Write-Host '  [x] 没找到 Python。' -ForegroundColor Red
    Write-Host '      去 https://www.python.org/downloads/ 装一个（安装时勾选 tcl/tk 和 Add to PATH），再跑一次本脚本。'
    exit 1
}
Write-Host ('  [1/4] Python: ' + $pythonw) -ForegroundColor Green

# ---------- 2. 检查 tkinter ----------
$python = Join-Path (Split-Path $pythonw) 'python.exe'
if (-not (Test-Path -LiteralPath $python)) { $python = $pythonw }
$tk = & $python -c "import tkinter, sys; sys.stdout.write('ok')" 2>$null
if ($tk -ne 'ok') {
    Write-Host '  [x] 这个 Python 没有 tkinter（浮窗画不出来）。' -ForegroundColor Red
    Write-Host '      重新运行 python.org 的安装包，选 Modify -> 勾上 tcl/tk and IDLE。'
    exit 1
}
Write-Host '  [2/4] tkinter: ok' -ForegroundColor Green

# ---------- 3. 开机自启 + 桌面快捷方式 ----------
$guard = Join-Path $Here 'widget_guard.py'
$ws = New-Object -ComObject WScript.Shell

$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup 'MagpieQuotaWidget.lnk'
$sc = $ws.CreateShortcut($lnk)
$sc.TargetPath = $pythonw
$sc.Arguments = '"' + $guard + '"'
$sc.WorkingDirectory = $Here
$sc.WindowStyle = 7
$sc.Description = 'Magpie 额度浮窗'
$sc.Save()

$desktop = [Environment]::GetFolderPath('Desktop')
$openCmd = Join-Path $desktop '打开额度浮窗.cmd'
$lines = @(
    '@echo off',
    'chcp 65001 >nul',
    ('if exist "' + (Join-Path $Here 'widget_off.flag') + '" del "' + (Join-Path $Here 'widget_off.flag') + '"'),
    ('start "" "' + $pythonw + '" "' + $guard + '"'),
    'timeout /t 2 >nul'
)
Set-Content -LiteralPath $openCmd -Value $lines -Encoding UTF8
Write-Host ('  [3/4] 自启: ' + $lnk) -ForegroundColor Green
Write-Host ('        桌面: ' + $openCmd) -ForegroundColor Green

# ---------- 4. 立刻启动 ----------
Start-Process -FilePath $pythonw -ArgumentList ('"' + $guard + '"') -WorkingDirectory $Here -WindowStyle Hidden

$port = 5599
if ($env:QUOTA_WIDGET_PORT) { $port = [int]$env:QUOTA_WIDGET_PORT }
$up = $false
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 1
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $c.Connect('127.0.0.1', $port)
        $up = $true
        $c.Close()
        break
    } catch {
        $c.Dispose()
    }
}

if ($up) {
    Write-Host '  [4/4] 浮窗已启动，看屏幕右下角。' -ForegroundColor Green
} else {
    Write-Host '  [!] 没连上 ' + $port + '，可能被占用或启动失败。' -ForegroundColor Yellow
    Write-Host ('      看日志: ' + (Join-Path $Here 'quota_widget.log'))
    Write-Host '      换端口: set QUOTA_WIDGET_PORT=5601 后再跑一次'
}
Write-Host ''
Write-Host '  完成。右键浮窗 = 设置；拖动 = 移动；× = 关闭（守护不会硬拉回来，' -ForegroundColor DarkGray
Write-Host '  想再打开就双击桌面「打开额度浮窗.cmd」）。' -ForegroundColor DarkGray
Write-Host ''
