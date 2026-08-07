"""统一登录 / OIDC / Matrix 相关配置（可用环境变量覆盖）。"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent
DOMAIN_FILE = BASE_DIR / "domain.txt"
_DEFAULT_PUBLIC_BASE = "http://127.0.0.1:1000"


def _rstrip_slash(url: str) -> str:
    return (url or "").strip().rstrip("/")


def _read_domain_file(path: Path | None = None) -> str:
    """从仓库根 domain.txt 读穿透/公网根（一行 URL；# 行为注释）。

    空文件或缺失返回空串，由调用方回退默认本机地址。
    """
    p = path or DOMAIN_FILE
    if not p.is_file():
        return ""
    try:
        text = p.read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    for line in text.splitlines():
        s = line.strip().lstrip("\ufeff")
        if not s or s.startswith("#"):
            continue
        return _rstrip_slash(s)
    return ""


# 对外公开根地址（本机浏览器 / 手机客户端 / 内网穿透域名）。
# 优先级：仓库根 domain.txt → 环境变量 PUBLIC_BASE_URL / OIDC_PUBLIC_BASE → 本机默认。
# domain.txt 优先，避免 Flask --reload 继承旧 PUBLIC_BASE_URL 后改穿透根不生效。
# 例：https://xxxx.ngrok-free.app 或 http://127.0.0.1:1000
# 不要带 /fluffychat、/_matrix 等路径。每次 Flask 启动都会重新读 domain.txt。
PUBLIC_BASE_URL = _rstrip_slash(
    _read_domain_file()
    or os.environ.get("PUBLIC_BASE_URL")
    or os.environ.get("OIDC_PUBLIC_BASE")
    or _DEFAULT_PUBLIC_BASE
)

# 容器侧 Issuer（须与 Synapse oidc issuer 一致；Docker 场景用 host.docker.internal）
# Synapse / token / jwks / userinfo 走此地址；id_token.iss 也用此值。
# 穿透场景仍保持 host.docker.internal，勿改成穿透域名（容器内解析不到）。
OIDC_ISSUER = _rstrip_slash(
    os.environ.get("OIDC_ISSUER", "http://host.docker.internal:1000")
)

# 浏览器侧公开基址（authorize / 登录页 / well-known 对客户端可见的 URL）
OIDC_PUBLIC_BASE = PUBLIC_BASE_URL

# Matrix 家服务器域名（MXID 里 : 后面那段），需与 Synapse server_name 一致
MATRIX_SERVER_NAME = os.environ.get("MATRIX_SERVER_NAME", "matrix.localhost")

# 预置给 Synapse 用的 OIDC 客户端（也可改环境变量）
OIDC_MATRIX_CLIENT_ID = os.environ.get("OIDC_MATRIX_CLIENT_ID", "jingepi-synapse")
OIDC_MATRIX_CLIENT_SECRET = os.environ.get(
    "OIDC_MATRIX_CLIENT_SECRET", "change-me-synapse-oidc-secret"
)


def _default_oidc_redirect_uris() -> list[str]:
    """本机 + 穿透回调；Synapse 经 Flask :1000 反代时 callback 在公开根下。"""
    uris = [
        "http://127.0.0.1:1000/_synapse/client/oidc/callback",
        "http://127.0.0.1:8008/_synapse/client/oidc/callback",
        "http://localhost:8008/_synapse/client/oidc/callback",
        f"{PUBLIC_BASE_URL}/_synapse/client/oidc/callback",
    ]
    # 去重且保序
    seen: set[str] = set()
    out: list[str] = []
    for u in uris:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


# Synapse OIDC 回调；穿透时务必含 {PUBLIC_BASE_URL}/_synapse/client/oidc/callback
OIDC_MATRIX_REDIRECT_URIS = [
    u.strip()
    for u in os.environ.get(
        "OIDC_MATRIX_REDIRECT_URIS",
        ",".join(_default_oidc_redirect_uris()),
    ).split(",")
    if u.strip()
]

# RSA 密钥目录（自动生成）
OIDC_KEY_DIR = Path(os.environ.get("OIDC_KEY_DIR", str(BASE_DIR / "oidc_keys")))

# 开发期允许 HTTP（生产务必关）
AUTHLIB_INSECURE_TRANSPORT = os.environ.get("AUTHLIB_INSECURE_TRANSPORT", "1") == "1"

# Synapse 同源反代（浏览器只打 :1000，OIDC/Client API 不离开本源）
SYNAPSE_UPSTREAM = _rstrip_slash(
    os.environ.get("SYNAPSE_UPSTREAM", "http://127.0.0.1:8008")
)
SYNAPSE_PROXY_ENABLED = os.environ.get("SYNAPSE_PROXY_ENABLED", "1") == "1"

# FluffyChat Web（默认经 Flask 同端口反代；/chat 主客户端）
FLUFFY_UPSTREAM = _rstrip_slash(
    os.environ.get("FLUFFY_UPSTREAM", "http://127.0.0.1:8082")
)
FLUFFY_PROXY_PATH = (
    os.environ.get("FLUFFY_PROXY_PATH", "/fluffychat") or "/fluffychat"
).rstrip("/") or "/fluffychat"
FLUFFY_PROXY_ENABLED = os.environ.get("FLUFFY_PROXY_ENABLED", "1") == "1"
FLUFFY_URL = _rstrip_slash(os.environ.get("FLUFFY_URL", "http://127.0.0.1:8082"))

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


def public_origin_for_csp() -> str:
    """给 frame-ancestors 用的公开 origin（scheme://host[:port]）。"""
    p = urlparse(PUBLIC_BASE_URL)
    if not p.scheme or not p.netloc:
        return "http://127.0.0.1:1000"
    return f"{p.scheme}://{p.netloc}"


