#!/usr/bin/env bash
# 实训：清除 Synapse 残留 cross-signing / 密钥备份元数据。
# 用法：./reset-lab-crypto.sh
# 可选：./reset-lab-crypto.sh '@uXXXX:matrix.localhost'
set -euo pipefail
cd "$(dirname "$0")"
USER_ID="${1:-}"

if [[ -z "$USER_ID" ]]; then
  SQL=$(cat <<'SQL'
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
SQL
)
else
  UID_ESC=${USER_ID//\'/\'\'}
  SQL=$(cat <<SQL
BEGIN;
DELETE FROM e2e_cross_signing_signatures
 WHERE user_id = '$UID_ESC' OR target_user_id = '$UID_ESC';
DELETE FROM e2e_cross_signing_keys WHERE user_id = '$UID_ESC';
DELETE FROM e2e_room_keys WHERE user_id = '$UID_ESC';
DELETE FROM e2e_room_keys_versions WHERE user_id = '$UID_ESC';
DELETE FROM account_data
 WHERE user_id = '$UID_ESC'
   AND (
        account_data_type LIKE 'm.cross_signing.%'
     OR account_data_type LIKE 'm.secret_storage.%'
     OR account_data_type = 'm.megolm_backup.v1'
     OR account_data_type LIKE 'io.element.key_%'
   );
SELECT user_id, keytype FROM e2e_cross_signing_keys WHERE user_id = '$UID_ESC';
COMMIT;
SQL
)
fi

echo "Resetting lab crypto metadata in Synapse Postgres..."
docker compose exec -T postgres psql -U synapse -d synapse <<<"$SQL"
echo
echo "Done. Users must clear Element site data once, then SSO again:"
echo "  http://127.0.0.1:1000/element/ → 站点信息 → 清除 Cookie 与网站数据"
