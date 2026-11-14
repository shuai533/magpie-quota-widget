# Magpie Quota Widget - uninstaller
# 用法: powershell -ExecutionPolicy Bypass -File uninstall.ps1
$ErrorActionPreference = 'SilentlyContinue'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Definition
Write-Host ''
Write-Host '  Magpie Quota Widget 卸载' -ForegroundColor Cyan

# 1. 停掉守护和浮窗
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and ($_.CommandLine -like '*widget_guard.py*' -or $_.CommandLine -like '*quota_widget.py*')
} | ForEach-Object {
    Stop-Process -Id $_.ProcessId -Force
    Write-Host ('  已停止进程 ' + $_.ProcessId)
}

# 2. 删掉开机自启和桌面快捷方式
$startup = [Environment]::GetFolderPath('Startup')
$lnk = Join-Path $startup 'MagpieQuotaWidget.lnk'
if (Test-Path -LiteralPath $lnk) {
    Remove-Item -LiteralPath $lnk -Force
    Write-Host '  已删除开机自启'
}

$desktop = [Environment]::GetFolderPath('Desktop')
$openCmd = Join-Path $desktop '打开额度浮窗.cmd'
if (Test-Path -LiteralPath $openCmd) {
    Remove-Item -LiteralPath $openCmd -Force
    Write-Host '  已删除桌面快捷方式'
}

Write-Host ''
Write-Host '  完成。源码和配置还在本目录，想彻底清掉就直接删文件夹。' -ForegroundColor DarkGray
Write-Host ''
