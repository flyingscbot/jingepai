"""同端口反代 Element Web，避免 /chat iframe 跨源与第三方 Cookie 问题。"""

from __future__ import annotations

import urllib.error
import urllib.request
from urllib.parse import urljoin

from flask import Blueprint, Response, request, stream_with_context

import auth_config

element_proxy_bp = Blueprint("element_proxy", __name__)

# 透传常见请求/响应头；剔除 hop-by-hop
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


def _upstream_url(subpath: str) -> str:
    base = auth_config.ELEMENT_UPSTREAM.rstrip("/") + "/"
    return urljoin(base, subpath.lstrip("/"))


def _filter_request_headers() -> dict[str, str]:
    headers = {}
    for key, value in request.headers:
        lk = key.lower()
        if lk in _HOP_BY_HOP or lk in ("cookie", "accept-encoding"):
            # Element 静态资源不需要金格 session cookie；避免压缩与分块长度不一致
            continue
        headers[key] = value
    headers["Accept-Encoding"] = "identity"
    headers["X-Forwarded-Prefix"] = auth_config.ELEMENT_PROXY_PATH.rstrip("/") or "/"
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-Proto"] = request.scheme
    return headers


def _filter_response_headers(upstream_headers) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key, value in upstream_headers.items():
        lk = key.lower()
        if lk in _HOP_BY_HOP:
            continue
        if lk == "content-security-policy":
            if "frame-ancestors" not in value.lower():
                value = (
                    value.rstrip(" ;")
                    + "; frame-ancestors 'self' http://127.0.0.1:1000 http://localhost:1000"
                )
            out.append((key, value))
            continue
        out.append((key, value))
    return out


def _proxy(subpath: str):
    if not auth_config.ELEMENT_PROXY_ENABLED:
        return Response("Element proxy disabled", status=404)

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
        return Response(
            body,
            status=e.code,
            headers=_filter_response_headers(e.headers),
        )
    except urllib.error.URLError as e:
        return Response(
            f"Element upstream unavailable: {e.reason}",
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


@element_proxy_bp.route("/element", methods=["GET", "HEAD"])
def proxy_element_root_redirect():
    return Response(status=308, headers={"Location": "/element/"})


@element_proxy_bp.route("/element/", defaults={"subpath": ""}, methods=["GET", "HEAD"])
@element_proxy_bp.route("/element/<path:subpath>", methods=["GET", "HEAD", "POST"])
def proxy_element(subpath: str):
    return _proxy(subpath)


def register_element_proxy(app):
    if auth_config.ELEMENT_PROXY_ENABLED:
        app.register_blueprint(element_proxy_bp)
