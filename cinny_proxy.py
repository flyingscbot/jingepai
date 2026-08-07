"""同端口反代 Cinny Web，避免 /chat iframe 跨源，并挂子路径 /cinny/。

官方预构建以 base=/ 产出绝对路径（/assets、/config.json 等）；
本代理把上游根挂到 /cinny/，并对 HTML/JS/CSS/JSON 做路径改写。
hashRouter 开启后无需为 SPA 深链单独回退 index.html。
"""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urljoin

from flask import Blueprint, Response, request, stream_with_context

import auth_config

cinny_proxy_bp = Blueprint("cinny_proxy", __name__)

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

_STATIC_DIR = Path(__file__).resolve().parent / "matrix" / "cinny-static"
_LAB_ASSETS = {
    "lab-jingepi-cinny.css": "text/css; charset=utf-8",
    "lab-jingepi-cinny.js": "application/javascript; charset=utf-8",
}
# 金格补丁的 locale；官方 v4.12.6 仅有 en/de 且几乎为空
_LAB_LOCALE_FILES = {
    "public/locales/zh.json",
    "public/locales/zh-CN.json",
}

_INJECT_SNIPPET = (
    b'<link rel="stylesheet" href="lab-jingepi-cinny.css">'
    b'<script src="lab-jingepi-cinny.js"></script>'
)
_INJECT_MARKER = b"lab-jingepi-cinny"

# 预构建 Cinny 常见绝对路径 → /cinny/ 前缀
_PROXY_PREFIX = b"/cinny"
_REWRITE_ROOTS = (
    b"/assets/",
    b"/public/",
    b"/config.json",
    b"/manifest.json",
    b"/sw.js",
    b"/pdf.worker.min.js",
    b"/pdf.worker.min.mjs",
    b"/favicon.ico",
    b"/robots.txt",
)


def _lab_response(filename: str, mime: str) -> Response:
    path = _STATIC_DIR / filename
    data = path.read_bytes()
    return Response(
        data,
        mimetype=mime,
        headers={"Cache-Control": "no-store"},
    )


def _safe_lab_path(clean: str) -> Path | None:
    """仅允许 cinny-static 下白名单相对路径，防路径穿越。"""
    if not clean or clean.startswith("/") or "\\" in clean or ".." in clean.split("/"):
        return None
    path = (_STATIC_DIR / clean).resolve()
    root = _STATIC_DIR.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None
    return path if path.is_file() else None


def _mime_for_lab(clean: str) -> str:
    if clean in _LAB_ASSETS:
        return _LAB_ASSETS[clean]
    if clean.endswith(".json"):
        return "application/json; charset=utf-8"
    if clean.endswith(".css"):
        return "text/css; charset=utf-8"
    if clean.endswith(".js"):
        return "application/javascript; charset=utf-8"
    return mimetypes.guess_type(clean)[0] or "application/octet-stream"


def _upstream_url(subpath: str) -> str:
    base = auth_config.CINNY_UPSTREAM.rstrip("/") + "/"
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
    headers["X-Forwarded-Prefix"] = auth_config.CINNY_PROXY_PATH.rstrip("/") or "/"
    return headers


def _rewrite_location(value: str) -> str:
    """上游 Location 若指向根路径资源，改写到 /cinny/ 下。"""
    prefix = auth_config.CINNY_PROXY_PATH.rstrip("/") or "/cinny"
    if value.startswith("/") and not value.startswith(prefix + "/") and value != prefix:
        for root in (
            "/assets/",
            "/public/",
            "/config.json",
            "/manifest.json",
            "/sw.js",
            "/favicon.ico",
        ):
            if value == root.rstrip("/") or value.startswith(root):
                return prefix + value
        if value == "/":
            return prefix + "/"
    return value


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
            continue
        if lk == "location":
            out.append((key, _rewrite_location(value)))
            continue
        out.append((key, value))
    if not any(k.lower() == "content-security-policy" for k, _ in out):
        out.append(
            ("Content-Security-Policy", auth_config.frame_ancestors_csp_value())
        )
    return out


def _rewrite_absolute_paths(body: bytes) -> bytes:
    """把预构建里的站点根绝对路径改到 /cinny 下（避免资源 404）。"""
    # Vite/Cinny：Jo 只剥尾斜杠。Jo("/")→"" 时 `${Jo("/")}/config.json` 变成 /config.json；
    # 改成 Jo("/cinny/")→"/cinny"，资源落到 /cinny/config.json 等。
    if b'Jo("/")' in body:
        body = body.replace(b'Jo("/")', b'Jo("/cinny/")')
    if b"Jo('/')" in body:
        body = body.replace(b"Jo('/')", b"Jo('/cinny/')")
    # SSO redirectUrl 用 fk("/") 拼 pathname；不改写会落到 origin/#/login（丢 /cinny），
    # 登录成功后停在主站黑底空白页。仅此一处字面量（hashRouter basename 仍走配置里的 "/"）。
    if b'fk("/")' in body:
        body = body.replace(b'fk("/")', b'fk("/cinny/")')
    if b"fk('/')" in body:
        body = body.replace(b"fk('/')", b"fk('/cinny/')")
    for root in _REWRITE_ROOTS:
        # " /assets/..." 与 '/assets/...' 与 `/assets/...`
        for quote in (b'"', b"'", b"`"):
            old = quote + root
            new = quote + _PROXY_PREFIX + root
            if old in body:
                body = body.replace(old, new)
        # URL(...) / src=/assets 无引号少见，补 HTML 属性无引号场景
        old_eq = b"=" + root
        new_eq = b"=" + _PROXY_PREFIX + root
        if old_eq in body:
            body = body.replace(old_eq, new_eq)
    return body


