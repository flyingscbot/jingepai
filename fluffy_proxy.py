"""同端口反代 FluffyChat Web，避免 /chat iframe 跨源与 SSO auth.html 回调问题。

额外：注入金格Pi壳层 CSS/JS（Flutter CanvasKit 画布内样式不可 CSS 覆盖，
颜色与 Material 交互态靠 config colorSchemeSeedInt + 启动脚本锁深色/金色）。
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urljoin

from flask import Blueprint, Response, request, send_file, stream_with_context

import auth_config

fluffy_proxy_bp = Blueprint("fluffy_proxy", __name__)

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

_BASE_HREF_OLD = b'<base href="/">'
_BASE_HREF_NEW = b'<base href="/fluffychat/">'

# 与 Element lab-static 同级：matrix/fluffy-static/
_STATIC_DIR = Path(__file__).resolve().parent / "matrix" / "fluffy-static"
_LAB_ASSETS = {
    "lab-jingepi-fluffy.css": "text/css; charset=utf-8",
    "lab-jingepi-fluffy.js": "application/javascript; charset=utf-8",
}

_INJECT_SNIPPET = (
    b'<link rel="stylesheet" href="lab-jingepi-fluffy.css">'
    b'<script src="lab-jingepi-fluffy.js"></script>'
)
_INJECT_MARKER = b"lab-jingepi-fluffy"


def _upstream_url(subpath: str) -> str:
    base = auth_config.FLUFFY_UPSTREAM.rstrip("/") + "/"
    return urljoin(base, subpath.lstrip("/"))


def _filter_request_headers() -> dict[str, str]:
    headers = {}
    for key, value in request.headers:
        lk = key.lower()
        if lk in _HOP_BY_HOP or lk in ("cookie", "accept-encoding"):
            continue
        headers[key] = value
    headers["Accept-Encoding"] = "identity"
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-Proto"] = request.scheme
    headers["X-Forwarded-Prefix"] = auth_config.FLUFFY_PROXY_PATH.rstrip("/") or "/"
    return headers


def _filter_response_headers(upstream_headers) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key, value in upstream_headers.items():
        lk = key.lower()
        if lk in _HOP_BY_HOP:
            continue
        if lk == "content-security-policy":
            if "frame-ancestors" not in value.lower():
                value = value.rstrip(" ;") + "; " + auth_config.frame_ancestors_csp_value()
            out.append((key, value))
            continue
        if lk == "x-frame-options":
            # 允许同源 /chat iframe 嵌入
            continue
        out.append((key, value))
    # 无 CSP 时补上 frame-ancestors，便于 iframe
    if not any(k.lower() == "content-security-policy" for k, _ in out):
        out.append(
            ("Content-Security-Policy", auth_config.frame_ancestors_csp_value())
        )
    return out


def _inject_jingepi_assets(body: bytes) -> bytes:
    if _INJECT_MARKER in body:
        return body
    lower = body.lower()
    needle = b"</body>"
    idx = lower.rfind(needle)
    if idx >= 0:
        return body[:idx] + _INJECT_SNIPPET + body[idx:]
    needle = b"</html>"
    idx = lower.rfind(needle)
    if idx >= 0:
        return body[:idx] + _INJECT_SNIPPET + body[idx:]
    return body + _INJECT_SNIPPET


def _maybe_rewrite_html(body: bytes, content_type: str) -> bytes:
    if "text/html" not in (content_type or "").lower():
        return body
    if _BASE_HREF_OLD in body:
        body = body.replace(_BASE_HREF_OLD, _BASE_HREF_NEW, 1)
    return _inject_jingepi_assets(body)


def _serve_lab_asset(filename: str):
    path = _STATIC_DIR / filename
    if not path.is_file():
        return Response(f"missing {filename}", status=404, mimetype="text/plain")
    mime = _LAB_ASSETS.get(filename) or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    resp = send_file(path, mimetype=mime, conditional=True)
    resp.headers["Cache-Control"] = "no-store"
    return resp


def _proxy(subpath: str, *, rewrite_base: bool = True):
    if not auth_config.FLUFFY_PROXY_ENABLED:
        return Response("FluffyChat proxy disabled", status=404)

    # 金格主题静态资源：优先本地，不走上游
    clean = (subpath or "").lstrip("/")
    if clean in _LAB_ASSETS:
        return _serve_lab_asset(clean)

    url = _upstream_url(subpath)
    if request.query_string:
        url = f"{url}?{request.query_string.decode('latin-1')}"

    data = request.get_data() if request.method in ("POST", "PUT", "PATCH") else None
    req = urllib.request.Request(
        url,
        data=data if data else None,
        headers=_filter_request_headers(),
        method=request.method,
    )
    try:
        upstream = urllib.request.urlopen(req, timeout=60)
    except urllib.error.HTTPError as e:
        body = e.read()
        ctype = e.headers.get("Content-Type", "")
        if rewrite_base:
            body = _maybe_rewrite_html(body, ctype)
        return Response(
            body,
            status=e.code,
            headers=_filter_response_headers(e.headers),
        )
    except urllib.error.URLError as e:
        return Response(
            f"FluffyChat upstream unavailable: {e.reason}",
            status=502,
            mimetype="text/plain",
        )

    ctype = upstream.headers.get("Content-Type", "")
    # HTML / 小 JSON 可整体改写；大静态资源流式转发
    if rewrite_base and "text/html" in ctype.lower():
        body = upstream.read()
        upstream.close()
        body = _maybe_rewrite_html(body, ctype)
        return Response(
            body,
            status=upstream.status,
            headers=_filter_response_headers(upstream.headers),
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


@fluffy_proxy_bp.route("/fluffychat", methods=["GET", "HEAD"])
def proxy_fluffy_root_redirect():
    return Response(status=308, headers={"Location": "/fluffychat/"})


@fluffy_proxy_bp.route("/fluffychat/", defaults={"subpath": ""}, methods=["GET", "HEAD"])
@fluffy_proxy_bp.route(
    "/fluffychat/<path:subpath>", methods=["GET", "HEAD", "POST"]
)
def proxy_fluffy(subpath: str):
    return _proxy(subpath, rewrite_base=True)


@fluffy_proxy_bp.route("/auth.html", methods=["GET", "HEAD"])
def proxy_fluffy_auth_html():
    """FluffyChat Web SSO 回调写死为 origin/auth.html，须挂在站点根路径。"""
    return _proxy("auth.html", rewrite_base=False)


def register_fluffy_proxy(app):
    if auth_config.FLUFFY_PROXY_ENABLED:
        app.register_blueprint(fluffy_proxy_bp)
