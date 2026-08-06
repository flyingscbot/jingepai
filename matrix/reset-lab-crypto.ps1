# 实训：清除 Synapse 上残留的 cross-signing / 密钥备份元数据，
# 避免客户端因旧加密身份不断弹出「验证此设备」。
# 用法（在 matrix 目录）：.\reset-lab-crypto.ps1
# 可选：.\reset-lab-crypto.ps1 -UserId "@uXXXX:matrix.localhost"
# 清除后请用户在浏览器清一次站点数据并重新 SSO 登录。

param(
    [string]$UserId = ""
)

$ErrorActionPreference = "Stop"
$docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
if (-not (Test-Path $docker)) { $docker = "docker" }

if ([string]::IsNullOrWhiteSpace($UserId)) {
    $sql = @"
BEGIN;
DELETE FROM e2e_cross_signing_signatures;
DELETE FROM e2e_cross_signing_keys;
DELETE FROM e2e_room_keys;
DELETE FROM e2e_room_keys_versions;
DELETE FROM account_data
 WHERE account_data_type LIKE 'm.cross_signing.%'
    OR account_data_type LIKE 'm.secret_storage.%'
    OR account_data_type = 'm.megolm_backup.v1'
    OR account_data_type LIKE 'io.element.key_%';
SELECT 'cross_signing_keys' AS t, COUNT(*)::text AS n FROM e2e_cross_signing_keys
UNION ALL
SELECT 'account_data_crypto', COUNT(*)::text FROM account_data
 WHERE account_data_type LIKE 'm.cross_signing.%'
    OR account_data_type LIKE 'm.secret_storage.%'
    OR account_data_type = 'm.megolm_backup.v1';
COMMIT;
"@
} else {
    $uid = $UserId.Replace("'", "''")
    $sql = @"
BEGIN;
DELETE FROM e2e_cross_signing_signatures
 WHERE user_id = '$uid' OR target_user_id = '$uid';
DELETE FROM e2e_cross_signing_keys WHERE user_id = '$uid';
DELETE FROM e2e_room_keys WHERE user_id = '$uid';
DELETE FROM e2e_room_keys_versions WHERE user_id = '$uid';
DELETE FROM account_data
 WHERE user_id = '$uid'
   AND (
        account_data_type LIKE 'm.cross_signing.%'
     OR account_data_type LIKE 'm.secret_storage.%'
     OR account_data_type = 'm.megolm_backup.v1'
     OR account_data_type LIKE 'io.element.key_%'
   );
SELECT user_id, keytype FROM e2e_cross_signing_keys WHERE user_id = '$uid';
COMMIT;
"@
}

Write-Host "Resetting lab crypto metadata in Synapse Postgres..."
$sql | & $docker compose exec -T postgres psql -U synapse -d synapse
if ($LASTEXITCODE -ne 0) { throw "psql failed" }

Write-Host @"

Done.
Users must clear FluffyChat site data once, then login again via JinGePi SSO:
  Open http://127.0.0.1:1000/fluffychat/
  -> site info (lock icon) -> Cookies and site data -> Clear data
"@
