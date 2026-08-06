"""统一登录 / OIDC / Matrix 相关配置（可用环境变量覆盖）。"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 容器侧 Issuer（须与 Synapse oidc issuer 一致；Docker 场景用 host.docker.internal）
# Synapse / token / jwks / userinfo 走此地址；id_token.iss 也用此值。
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "http://host.docker.internal:1000").rstrip("/")

# 浏览器侧公开基址（authorize / 登录页）。Windows 上浏览器不能可靠打开 host.docker.internal。
OIDC_PUBLIC_BASE = os.environ.get("OIDC_PUBLIC_BASE", "http://127.0.0.1:1000").rstrip("/")

# Matrix 家服务器域名（MXID 里 : 后面那段），需与 Synapse server_name 一致
MATRIX_SERVER_NAME = os.environ.get("MATRIX_SERVER_NAME", "matrix.localhost")

# 预置给 Synapse 用的 OIDC 客户端（也可改环境变量）
OIDC_MATRIX_CLIENT_ID = os.environ.get("OIDC_MATRIX_CLIENT_ID", "jingepi-synapse")
OIDC_MATRIX_CLIENT_SECRET = os.environ.get(
    "OIDC_MATRIX_CLIENT_SECRET", "change-me-synapse-oidc-secret"
)
# Synapse OIDC 回调；docker 内常用 http://localhost:8008/... 或公网域名
# Browser callback prefers 127.0.0.1 to avoid Windows localhost->::1 refused
OIDC_MATRIX_REDIRECT_URIS = [
    u.strip()
    for u in os.environ.get(
        "OIDC_MATRIX_REDIRECT_URIS",
        ",".join(
            [
                "http://127.0.0.1:1000/_synapse/client/oidc/callback",
                "http://127.0.0.1:8008/_synapse/client/oidc/callback",
                "http://localhost:8008/_synapse/client/oidc/callback",
            ]
        ),
    ).split(",")
    if u.strip()
]

# RSA 密钥目录（自动生成）
OIDC_KEY_DIR = Path(os.environ.get("OIDC_KEY_DIR", str(BASE_DIR / "oidc_keys")))

# 开发期允许 HTTP（生产务必关）
AUTHLIB_INSECURE_TRANSPORT = os.environ.get("AUTHLIB_INSECURE_TRANSPORT", "1") == "1"

# Element Web：默认经 Flask 同端口反代，避免 /chat iframe 跨源

# Synapse 同源反代（浏览器只打 :1000，OIDC/Client API 不离开本源）
SYNAPSE_UPSTREAM = os.environ.get("SYNAPSE_UPSTREAM", "http://127.0.0.1:8008").rstrip("/")
SYNAPSE_PROXY_ENABLED = os.environ.get("SYNAPSE_PROXY_ENABLED", "1") == "1"

ELEMENT_UPSTREAM = os.environ.get("ELEMENT_UPSTREAM", "http://127.0.0.1:8081").rstrip("/")
ELEMENT_PROXY_PATH = (os.environ.get("ELEMENT_PROXY_PATH", "/element") or "/element").rstrip(
    "/"
) or "/element"
ELEMENT_PROXY_ENABLED = os.environ.get("ELEMENT_PROXY_ENABLED", "1") == "1"
# 关闭反代时 iframe 直连此地址
ELEMENT_URL = os.environ.get("ELEMENT_URL", "http://127.0.0.1:8081").rstrip("/")

# Synapse Admin API：金格改用户名/头像时即时同步 Matrix displayname / avatar
# 须与 matrix/homeserver.yaml 的 registration_shared_secret 一致
SYNAPSE_REGISTRATION_SHARED_SECRET = os.environ.get(
    "SYNAPSE_REGISTRATION_SHARED_SECRET",
    "jingepi-dev-registration-secret-change-me",
)
# 可选：直接提供已有 admin 的 access_token（优先于自动注册）
SYNAPSE_ADMIN_ACCESS_TOKEN = os.environ.get("SYNAPSE_ADMIN_ACCESS_TOKEN", "").strip()


def oidc_uses_http() -> bool:
    """本地 HTTP 开发：issuer / public base 非 https，或显式 insecure transport。"""
    if AUTHLIB_INSECURE_TRANSPORT:
        return True
    for url in (OIDC_ISSUER, OIDC_PUBLIC_BASE):
        if url.startswith("http://"):
            return True
    return False


def element_embed_path() -> str:
    """给 /chat iframe 用的 Element 地址（优先同源相对路径）。"""
    if ELEMENT_PROXY_ENABLED:
        return ELEMENT_PROXY_PATH + "/"
    return ELEMENT_URL + "/"


def matrix_mxid(localpart: str) -> str:
    return f"@{localpart}:{MATRIX_SERVER_NAME}"


def matrix_localpart_from_user_id(user_id: str) -> str:
    """Matrix localpart = 金格 users.id（uuid4.hex，32 位 [a-f0-9]）。

    用户名可能含中文，不能作 localpart；显示名由 OIDC name（username）提供。
    """
    uid = (user_id or "").strip().lower()
    if not uid or len(uid) != 32 or any(c not in "0123456789abcdef" for c in uid):
        raise ValueError(f"非法金格用户 id，无法映射 Matrix localpart: {user_id!r}")
    return uid
