"""同端口反代 Cinny Web，避免 /chat iframe 跨源，并挂子路径 /cinny/。

官方预构建以 base=/ 产出绝对路径（/assets、/config.json 等）；
本代理把上游根挂到 /cinny/，并对 HTML/JS/CSS/JSON 做路径改写。
hashRouter 开启后无需为 SPA 深链单独回退 index.html。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import mimetypes
import re
import threading
from functools import lru_cache
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urljoin

from flask import Blueprint, Response, request, stream_with_context

import auth_config

logger = logging.getLogger(__name__)

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

_INJECT_MARKER = b"lab-jingepi-cinny"

def _boot_inline_script() -> bytes:
    path = _STATIC_DIR / "lab-jingepi-cinny-boot.js"
    try:
        return b"<script>" + path.read_bytes() + b"</script>"
    except OSError:
        return b""


def _inject_snippet() -> bytes:
    return (
        _boot_inline_script()
        + b'<link rel="stylesheet" href="lab-jingepi-cinny.css">'
        + b'<script defer src="lab-jingepi-cinny.js"></script>'
    )

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

# Vite 产出带 content-hash 的文件名，内容不变可长期缓存
_HASHED_ASSET_RE = re.compile(
    r"^assets/.+-[A-Za-z0-9_-]+\.(?:js|css|mjs|wasm|ico|png|jpg|jpeg|gif|webp|svg|woff2?)$",
    re.I,
)

# subpath → (body, content-type, precomputed-gzip|None)
_ASSET_CACHE: dict[str, tuple[bytes, str, bytes | None]] = {}
_CACHE_DIR = Path(__file__).resolve().parent / "matrix" / "cinny-cache"
_APPLE_ICON_RE = re.compile(
    rb"<link\s[^>]*\brel=[\"']apple-touch-icon[\"'][^>]*>\s*",
    re.I | re.S,
)


def _client_accepts_gzip() -> bool:
    ae = (request.headers.get("Accept-Encoding") or "").lower()
    return "gzip" in ae


def _gzip_body(body: bytes) -> bytes:
    return gzip.compress(body, compresslevel=6)


def _etag_for(body: bytes) -> str:
    return f'"{hashlib.md5(body, usedforsecurity=False).hexdigest()}"'


def _cache_control_for(subpath: str) -> str:
    clean = (subpath or "").lstrip("/")
    if clean in _LAB_ASSETS or clean in _LAB_LOCALE_FILES:
        return "public, max-age=86400"
    if _HASHED_ASSET_RE.match(clean):
        return "public, max-age=31536000, immutable"
    if clean in ("config.json", "manifest.json", "sw.js"):
        return "no-cache"
    if not clean or clean == "index.html":
        return "no-cache"
    if clean.startswith("assets/"):
        return "public, max-age=86400"
    return "public, max-age=3600"


def _respond_bytes(
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "application/octet-stream",
    cache_control: str | None = None,
    extra_headers: list[tuple[str, str]] | None = None,
    gzip_cached: bytes | None = None,
) -> Response:
    """统一出站：ETag、Cache-Control、按客户端 Accept-Encoding 可选 gzip。"""
    headers: list[tuple[str, str]] = list(extra_headers or [])
    if cache_control:
        headers.append(("Cache-Control", cache_control))
    etag = _etag_for(body)
    headers.append(("ETag", etag))
    inm = request.headers.get("If-None-Match")
    if inm and inm.strip() == etag:
        return Response(status=304, headers=headers)

    if request.method == "HEAD":
        return Response(status=status, headers=headers)

    if _client_accepts_gzip():
        gz = gzip_cached
        if gz is None and _should_compress(content_type, body):
            gz = _gzip_body(body)
        if gz:
            headers.append(("Content-Encoding", "gzip"))
            headers.append(("Vary", "Accept-Encoding"))
            return Response(gz, status=status, headers=headers, mimetype=content_type)

    return Response(body, status=status, headers=headers, mimetype=content_type)


def _lab_response(filename: str, mime: str) -> Response:
    data = _lab_bytes(filename)
    return _respond_bytes(
        data,
        content_type=mime,
        cache_control=_cache_control_for(filename),
    )


@lru_cache(maxsize=16)
def _lab_bytes(filename: str) -> bytes:
    return (_STATIC_DIR / filename).read_bytes()


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
    if clean.endswith(".wasm"):
        return "application/wasm"
    return mimetypes.guess_type(clean)[0] or "application/octet-stream"


def _should_compress(content_type: str, body: bytes) -> bool:
    if len(body) <= 1024:
        return False
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return False
    return True


def _cache_storage_key(clean: str) -> str | None:
    if not clean or clean == "index.html":
        return "__index__"
    if _HASHED_ASSET_RE.match(clean) or clean in ("manifest.json", "sw.js"):
        return clean
    return None


def _store_asset_cache(clean: str, body: bytes, content_type: str) -> None:
    key = _cache_storage_key(clean)
    if key is None:
        return
    gz = _gzip_body(body) if _should_compress(content_type, body) else None
    _ASSET_CACHE[key] = (body, content_type, gz)
    _save_disk_cache(key, body, content_type, gz)


def _disk_entry_dir(key: str) -> Path:
    safe = key.replace("/", "__").replace("\\", "_")
    return _CACHE_DIR / safe


def _load_disk_cache() -> int:
    meta_path = _CACHE_DIR / "meta.json"
    if not meta_path.is_file():
        return 0
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return 0
    loaded = 0
    for key, info in meta.items():
        if key in _ASSET_CACHE:
            loaded += 1
            continue
        if not isinstance(info, dict):
            continue
        entry = _disk_entry_dir(key)
        raw_path = entry / "body"
        if not raw_path.is_file():
            continue
        body = raw_path.read_bytes()
        clean = "" if key == "__index__" else key
        ctype = str(info.get("ctype") or _guess_mime(clean))
        gz_path = entry / "body.gz"
        gz = gz_path.read_bytes() if gz_path.is_file() else None
        if gz is None and _should_compress(ctype, body):
            gz = _gzip_body(body)
        _ASSET_CACHE[key] = (body, ctype, gz)
        loaded += 1
    return loaded


def _save_disk_cache(
    key: str, body: bytes, content_type: str, gz: bytes | None
) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        entry = _disk_entry_dir(key)
        entry.mkdir(parents=True, exist_ok=True)
        (entry / "body").write_bytes(body)
        if gz:
            (entry / "body.gz").write_bytes(gz)
        meta_path = _CACHE_DIR / "meta.json"
        meta: dict = {}
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(meta, dict):
            meta = {}
        meta[key] = {"ctype": content_type}
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("Cinny 磁盘缓存写入失败 %s: %s", key, exc)


def _get_asset_cache(clean: str) -> tuple[bytes, str, bytes | None] | None:
    key = _cache_storage_key(clean)
    if key is None:
        return None
    return _ASSET_CACHE.get(key)


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
    # 必须 identity：后续要对 HTML/JS/CSS 做路径改写，不能拿到 gzip 二进制
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


def _trim_html_for_perf(body: bytes) -> bytes:
    """穿透高延迟：去掉 PWA 用 apple-touch-icon（10+ 次往返）。"""
    return _APPLE_ICON_RE.sub(b"", body)


def _inject_preloads(body: bytes) -> bytes:
    """提前拉主包，减少瀑布等待。"""
    inserts = b""
    if b"modulepreload" not in body[:4096]:
        m = re.search(rb'src="(/cinny/assets/index-[^"]+\.js)"', body)
        if m:
            inserts += b'<link rel="modulepreload" crossorigin href="' + m.group(1) + b'">'
    if inserts and b"<head" in body.lower():
        lower = body.lower()
        head = lower.find(b"<head")
        gt = lower.find(b">", head)
        if gt >= 0:
            return body[: gt + 1] + inserts + body[gt + 1 :]
    return body


def _inject_jingepi_assets(body: bytes) -> bytes:
    # 默认文档语言简体中文（用户仍可通过 i18nextLng 覆盖）
    if b'<html lang="en">' in body:
        body = body.replace(b'<html lang="en">', b'<html lang="zh-CN">', 1)
    elif b"<html lang='en'>" in body:
        body = body.replace(b"<html lang='en'>", b"<html lang='zh-CN'>", 1)
    body = _trim_html_for_perf(body)
    if _INJECT_MARKER not in body:
        lower = body.lower()
        # 尽早注入：CSS+JS 须在 type=module 的 Cinny 入口之前（先设 locale/theme）
        head = lower.find(b"<head")
        if head >= 0:
            gt = lower.find(b">", head)
            if gt >= 0:
                body = body[: gt + 1] + _inject_snippet() + body[gt + 1 :]
        else:
            for needle in (b"</head>", b"</body>", b"</html>"):
                idx = lower.rfind(needle)
                if idx >= 0:
                    body = body[:idx] + _inject_snippet() + body[idx:]
                    break
            else:
                body = body + _inject_snippet()
    return _inject_preloads(body)


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


def _fetch_upstream_bytes(clean: str) -> tuple[bytes, str, int]:
    """直连 Cinny 容器拉资源（预热/冷启动用）。"""
    url = _upstream_url(clean)
    req = urllib.request.Request(
        url,
        headers={"Accept-Encoding": "identity"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=120) as upstream:
        body = upstream.read()
        ctype = upstream.headers.get("Content-Type", "")
        status = upstream.status
    return body, ctype, status


def _prepare_asset(clean: str, body: bytes, content_type: str) -> tuple[bytes, str]:
    body = _maybe_rewrite_body(body, content_type, subpath=clean)
    ctype = _guess_mime(clean, content_type)
    _store_asset_cache(clean, body, ctype)
    return body, ctype


def _prewarm_cinny_cache() -> None:
    """后台预热：改写 + gzip 进内存，穿透首屏少等 Flask 现压缩。"""
    try:
        raw, ctype, _ = _fetch_upstream_bytes("")
        html, html_ct = _prepare_asset("", raw, ctype)
        assets = set(
            m.decode("utf-8", errors="replace")
            for m in re.findall(rb'(?:href|src)="/cinny/([^"]+)"', html)
        )
        for clean in assets:
            if not clean or clean in _LAB_ASSETS or clean in _LAB_LOCALE_FILES:
                continue
            if _get_asset_cache(clean) is not None:
                continue
            try:
                raw_b, raw_ct, _ = _fetch_upstream_bytes(clean)
                _prepare_asset(clean, raw_b, raw_ct)
            except Exception as exc:
                logger.debug("prewarm skip %s: %s", clean, exc)
        logger.info("Cinny 资源预热完成：%d 项", len(_ASSET_CACHE))
    except Exception as exc:
        logger.warning("Cinny 资源预热失败: %s", exc)


def _frame_extra_headers() -> list[tuple[str, str]]:
    return [("Content-Security-Policy", auth_config.frame_ancestors_csp_value())]


def _serve_cached(clean: str) -> Response | None:
    cached = _get_asset_cache(clean)
    if cached is None:
        return None
    body, ctype, gz = cached
    return _respond_bytes(
        body,
        content_type=ctype,
        cache_control=_cache_control_for(clean),
        extra_headers=_frame_extra_headers(),
        gzip_cached=gz,
    )


def _respond_prepared(
    clean: str,
    body: bytes,
    content_type: str,
    *,
    status: int = 200,
) -> Response:
    mime = _guess_mime(clean, content_type)
    _store_asset_cache(clean, body, mime)
    cached = _get_asset_cache(clean)
    gz = cached[2] if cached else None
    return _respond_bytes(
        body,
        status=status,
        content_type=mime,
        cache_control=_cache_control_for(clean),
        extra_headers=_frame_extra_headers(),
        gzip_cached=gz,
    )


def _guess_mime(clean: str, fallback: str = "") -> str:
    if fallback:
        return fallback
    if clean.endswith(".css"):
        return "text/css; charset=utf-8"
    if clean.endswith(".js") or clean.endswith(".mjs"):
        return "application/javascript; charset=utf-8"
    if clean.endswith(".json"):
        return "application/json; charset=utf-8"
    if clean.endswith(".html") or not clean:
        return "text/html; charset=utf-8"
    guessed, _ = mimetypes.guess_type(clean)
    return guessed or "application/octet-stream"


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

    served = _serve_cached(clean)
    if served is not None:
        return served

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
        return _respond_bytes(
            body,
            status=e.code,
            content_type=_guess_mime(clean, ctype),
            cache_control=_cache_control_for(clean),
            extra_headers=_frame_extra_headers(),
        )
    except urllib.error.URLError as e:
        return Response(
            f"Cinny upstream unavailable: {e.reason}",
            status=502,
            mimetype="text/plain",
        )

    ctype = upstream.headers.get("Content-Type", "")
    status = upstream.status
    # HTML / JS / CSS / JSON 整体改写；带 hash 的静态资源进内存缓存
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
        return _respond_prepared(clean, body, ctype, status=status)

    # 二进制：带 hash 的文件读入缓存
    if _HASHED_ASSET_RE.match(clean):
        body = upstream.read()
        upstream.close()
        return _respond_prepared(clean, body, ctype, status=status)

    def generate():
        try:
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    headers = _filter_response_headers(upstream.headers)
    cc = _cache_control_for(clean)
    if not any(k.lower() == "cache-control" for k, _ in headers):
        headers.append(("Cache-Control", cc))
    return Response(
        stream_with_context(generate()),
        status=status,
        headers=headers,
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
        loaded = _load_disk_cache()
        if loaded:
            logger.info("Cinny 磁盘缓存已加载 %d 项", loaded)
        if len(_ASSET_CACHE) < 3:
            threading.Thread(target=_prewarm_cinny_cache, daemon=True).start()
