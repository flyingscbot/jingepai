"""Same-origin reverse proxy for Synapse client/OIDC under Flask :1000.

Keeps Element SSO on one origin so:
- iframe /chat can show Synapse SSO pages (strip X-Frame-Options)
- browsers accept OIDC session cookies on plain HTTP (strip Secure from Set-Cookie)

Also enforces lab policies (deactivate / room_keys / createRoom for非管理员).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urljoin

from flask import Blueprint, Response, jsonify, request, stream_with_context

import auth_config
import user_db

logger = logging.getLogger(__name__)

matrix_proxy_bp = Blueprint("matrix_proxy", __name__)


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
        if lk in _HOP_BY_HOP:
            continue
        headers[key] = value
    # Synapse public_baseurl 是浏览器可见根 — Host / Proto 必须与穿透一致，
    # 否则 SSO 302 会指回错误 scheme/host。
    headers["Host"] = request.host
    headers["X-Forwarded-Host"] = request.host
    fwd_proto = (request.headers.get("X-Forwarded-Proto") or request.scheme or "http").split(",")[0].strip()
    if auth_config.PUBLIC_BASE_URL.startswith("https://"):
        fwd_proto = "https"
    elif auth_config.PUBLIC_BASE_URL.startswith("http://"):
        # 本机明文或 HTTP 穿透
        if fwd_proto not in ("http", "https"):
            fwd_proto = "http"
    headers["X-Forwarded-Proto"] = fwd_proto
    headers["X-Forwarded-For"] = request.remote_addr or "127.0.0.1"
    headers["Accept-Encoding"] = "identity"
    return headers


def _rewrite_set_cookie(value: str) -> str:
    # Local HTTP: browsers reject Secure cookies → strip for OIDC/session cookies
    value = _SECURE_COOKIE_RE.sub("", value)
    # SameSite=None requires Secure; downgrade so cookie is kept on HTTP
    value = re.sub(r";\s*SameSite=None", "; SameSite=Lax", value, flags=re.I)
    return value


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
        upstream = _OPENER.open(req, timeout=120)
    except urllib.error.HTTPError as e:
        body = e.read()
        return Response(body, status=e.code, headers=_filter_response_headers(e.headers))
    except urllib.error.URLError as e:
        return Response(
            f"Synapse upstream unavailable: {e.reason}",
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

    ``m.homeserver.base_url`` 一律用 ``PUBLIC_BASE_URL``（穿透/公网根），
    避免手机 Element 仍被导向 127.0.0.1。E2EE 禁用标志与 Synapse
    extra_well_known_client_content 对齐；上游失败时仍返回本地默认。
    不与 OIDC ``/.well-known/openid-configuration`` 冲突。
    """
    kind = subpath.strip("/")
    if kind == "client":
        body: dict = {
            "m.homeserver": {"base_url": auth_config.PUBLIC_BASE_URL},
            "io.element.e2ee": {"default": False, "force_disable": True},
        }
        try:
            upstream = _OPENER.open(
                urllib.request.Request(
                    _upstream("/.well-known/matrix/client"),
                    headers={"Accept": "application/json"},
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
        body["m.homeserver"] = {"base_url": auth_config.PUBLIC_BASE_URL}
        return jsonify(body)
    return _proxy("/.well-known/matrix/" + subpath)


def register_matrix_proxy(app):
    if auth_config.SYNAPSE_PROXY_ENABLED:
        app.register_blueprint(matrix_proxy_bp)