def _is_loopback_host(host: str) -> bool:
    h = (host or "").split(":")[0].strip().lower()
    return h in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def client_facing_base_url(request) -> str:
    """按当前 HTTP 请求推断浏览器可见根（本机 Host 或穿透 X-Forwarded-*）。

    TLS 终止型穿透常见情况：浏览器是 https，Flask 只收到 http，且未必带
    X-Forwarded-Proto。若 Host 与 PUBLIC_BASE_URL 一致，则采用公开根的 scheme，
    避免表单/well-known 生成 http://穿透根 导致混合内容被浏览器静默拦截。

    另：部分穿透只加 X-Forwarded-Proto: https，却把 Host 改成 127.0.0.1，
    若照做会得到 https://127.0.0.1:1000，Cinny SSO redirectUrl/HS 全错。
    此时若 PUBLIC_BASE_URL 是非回环公网根，直接采用公开根。
    """
    xfh = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    host = (xfh or request.host or "").split(",")[0].strip()
    if not host:
        return PUBLIC_BASE_URL

    xfp = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    pub = urlparse(PUBLIC_BASE_URL)
    pub_loopback = _is_loopback_host(pub.netloc or "")

    # 穿透 TLS 终止后常见：X-Forwarded-Proto=https，但 Host 仍是 127.0.0.1。
    # 若公开根是外网地址，改用 PUBLIC_BASE_URL，避免 Cinny HS/SSO 落到本机。
    if (
        _is_loopback_host(host)
        and not pub_loopback
        and pub.scheme in ("http", "https")
        and pub.netloc
        and xfp == "https"
    ):
        return PUBLIC_BASE_URL

    if xfp in ("http", "https"):
        proto = xfp
    elif pub.netloc and host.lower() == pub.netloc.lower() and pub.scheme in (
        "http",
        "https",
    ):
        proto = pub.scheme
    else:
        proto = (request.scheme or "http").split(",")[0].strip().lower()
        if proto not in ("http", "https"):
            proto = "https" if PUBLIC_BASE_URL.startswith("https://") else "http"
    return f"{proto}://{host}".rstrip("/")


def relative_request_action(request) -> str:
    """同源相对 action（path?query），供授权表单使用。

    勿用 request.url：穿透后 Flask scheme 常为 http，绝对 http action 在
    https 页面会被混合内容策略拦截，表现为「登录并授权」点击无反应。
    """
    path = request.path or "/"
    qs = request.query_string.decode("utf-8", errors="replace")
    return f"{path}?{qs}" if qs else path


def frame_ancestors_csp_value() -> str:
    """CSP frame-ancestors：本机 + 当前公开根（穿透域名）。"""
    origins = [
        "'self'",
        "http://127.0.0.1:1000",
        "http://localhost:1000",
        "http://127.0.0.1:5000",
        "http://localhost:5000",
        public_origin_for_csp(),
    ]
    seen: set[str] = set()
    parts: list[str] = []
    for o in origins:
        if o not in seen:
            seen.add(o)
            parts.append(o)
    return "frame-ancestors " + " ".join(parts)


def fluffy_embed_path() -> str:
    """给 /chat iframe 用的 FluffyChat 地址（优先同源相对路径）。"""
    if FLUFFY_PROXY_ENABLED:
        return FLUFFY_PROXY_PATH + "/"
    return FLUFFY_URL + "/"


def chat_embed_path() -> str:
    """/chat iframe 嵌入 FluffyChat。"""
    return fluffy_embed_path()


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
