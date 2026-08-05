"""金格最小 OIDC Provider（供自建 Synapse 使用）。

端点：
  GET  /.well-known/openid-configuration
  GET  /oauth/jwks.json
  GET  /oauth/authorize
  POST /oauth/token
  GET  /oauth/userinfo

网页 Session 已登录则可直接授权；未登录则在授权页使用金格账密。
"""

from __future__ import annotations

import os
import time

from authlib.integrations.flask_oauth2 import (
    AuthorizationServer,
    ResourceProtector,
    current_token,
)
from authlib.jose import JsonWebKey
from authlib.oauth2.rfc6749 import grants
from authlib.oauth2.rfc6750 import BearerTokenValidator
from authlib.oidc.core import UserInfo
from authlib.oidc.core.grants import OpenIDCode
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import (
    Blueprint,
    current_app,
    jsonify,
    render_template_string,
    request,
    session,
)

import auth_config
import oidc_store
import user_db

oidc_bp = Blueprint("oidc", __name__)

AUTHORIZATION_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>金格Pi - 授权登录</title>
  <style>
    body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
      font-family:"Noto Sans SC",sans-serif;background:#111;color:#eee;}
    .box{width:min(400px,92vw);padding:28px;border-radius:16px;
      background:rgba(36,36,40,.9);border:1px solid rgba(255,255,255,.14);}
    h1{font-size:20px;margin:0 0 8px;}
    p{color:#aaa;font-size:14px;line-height:1.5;margin:0 0 18px;}
    label{display:block;font-size:13px;margin:12px 0 6px;color:#ccc;}
    input{width:100%;box-sizing:border-box;height:40px;padding:0 12px;border-radius:10px;
      border:1px solid rgba(255,255,255,.16);background:#1a1a1e;color:#fff;}
    button{margin-top:18px;width:100%;height:42px;border:0;border-radius:999px;
      background:#f0b90b;color:#111;font-weight:600;cursor:pointer;}
    .err{color:#ff8e8e;font-size:13px;margin-top:10px;}
  </style>
</head>
<body>
  <div class="box">
    <h1>授权「{{ client_name }}」</h1>
    <p>使用金格Pi 账号登录 Matrix。登录后将创建/绑定家服务器用户。</p>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
    <form method="post" action="{{ form_action }}">
      <label>用户名</label>
      <input name="username" autocomplete="username" required value="{{ username }}">
      <label>密码</label>
      <input type="password" name="password" autocomplete="current-password" required>
      <button type="submit">登录并授权</button>
    </form>
  </div>
</body>
</html>
"""


def _ensure_rsa_key() -> tuple[str, str]:
    auth_config.OIDC_KEY_DIR.mkdir(parents=True, exist_ok=True)
    priv_path = auth_config.OIDC_KEY_DIR / "private.pem"
    pub_path = auth_config.OIDC_KEY_DIR / "public.pem"
    if not priv_path.exists() or not pub_path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        priv_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        pub_path.write_bytes(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
    return priv_path.read_text(encoding="utf-8"), pub_path.read_text(encoding="utf-8")


def _user_info(user: dict) -> UserInfo:
    localpart = auth_config.matrix_localpart_from_user_id(user["id"])
    return UserInfo(
        {
            "sub": user["id"],
            "name": user["username"],
            "preferred_username": localpart,
            "picture": user_db.avatar_url(user["id"], user["username"]),
        }
    )


def secrets_equal(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a.encode(), b.encode()):
        result |= x ^ y
    return result == 0


class _Client:
    def __init__(self, data: dict):
        self._data = data
        self.client_id = data["client_id"]

    def get_client_id(self):
        return self.client_id

    def get_default_redirect_uri(self):
        uris = self._data.get("redirect_uris") or []
        return uris[0] if uris else None

    def get_allowed_scope(self, scope):
        return scope

    def check_redirect_uri(self, redirect_uri):
        return redirect_uri in (self._data.get("redirect_uris") or [])

    def check_client_secret(self, client_secret):
        return secrets_equal(self._data.get("client_secret") or "", client_secret or "")

    def check_endpoint_auth_method(self, method, endpoint):
        if endpoint == "token":
            return method in (
                "client_secret_basic",
                "client_secret_post",
                "none",
            )
        return True

    def check_response_type(self, response_type):
        return response_type in (self._data.get("response_types") or ["code"])

    def check_grant_type(self, grant_type):
        return grant_type in (self._data.get("grant_types") or ["authorization_code"])

    def has_client_secret(self):
        return bool(self._data.get("client_secret"))


def query_client(client_id):
    data = oidc_store.get_client(client_id)
    return _Client(data) if data else None


def save_token(token, request):
    user = request.user
    client = request.client
    user_id = user["id"] if isinstance(user, dict) else None
    oidc_store.save_token(
        client_id=client.get_client_id(),
        user_id=user_id,
        access_token=token["access_token"],
        refresh_token=token.get("refresh_token"),
        scope=token.get("scope"),
        expires_in=int(token.get("expires_in") or 3600),
    )


authorization = AuthorizationServer()
require_oauth = ResourceProtector()


class AuthorizationCodeGrant(grants.AuthorizationCodeGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = [
        "client_secret_basic",
        "client_secret_post",
        "none",
    ]

    def save_authorization_code(self, code, request):
        oidc_store.save_authorization_code(
            code=code,
            client_id=request.client.client_id,
            user_id=request.user["id"],
            redirect_uri=request.redirect_uri,
            scope=request.scope,
            nonce=request.data.get("nonce"),
            code_challenge=request.data.get("code_challenge"),
            code_challenge_method=request.data.get("code_challenge_method"),
        )
        return code

    def query_authorization_code(self, code, client):
        item = oidc_store.get_authorization_code(code)
        if not item or item["client_id"] != client.client_id:
            return None

        class _Code:
            def __init__(self):
                self.code = code

            def get_redirect_uri(self):
                return item["redirect_uri"]

            def get_scope(self):
                return item.get("scope")

            def get_nonce(self):
                return item.get("nonce")

            def get_auth_time(self):
                return item.get("auth_time") or int(__import__("time").time())

            def get_acr(self):
                return None

            def get_amr(self):
                return None

            def is_expired(self):
                return False

            @property
            def code_challenge(self):
                return item.get("code_challenge")

            @property
            def code_challenge_method(self):
                return item.get("code_challenge_method")

            @property
            def user_id(self):
                return item["user_id"]

        return _Code()

    def delete_authorization_code(self, authorization_code):
        raw = getattr(authorization_code, "code", None)
        if raw:
            oidc_store.delete_authorization_code(raw)

    def authenticate_user(self, authorization_code):
        return user_db.get_user_by_id(authorization_code.user_id)


class MyOpenIDCode(OpenIDCode):
    def exists_nonce(self, nonce, request):
        return False

    def get_jwt_config(self, grant):
        private_key, _ = _ensure_rsa_key()
        return {
            "key": private_key,
            "alg": "RS256",
            "iss": auth_config.OIDC_ISSUER,
            "exp": 3600,
        }

    def generate_user_info(self, user, scope):
        return _user_info(user)


class _BearerTokenValidator(BearerTokenValidator):
    def authenticate_token(self, token_string):
        item = oidc_store.get_token(token_string)
        if not item:
            return None

        class _Token:
            def get_scope(self):
                return item.get("scope")

            def get_expires_at(self):
                return int(item["issued_at"]) + int(item["expires_in"])

            def get_expires_in(self):
                return int(item["expires_in"])

            @property
            def user_id(self):
                return item["user_id"]

            def is_expired(self):
                return self.get_expires_at() < int(time.time())

            def is_revoked(self):
                return False

        return _Token()


def init_oidc(app):
    if auth_config.AUTHLIB_INSECURE_TRANSPORT:
        os.environ["AUTHLIB_INSECURE_TRANSPORT"] = "1"

    oidc_store.init_oidc_tables()
    _ensure_rsa_key()

    authorization.init_app(app, query_client=query_client, save_token=save_token)
    authorization.register_grant(
        AuthorizationCodeGrant, [MyOpenIDCode(require_nonce=False)]
    )
    require_oauth.register_token_validator(_BearerTokenValidator())
    app.register_blueprint(oidc_bp)


def _current_session_user():
    if not session.get("is_login"):
        return None
    return user_db.get_user_by_id(session.get("user_id"))


@oidc_bp.get("/.well-known/openid-configuration")
def openid_configuration():
    # issuer / token / jwks：容器经 host.docker.internal 访问
    # authorization_endpoint：浏览器走 127.0.0.1，避免 host.docker.internal 拒绝连接
    iss = auth_config.OIDC_ISSUER
    public = auth_config.OIDC_PUBLIC_BASE
    return jsonify(
        {
            "issuer": iss,
            "authorization_endpoint": f"{public}/oauth/authorize",
            "token_endpoint": f"{iss}/oauth/token",
            "userinfo_endpoint": f"{iss}/oauth/userinfo",
            "jwks_uri": f"{iss}/oauth/jwks.json",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "scopes_supported": ["openid", "profile"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_basic",
                "client_secret_post",
            ],
            "claims_supported": ["sub", "name", "preferred_username", "picture"],
        }
    )


@oidc_bp.get("/oauth/jwks.json")
def jwks():
    _, public_pem = _ensure_rsa_key()
    key = JsonWebKey.import_key(
        public_pem, {"kty": "RSA", "use": "sig", "alg": "RS256"}
    )
    return jsonify({"keys": [key.as_dict(is_private=False)]})


@oidc_bp.route("/oauth/authorize", methods=["GET", "POST"])
def authorize():
    user = _current_session_user()
    client_id = request.args.get("client_id") or request.form.get("client_id")
    client = oidc_store.get_client(client_id) if client_id else None
    client_name = (client or {}).get("client_name") or "Matrix"

    if not user:
        error = None
        username = ""
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            candidate = user_db.get_user_by_name(username)
            if candidate and user_db.verify_password(candidate, password):
                session["is_login"] = True
                session["user_id"] = candidate["id"]
                session["username"] = candidate["username"]
                session.permanent = True
                user_db.ensure_user_folder(candidate)
                user = candidate
            else:
                error = "用户名或密码错误"
                return render_template_string(
                    AUTHORIZATION_HTML,
                    client_name=client_name,
                    error=error,
                    username=username,
                    form_action=request.url,
                )
        else:
            return render_template_string(
                AUTHORIZATION_HTML,
                client_name=client_name,
                error=None,
                username="",
                form_action=request.url,
            )

    # 实训场景：已登录直接授权
    try:
        return authorization.create_authorization_response(grant_user=user)
    except Exception as exc:
        current_app.logger.exception("OIDC authorize failed")
        return (
            jsonify({"error": "server_error", "error_description": str(exc)}),
            400,
        )


@oidc_bp.post("/oauth/token")
def issue_token():
    return authorization.create_token_response()


@oidc_bp.get("/oauth/userinfo")
@require_oauth("profile")
def userinfo():
    token = current_token
    user = user_db.get_user_by_id(getattr(token, "user_id", None))
    if not user:
        return jsonify({"error": "invalid_token"}), 401
    return jsonify(dict(_user_info(user)))