def _inject_jingepi_assets(body: bytes) -> bytes:
    # 默认文档语言简体中文（用户仍可通过 i18nextLng 覆盖）
    if b'<html lang="en">' in body:
        body = body.replace(b'<html lang="en">', b'<html lang="zh-CN">', 1)
    elif b"<html lang='en'>" in body:
        body = body.replace(b"<html lang='en'>", b"<html lang='zh-CN'>", 1)
    if _INJECT_MARKER in body:
        return body
    lower = body.lower()
    # 尽早注入：CSS+JS 须在 type=module 的 Cinny 入口之前（先设 locale/theme）
    head = lower.find(b"<head")
    if head >= 0:
        gt = lower.find(b">", head)
        if gt >= 0:
            return body[: gt + 1] + _INJECT_SNIPPET + body[gt + 1 :]
    for needle in (b"</head>", b"</body>", b"</html>"):
        idx = lower.rfind(needle)
        if idx >= 0:
            return body[:idx] + _INJECT_SNIPPET + body[idx:]
    return body + _INJECT_SNIPPET


def _rewrite_config_homeserver(body: bytes) -> bytes:
    """按当前访问 Host 重写 homeserverList，避免写死穿透 IP 导致本机无法连服。"""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return body
    if not isinstance(data, dict):
        return body
    base = auth_config.client_facing_base_url(request)
    hs_list = data.get("homeserverList")
    if not isinstance(hs_list, list):
        hs_list = []
    # 当前访问根置顶；保留另一端（本机:1000 / 穿透）便于手动切换。
    # 不把无端口的 http://127.0.0.1 放进列表（易连到 80 端口）。
    others: list[str] = []
    for item in hs_list:
        if not isinstance(item, str):
            continue
        cleaned = item.strip().rstrip("/")
        if cleaned in ("http://127.0.0.1", "https://127.0.0.1", "http://localhost", "https://localhost"):
            continue
        if cleaned and cleaned != base and cleaned not in others:
            others.append(cleaned)
    local = "http://127.0.0.1:1000"
    public = auth_config.PUBLIC_BASE_URL.rstrip("/")
    for candidate in (local, public):
        if (
            candidate
            and candidate != base
            and candidate not in others
            and candidate
            not in (
                "http://127.0.0.1",
                "https://127.0.0.1",
            )
        ):
            others.append(candidate)
    data["homeserverList"] = [base, *others]
    data["defaultHomeserver"] = 0
    hr = data.get("hashRouter")
    if not isinstance(hr, dict):
        hr = {}
    hr["enabled"] = True
    hr.setdefault("basename", "/")
    data["hashRouter"] = hr
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _maybe_rewrite_body(body: bytes, content_type: str, *, subpath: str = "") -> bytes:
    ctype = (content_type or "").lower()
    textish = any(
        t in ctype
        for t in (
            "text/html",
            "javascript",
            "ecmascript",
            "text/css",
            "application/json",
            "text/json",
            "application/manifest",
            "text/plain",
        )
    )
    if not textish:
        return body
    clean = (subpath or "").lstrip("/")
    if clean == "config.json" or (
        "application/json" in ctype and clean.endswith("config.json")
    ):
        return _rewrite_config_homeserver(body)
    body = _rewrite_absolute_paths(body)
    if "text/html" in ctype:
        body = _inject_jingepi_assets(body)
    return body


def _serve_lab_asset(filename: str):
    path = _safe_lab_path(filename)
    if path is None:
        return Response(f"missing {filename}", status=404, mimetype="text/plain")
    return _lab_response(filename, _mime_for_lab(filename))


def _proxy(subpath: str):
    if not auth_config.CINNY_PROXY_ENABLED:
        return Response("Cinny proxy disabled", status=404)

    clean = (subpath or "").lstrip("/")
    if clean in _LAB_ASSETS or clean in _LAB_LOCALE_FILES:
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
        body = _maybe_rewrite_body(body, ctype, subpath=clean)
        return Response(
            body,
            status=e.code,
            headers=_filter_response_headers(e.headers),
        )
    except urllib.error.URLError as e:
        return Response(
            f"Cinny upstream unavailable: {e.reason}",
            status=502,
            mimetype="text/plain",
        )

    ctype = upstream.headers.get("Content-Type", "")
    # HTML / 文本类整体改写；大静态资源流式转发
    if any(
        t in ctype.lower()
        for t in (
            "text/html",
            "javascript",
            "ecmascript",
            "text/css",
            "application/json",
            "application/manifest",
        )
    ) or clean == "config.json":
        body = upstream.read()
        upstream.close()
        body = _maybe_rewrite_body(body, ctype, subpath=clean)
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


@cinny_proxy_bp.route("/cinny", methods=["GET", "HEAD"])
def proxy_cinny_root_redirect():
    return Response(status=308, headers={"Location": "/cinny/"})


@cinny_proxy_bp.route("/cinny/", defaults={"subpath": ""}, methods=["GET", "HEAD"])
@cinny_proxy_bp.route(
    "/cinny/<path:subpath>", methods=["GET", "HEAD", "POST"]
)
def proxy_cinny(subpath: str):
    return _proxy(subpath)


def register_cinny_proxy(app):
    if auth_config.CINNY_PROXY_ENABLED:
        app.register_blueprint(cinny_proxy_bp)
