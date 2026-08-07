"""Same-origin reverse proxy for Synapse client/OIDC under Flask :1000.

Keeps Matrix SSO on one origin so:
- iframe /chat can show Synapse SSO pages (strip X-Frame-Options)
- browsers accept OIDC session cookies on plain HTTP (strip Secure from Set-Cookie)

Also enforces lab policies (deactivate / room_keys / createRoom for非管理员).
"""

from __future__ import annotations

import http.client
import json
import logging
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urljoin, urlparse

from flask import Blueprint, Response, jsonify, request, stream_with_context

import auth_config
import synapse_admin
import user_db

logger = logging.getLogger(__name__)

matrix_proxy_bp = Blueprint("matrix_proxy", __name__)

# Cinny / 浏览器偶发带超多自定义头；Synapse 若回显或中间层拼接时，
# 默认 http.client._MAXHEADERS=100 会直接炸，表现为 /_matrix 卡住或 500。
if getattr(http.client, "_MAXHEADERS", 100) < 500:
    http.client._MAXHEADERS = 500


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Pass 3xx through to the browser — never follow (avoids Flask self-deadlock)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

# 只转发 Matrix / OIDC 需要的请求头，避免把浏览器垃圾头放大成上游异常响应
_REQUEST_HEADER_ALLOW = {
    "authorization",
    "content-type",
    "accept",
    "origin",
    "user-agent",
    "cookie",
    "if-none-match",
    "if-modified-since",
    "x-requested-with",
}

_SECURE_COOKIE_RE = re.compile(r";\s*Secure", re.I)


def _upstream(path_and_query: str) -> str:
    base = auth_config.SYNAPSE_UPSTREAM.rstrip("/") + "/"
    return urljoin(base, path_and_query.lstrip("/"))


def _encode_path_for_upstream(path: str) -> str:
    """Re-percent-encode path so urllib does not treat Matrix room aliases as fragments.

    Flask/Werkzeug decode ``%23lobby%3A…`` → ``#lobby:…`` in PATH_INFO.
    Passing that string to ``urllib.request`` makes ``#…`` a URL fragment, so Synapse
    sees ``GET /_matrix/client/v3/directory/room/`` and returns M_INVALID_PARAM.
    Keep ``/`` unencoded; encode everything else (``#``, ``?``, ``@``, ``!``, ``:``, …).
    """
    return quote(path, safe="/")


def _filter_request_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in request.headers:
        lk = key.lower()
        if lk in _HOP_BY_HOP or lk not in _REQUEST_HEADER_ALLOW:
            continue
        headers[key] = value
    # Host / Proto：跟「浏览器实际访问的根」一致，勿仅因 domain.txt 是 https
    # 就把本机 http://127.0.0.1 请求强行标成 https（易干扰 SSO 与发现）。
    facing = auth_config.client_facing_base_url(request)
    parsed = urlparse(facing)
    host = parsed.netloc or request.host
    proto = parsed.scheme or request.scheme or "http"
    headers["Host"] = host
    headers["X-Forwarded-Host"] = host
    headers["X-Forwarded-Proto"] = proto
    headers["X-Forwarded-For"] = request.remote_addr or "127.0.0.1"
    # 允许 Synapse 回 gzip 压缩 JSON（代理不改写 body，可透传）
    if "accept-encoding" not in headers:
        ae = (request.headers.get("Accept-Encoding") or "").lower()
        if ae:
            headers["Accept-Encoding"] = ae
        else:
            headers["Accept-Encoding"] = "gzip, deflate"
    return headers


def _rewrite_set_cookie(value: str) -> str:
    # Local HTTP: browsers reject Secure cookies → strip for OIDC/session cookies
    value = _SECURE_COOKIE_RE.sub("", value)
    # SameSite=None requires Secure; downgrade so cookie is kept on HTTP
    value = re.sub(r";\s*SameSite=None", "; SameSite=Lax", value, flags=re.I)
    return value


def _rewrite_location(value: str) -> str:
    """谨慎改写上游 Location；SSO/OIDC 浏览器跳转不得改回本机。

    domain.txt 为穿透根时，Synapse 会把本机发起的 SSO 302 到 public_baseurl。
    若再把 Location 改回 http://127.0.0.1:1000/.../sso/redirect，会与
    Synapse canonical 检查形成无限 302（本机「登录不行」）。

    双模式策略：SSO/OIDC 跳转保持 Synapse 给出的 public_baseurl（穿透）；
    完结后靠 Cinny 的 redirectUrl 回到本机或穿透 Cinny。其它 Location
    仍可对齐到当前访问根。
    """
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return value
    path = (parsed.path or "").lower()
    if any(
        p in path
        for p in (
            "/login/sso/redirect",
            "/oauth/authorize",
            "/_synapse/client/oidc/",
        )
    ):
        return value

    facing = auth_config.client_facing_base_url(request).rstrip("/")
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    if origin == facing:
        return value
    replaceable = {
        auth_config.PUBLIC_BASE_URL.rstrip("/"),
        "http://127.0.0.1",
        "http://127.0.0.1:1000",
        "http://localhost",
        "http://localhost:1000",
        "https://127.0.0.1",
        "https://127.0.0.1:1000",
        "https://localhost",
        "https://localhost:1000",
    }
    if origin not in replaceable:
        return value
    suffix = parsed.path or ""
    if parsed.query:
        suffix += f"?{parsed.query}"
    if parsed.fragment:
        suffix += f"#{parsed.fragment}"
    return facing + suffix


