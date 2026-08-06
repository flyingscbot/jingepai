# Windows 快捷方式：核心逻辑在 start_with_domain.py（跨平台）。
#
# 用法（在仓库根）：
#   .\start_with_domain.ps1
#   .\start_with_domain.ps1 -SkipCompose
#   .\start_with_domain.ps1 -SkipApply
#   .\start_with_domain.ps1 -NoFlask
#
# 其它系统请用：
#   python start_with_domain.py
#   或 ./start_with_domain.sh

param(
    [switch]$SkipCompose,
    [switch]$SkipApply,
    [switch]$NoFlask
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$py = Join-Path $Root "venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $py)) {
    $py = "python"
}

$argv = @()
if ($SkipCompose) { $argv += "--skip-compose" }
if ($SkipApply) { $argv += "--skip-apply" }
if ($NoFlask) { $argv += "--no-flask" }

& $py (Join-Path $Root "start_with_domain.py") @argv
exit $LASTEXITCODE
