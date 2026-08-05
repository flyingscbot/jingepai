# 实训：创建 Synapse 管理员账号并缓存 access_token，供金格改用户名时同步 Matrix displayname。
# 用法（在 matrix 目录）：.\bootstrap-admin.ps1
# 也可直接设环境变量 SYNAPSE_ADMIN_ACCESS_TOKEN=...

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root "venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

Set-Location $root
Write-Host "Ensuring Synapse admin token via Flask helper..."
& $py -c "import logging,sys; logging.basicConfig(level=logging.INFO); import synapse_admin; tok=synapse_admin.ensure_admin_token(); print('OK' if tok else 'FAIL', 'token_len=', len(tok or '')); sys.exit(0 if tok else 1)"

if ($LASTEXITCODE -ne 0) {
    Write-Host @"

Failed. Check:
  1) Synapse is up: docker compose ps
  2) registration_shared_secret matches auth_config / homeserver.yaml
  3) If @jingepi-admin already exists without token file, either:
     - Set SYNAPSE_ADMIN_ACCESS_TOKEN to a known admin token, or
     - Delete the Matrix user and re-run this script
"@
    exit 1
}

Write-Host @"

Admin token cached at matrix/data/jingepi-admin.access_token (gitignored).
Flask /api/settings/username will now push displayname via Admin API.
"@
