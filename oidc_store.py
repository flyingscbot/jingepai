"""OIDC / OAuth2 持久化（SQLite，与 users.db 同库）。"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

import user_db
from auth_config import (
    OIDC_MATRIX_CLIENT_ID,
    OIDC_MATRIX_CLIENT_SECRET,
    OIDC_MATRIX_REDIRECT_URIS,
)


def init_oidc_tables() -> None:
    with user_db.get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS oauth2_clients (
                client_id TEXT PRIMARY KEY,
                client_secret TEXT NOT NULL,
                client_name TEXT NOT NULL,
                redirect_uris TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'openid profile',
                grant_types TEXT NOT NULL DEFAULT 'authorization_code',
                response_types TEXT NOT NULL DEFAULT 'code',
                token_endpoint_auth_method TEXT NOT NULL DEFAULT 'client_secret_post'
            );

            CREATE TABLE IF NOT EXISTS oauth2_codes (
                code TEXT PRIMARY KEY,
                client_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                redirect_uri TEXT NOT NULL,
                scope TEXT,
                nonce TEXT,
                auth_time INTEGER,
                code_challenge TEXT,
                code_challenge_method TEXT,
                expires_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS oauth2_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                token_type TEXT NOT NULL DEFAULT 'Bearer',
                access_token TEXT NOT NULL UNIQUE,
                refresh_token TEXT UNIQUE,
                scope TEXT,
                revoked INTEGER NOT NULL DEFAULT 0,
                issued_at INTEGER NOT NULL,
                expires_in INTEGER NOT NULL
            );
            """
        )
        row = conn.execute(
            "SELECT 1 FROM oauth2_clients WHERE client_id = ? LIMIT 1",
            (OIDC_MATRIX_CLIENT_ID,),
        ).fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO oauth2_clients (
                    client_id, client_secret, client_name, redirect_uris,
                    scope, grant_types, response_types, token_endpoint_auth_method
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    OIDC_MATRIX_CLIENT_ID,
                    OIDC_MATRIX_CLIENT_SECRET,
                    "Matrix Synapse",
                    json.dumps(OIDC_MATRIX_REDIRECT_URIS, ensure_ascii=False),
                    "openid profile",
                    "authorization_code",
                    "code",
                    "client_secret_post",
                ),
            )
        else:
            # 同步 redirect / secret，便于改环境变量后生效
            conn.execute(
                """
                UPDATE oauth2_clients
                SET client_secret = ?, redirect_uris = ?
                WHERE client_id = ?
                """,
                (
                    OIDC_MATRIX_CLIENT_SECRET,
                    json.dumps(OIDC_MATRIX_REDIRECT_URIS, ensure_ascii=False),
                    OIDC_MATRIX_CLIENT_ID,
                ),
            )
        conn.commit()


def _client_row_to_dict(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "client_id": row["client_id"],
        "client_secret": row["client_secret"],
        "client_name": row["client_name"],
        "redirect_uris": json.loads(row["redirect_uris"]),
        "scope": row["scope"],
        "grant_types": row["grant_types"].split(),
        "response_types": row["response_types"].split(),
        "token_endpoint_auth_method": row["token_endpoint_auth_method"],
    }


def get_client(client_id: str) -> dict[str, Any] | None:
    with user_db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM oauth2_clients WHERE client_id = ? LIMIT 1",
            (client_id,),
        ).fetchone()
    return _client_row_to_dict(row)


def save_authorization_code(
    *,
    code: str,
    client_id: str,
    user_id: str,
    redirect_uri: str,
    scope: str | None,
    nonce: str | None,
    code_challenge: str | None = None,
    code_challenge_method: str | None = None,
    ttl_sec: int = 300,
) -> None:
    now = int(time.time())
    with user_db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO oauth2_codes (
                code, client_id, user_id, redirect_uri, scope, nonce,
                auth_time, code_challenge, code_challenge_method, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                code,
                client_id,
                user_id,
                redirect_uri,
                scope,
                nonce,
                now,
                code_challenge,
                code_challenge_method,
                now + ttl_sec,
            ),
        )
        conn.commit()


def get_authorization_code(code: str) -> dict[str, Any] | None:
    with user_db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM oauth2_codes WHERE code = ? LIMIT 1", (code,)
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    if int(data["expires_at"]) < int(time.time()):
        delete_authorization_code(code)
        return None
    return data


def delete_authorization_code(code: str) -> None:
    with user_db.get_conn() as conn:
        conn.execute("DELETE FROM oauth2_codes WHERE code = ?", (code,))
        conn.commit()


def pop_authorization_code(code: str) -> dict[str, Any] | None:
    data = get_authorization_code(code)
    if data:
        delete_authorization_code(code)
    return data


def save_token(
    *,
    client_id: str,
    user_id: str,
    access_token: str,
    refresh_token: str | None,
    scope: str | None,
    expires_in: int = 3600,
) -> None:
    now = int(time.time())
    with user_db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO oauth2_tokens (
                client_id, user_id, access_token, refresh_token, scope,
                issued_at, expires_in
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                client_id,
                user_id,
                access_token,
                refresh_token,
                scope,
                now,
                expires_in,
            ),
        )
        conn.commit()


def get_token(access_token: str) -> dict[str, Any] | None:
    with user_db.get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM oauth2_tokens
            WHERE access_token = ? AND revoked = 0
            LIMIT 1
            """,
            (access_token,),
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    if int(data["issued_at"]) + int(data["expires_in"]) < int(time.time()):
        return None
    return data


def new_token_string() -> str:
    return secrets.token_urlsafe(48)