def _filter_response_headers(upstream_headers) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key, value in upstream_headers.items():
        lk = key.lower()
        if lk in _HOP_BY_HOP:
            continue
        if lk == "x-frame-options":
            # Allow embedding Synapse SSO/Continue inside /chat iframe
            continue
        if lk == "content-security-policy":
            # Replace deny frame-ancestors so Continue page can render in iframe
            # （含 PUBLIC_BASE_URL / 穿透域名）
            fa = auth_config.frame_ancestors_csp_value() + ";"
            value = re.sub(
                r"frame-ancestors[^;]*;?",
                fa,
                value,
                flags=re.I,
            )
            if "frame-ancestors" not in value.lower():
                value = value.rstrip(" ;") + "; " + fa.rstrip(";")
            out.append((key, value))
            continue
        if lk == "set-cookie":
            out.append((key, _rewrite_set_cookie(value)))
            continue
        if lk == "location":
            out.append((key, _rewrite_location(value)))
            continue
        out.append((key, value))
    return out


# Client-Server API: POST /_matrix/client/{r0|v3|unstable}/account/deactivate
_DEACTIVATE_RE = re.compile(
    r"^/_matrix/client/(?:r0|v3|unstable)/account/deactivate/?$",
    re.I,
)

# E2EE room key backup / SSSS backup versions (not device keys / sync / login)
# GET/POST/PUT/DELETE /_matrix/client/{r0|v3|unstable}/room_keys/...
_ROOM_KEYS_RE = re.compile(
    r"^/_matrix/client/(?:r0|v3|unstable)/room_keys(?:/.*)?$",
    re.I,
)

# Create room / space: POST /_matrix/client/{r0|v3|unstable}/createRoom
_CREATE_ROOM_RE = re.compile(
    r"^/_matrix/client/(?:r0|v3|unstable)/createRoom/?$",
    re.I,
)


def _blocked_deactivate_response() -> Response:
    """Lab policy: users must not self-deactivate (SSO accounts are IdP-managed)."""
    return Response(
        '{"errcode":"M_FORBIDDEN","error":"Account deactivation is disabled"}',
        status=403,
        mimetype="application/json",
    )


def _blocked_room_keys_response() -> Response:
    """Lab policy: disable megolm key backup so recovery-key / secure-backup flows cannot run."""
    return Response(
        '{"errcode":"M_FORBIDDEN","error":"Room key backup is disabled"}',
        status=403,
        mimetype="application/json",
    )


def _blocked_create_room_response() -> Response:
    return Response(
        '{"errcode":"M_FORBIDDEN","error":"Creating group chats and spaces requires an admin account"}',
        status=403,
        mimetype="application/json",
    )


def _bearer_token() -> str | None:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        tok = auth[7:].strip()
        return tok or None
    tok = request.args.get("access_token")
    return tok.strip() if tok else None


def _whoami_user_id(access_token: str) -> str | None:
    """Resolve MXID via Synapse whoami (direct upstream, not through Flask)."""
    url = _upstream("/_matrix/client/v3/account/whoami")
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with _OPENER.open(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        uid = data.get("user_id")
        return uid if isinstance(uid, str) else None
    except Exception as exc:
        logger.warning("whoami failed: %s", exc)
        return None


def _mxid_localpart(mxid: str) -> str | None:
    if not mxid.startswith("@") or ":" not in mxid:
        return None
    return mxid[1:].split(":", 1)[0]


def resolve_jingepi_user_from_matrix_token() -> dict | None:
    """用当前请求的 Matrix access_token 解析金格用户（localpart = users.id）。"""
    token = _bearer_token()
    if not token:
        return None
    mxid = _whoami_user_id(token)
    if not mxid:
        return None
    localpart = _mxid_localpart(mxid)
    if not localpart:
        return None
    return user_db.get_user_by_id(localpart)


def _create_room_is_restricted(body: bytes | None) -> bool:
    """True = 群聊或空间（普通用户禁止）；False = 私聊 DM（允许）。"""
    if not body:
        return True
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return True
    if not isinstance(data, dict):
        return True
    creation = data.get("creation_content") or {}
    if isinstance(creation, dict) and creation.get("type") == "m.space":
        return True
    if data.get("type") == "m.space":
        return True
    if data.get("is_direct") is True:
        return False
    return True


def _should_block_create_room(body: bytes | None) -> bool:
    if not _create_room_is_restricted(body):
        return False
    user = resolve_jingepi_user_from_matrix_token()
    if user is None:
        return True
    if not user.get("is_active", True):
        return True
    return not user_db.can_create_matrix_rooms(user.get("role"))


def _proxy(subpath: str):
    if not auth_config.SYNAPSE_PROXY_ENABLED:
        return Response("Synapse proxy disabled", status=404)

    path = subpath if subpath.startswith("/") else "/" + subpath
    if request.method == "POST" and _DEACTIVATE_RE.match(path):
        return _blocked_deactivate_response()
    if _ROOM_KEYS_RE.match(path):
        return _blocked_room_keys_response()

    data = request.get_data() if request.method in ("POST", "PUT", "PATCH") else None

    if request.method == "POST" and _CREATE_ROOM_RE.match(path):
        if _should_block_create_room(data):
            return _blocked_create_room_response()

    # Re-encode decoded PATH_INFO (# in #alias:server) before urllib upstream fetch.
    url = _upstream(_encode_path_for_upstream(path))
    if request.query_string:
        url = f"{url}?{request.query_string.decode('latin-1')}"

    req = urllib.request.Request(
        url,
        data=data if data else None,
        headers=_filter_request_headers(),
        method=request.method,
    )
    try:
        upstream = _OPENER.open(req, timeout=60)
    except urllib.error.HTTPError as e:
        body = e.read()
        return Response(body, status=e.code, headers=_filter_response_headers(e.headers))
    except urllib.error.URLError as e:
        return Response(
            f"Synapse upstream unavailable: {e.reason}",
            status=502,
            mimetype="text/plain",
        )
    except http.client.HTTPException as e:
        # 典型：got more than N headers —— 勿让未捕获异常拖死/刷爆 Flask worker
        logger.warning("Synapse upstream HTTP parse error for %s: %s", path, e)
        return Response(
            f"Synapse upstream protocol error: {e}",
            status=502,
            mimetype="text/plain",
        )
    except Exception as e:
        logger.exception("Synapse proxy failed for %s", path)
        return Response(
            f"Synapse proxy error: {e}",
            status=502,
            mimetype="text/plain",
        )

    def generate():
        try:
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    return Response(
        stream_with_context(generate()),
        status=upstream.status,
        headers=_filter_response_headers(upstream.headers),
    )


@matrix_proxy_bp.route(
    "/_matrix/<path:subpath>",
    methods=["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
)
def proxy_matrix(subpath: str):
    return _proxy("/_matrix/" + subpath)


@matrix_proxy_bp.route(
    "/_synapse/<path:subpath>",
    methods=["GET", "HEAD", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
)
def proxy_synapse(subpath: str):
    return _proxy("/_synapse/" + subpath)


@matrix_proxy_bp.route(
    "/.well-known/matrix/<path:subpath>",
    methods=["GET", "HEAD", "OPTIONS"],
)
def proxy_matrix_well_known(subpath: str):
    """Expose Matrix client/server well-known on the Flask origin (:1000).

    ``m.homeserver.base_url`` 用当前请求的对外根（本机 Host 或穿透
    X-Forwarded-*），这样本机打开 127.0.0.1 不会被强制指到穿透 IP，
    手机经穿透访问时仍得到穿透根。E2EE 标志与 Synapse
    extra_well_known_client_content 对齐。
    不与 OIDC ``/.well-known/openid-configuration`` 冲突。
    """
    kind = subpath.strip("/")
    if kind == "client":
        base = auth_config.client_facing_base_url(request)
        body: dict = {
            "m.homeserver": {"base_url": base},
            "io.element.e2ee": {"default": False, "force_disable": True},
        }
        try:
            upstream = _OPENER.open(
                urllib.request.Request(
                    _upstream("/.well-known/matrix/client"),
                    headers={"Accept": "application/json", "Connection": "close"},
                    method="GET",
                ),
                timeout=5,
            )
            try:
                raw = upstream.read()
                data = json.loads(raw.decode("utf-8", errors="replace"))
                if isinstance(data, dict):
                    for k, v in data.items():
                        if k == "m.homeserver":
                            continue
                        body[k] = v
                    # 保证 e2ee 强制禁用不被上游覆盖丢
                    e2ee = body.get("io.element.e2ee")
                    if not isinstance(e2ee, dict):
                        e2ee = {}
                    e2ee.setdefault("default", False)
                    e2ee["force_disable"] = True
                    body["io.element.e2ee"] = e2ee
            finally:
                upstream.close()
        except Exception:
            logger.debug("well-known upstream merge skipped", exc_info=True)
        body["m.homeserver"] = {"base_url": base}
        return jsonify(body)
    return _proxy("/.well-known/matrix/" + subpath)


def register_matrix_proxy(app):
    if auth_config.SYNAPSE_PROXY_ENABLED:
        app.register_blueprint(matrix_proxy_bp)
