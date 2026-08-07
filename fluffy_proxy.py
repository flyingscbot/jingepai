"""同端口反代 FluffyChat Web，避免 /chat iframe 跨源与 SSO auth.html 回调问题。

穿透高延迟场景：对大体积 JS/WASM 做内存+磁盘缓存与预压缩 gzip（main.dart.js 约 10MB→3MB），
启动时后台预热；HTML 仍按需改写 base href 与金格注入。
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import mimetypes
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path
import urllib.error
import urllib.request
from urllib.parse import urljoin

from flask import Blueprint, Response, request

import auth_config

logger = logging.getLogger(__name__)

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

_STATIC_DIR = Path(__file__).resolve().parent / "matrix" / "fluffy-static"
_LAB_ASSETS = {
    "lab-jingepi-fluffy.css": "text/css; charset=utf-8",
    "lab-jingepi-fluffy.js": "application/javascript; charset=utf-8",
    "auth.html": "text/html; charset=utf-8",
}

_INJECT_SNIPPET = (
    b'<link rel="stylesheet" href="lab-jingepi-fluffy.css">'
    b'<script src="lab-jingepi-fluffy.js"></script>'
)
_INJECT_MARKER = b"lab-jingepi-fluffy"

# subpath → (body, content-type, precomputed-gzip|None)
_ASSET_CACHE: dict[str, tuple[bytes, str, bytes | None]] = {}
_CACHE_DIR = Path(__file__).resolve().parent / "matrix" / "fluffy-cache"
_DISK_LOCK = threading.Lock()

_CACHEABLE_RE = re.compile(
    r"^(?:"
    r"main\.dart\.js(?:_\d+\.part\.js)?|"
    r"flutter(?:_bootstrap|_service_worker)?\.js|"
    r"Imaging\.(?:js|wasm)|"
    r"canvaskit/.+|"
    r"assets/.+|"
    r"icons/.+|"
    r"favicon\.png"
    r")$",
    re.I,
)

_SKIP_PREWARM_RE = re.compile(r"\.(?:map|symbols)$", re.I)

_PREWARM_PATHS = (
    "",
    "main.dart.js",
    "flutter.js",
    "canvaskit/canvaskit.js",
    "canvaskit/canvaskit.wasm",
)

_FLUFFY_CFG_PATH = Path(__file__).resolve().parent / "matrix" / "fluffychat-config.json"


def _client_accepts_gzip() -> bool:
    ae = (request.headers.get("Accept-Encoding") or "").lower()
    return "gzip" in ae


def _gzip_body(body: bytes) -> bytes:
    return gzip.compress(body, compresslevel=6)


def _etag_for(body: bytes) -> str:
    return f'"{hashlib.md5(body, usedforsecurity=False).hexdigest()}"'


def _should_compress(content_type: str, body: bytes) -> bool:
    if len(body) <= 1024:
        return False
    ct = (content_type or "").lower()
    if ct.startswith("image/"):
        return False
    return True


def _cache_control_for(subpath: str) -> str:
    clean = (subpath or "").lstrip("/")
    if clean in _LAB_ASSETS:
        return "public, max-age=86400"
    if clean in ("config.json", "flutter_service_worker.js"):
        return "no-cache"
    if not clean or clean == "index.html":
        return "no-cache"
    if _CACHEABLE_RE.match(clean):
        return "public, max-age=31536000, immutable"
    if clean.endswith((".js", ".wasm", ".css")):
        return "public, max-age=86400"
    return "public, max-age=3600"


def _cache_storage_key(clean: str) -> str | None:
    if not clean or clean == "index.html":
        return None
    if clean == "config.json":
        return None
    if _CACHEABLE_RE.match(clean):
        return clean
    return None


def _guess_mime(clean: str, fallback: str = "") -> str:
    if fallback:
        return fallback
    if clean.endswith(".css"):
        return "text/css; charset=utf-8"
    if clean.endswith(".js") or clean.endswith(".mjs"):
        return "application/javascript; charset=utf-8"
    if clean.endswith(".json"):
        return "application/json; charset=utf-8"
    if clean.endswith(".wasm"):
        return "application/wasm"
    if clean.endswith(".html") or not clean:
        return "text/html; charset=utf-8"
    guessed, _ = mimetypes.guess_type(clean)
    return guessed or "application/octet-stream"


def _frame_extra_headers() -> list[tuple[str, str]]:
    return [("Content-Security-Policy", auth_config.frame_ancestors_csp_value())]


def _respond_bytes(
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "application/octet-stream",
    cache_control: str | None = None,
    extra_headers: list[tuple[str, str]] | None = None,
    gzip_cached: bytes | None = None,
) -> Response:
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
        if key == "__index__":
            continue
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
        with _DISK_LOCK:
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
        logger.debug("FluffyChat 磁盘缓存写入失败 %s: %s", key, exc)


def _store_asset_cache(clean: str, body: bytes, content_type: str) -> None:
    key = _cache_storage_key(clean)
    if key is None:
        return
    # index / config 随 Host 与 domain.txt 变化，不缓存
    if key in ("__index__",):
        gz = _gzip_body(body) if _should_compress(content_type, body) else None
        _ASSET_CACHE[key] = (body, content_type, gz)
        return
    gz = _gzip_body(body) if _should_compress(content_type, body) else None
    _ASSET_CACHE[key] = (body, content_type, gz)
    _save_disk_cache(key, body, content_type, gz)


def _get_asset_cache(clean: str) -> tuple[bytes, str, bytes | None] | None:
    key = _cache_storage_key(clean)
    if key is None:
        return None
    return _ASSET_CACHE.get(key)


def _upstream_url(subpath: str) -> str:
    base = auth_config.FLUFFY_UPSTREAM.rstrip("/") + "/"
    return urljoin(base, subpath.lstrip("/"))


def _filter_request_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
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
            continue
        out.append((key, value))
    if not any(k.lower() == "content-security-policy" for k, _ in out):
        out.append(
            ("Content-Security-Policy", auth_config.frame_ancestors_csp_value())
        )
    return out


def _inject_homeserver_boot(body: bytes) -> bytes:
    """在 Flutter 启动前同步写入 homeserver（须随 Host 动态生成，不能缓存 index）。"""
    base = auth_config.client_facing_base_url(request).rstrip("/")
    marker = b'id="__jingepi_homeserver_boot__"'
    snippet = (
        b'<script id="__jingepi_homeserver_boot__">window.__JINGEPI_HOMESERVER__='
        + json.dumps(base).encode("utf-8")
        + b";</script>"
    )
    if marker in body:
        # 替换已有 boot 块（base 随 Host 变化）
        start = body.find(b'<script id="__jingepi_homeserver_boot__"')
        if start >= 0:
            end = body.find(b"</script>", start)
            if end >= 0:
                return body[:start] + snippet + body[end + len(b"</script>") :]
    lower = body.lower()
    head = lower.find(b"<head")
    if head < 0:
        return body
    gt = lower.find(b">", head)
    if gt < 0:
        return body
    return body[: gt + 1] + snippet + body[gt + 1 :]


def _inject_jingepi_assets(body: bytes) -> bytes:
    if _INJECT_MARKER in body:
        return body
    lower = body.lower()
    for needle in (b"</body>", b"</html>"):
        idx = lower.rfind(needle)
        if idx >= 0:
            return body[:idx] + _INJECT_SNIPPET + body[idx:]
    return body + _INJECT_SNIPPET


def _inject_preloads(body: bytes) -> bytes:
    """穿透：提前声明主包与本地 CanvasKit，缩短瀑布。"""
    if b'rel="preload"' in body[:8192]:
        return body
    inserts = (
        b'<link rel="preload" href="main.dart.js" as="script">'
        b'<link rel="preload" href="flutter.js" as="script">'
        b'<link rel="preload" href="canvaskit/canvaskit.js" as="script">'
        b'<link rel="preload" href="canvaskit/canvaskit.wasm" as="fetch" crossorigin>'
    )
    lower = body.lower()
    head = lower.find(b"<head")
    if head < 0:
        return body
    gt = lower.find(b">", head)
    if gt < 0:
        return body
    return body[: gt + 1] + inserts + body[gt + 1 :]


def _rewrite_config_json(body: bytes) -> bytes:
    """按当前访问根改写 defaultHomeserver，避免 domain.txt 变更后仍读旧缓存。"""
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return body
    if not isinstance(data, dict):
        return body
    base = auth_config.client_facing_base_url(request).rstrip("/")
    data["defaultHomeserver"] = base
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _load_config_template() -> bytes:
    if _FLUFFY_CFG_PATH.is_file():
        return _FLUFFY_CFG_PATH.read_bytes()
    raw, _, _ = _fetch_upstream_bytes("config.json")
    return raw


def _serve_config_json() -> Response:
    body = _rewrite_config_json(_load_config_template())
    return _respond_bytes(
        body,
        content_type="application/json; charset=utf-8",
        cache_control="no-cache",
        extra_headers=_frame_extra_headers(),
        gzip_cached=_gzip_body(body),
    )


def _maybe_rewrite_html(body: bytes, content_type: str) -> bytes:
    if "text/html" not in (content_type or "").lower():
        return body
    if _BASE_HREF_OLD in body:
        body = body.replace(_BASE_HREF_OLD, _BASE_HREF_NEW, 1)
    body = _inject_homeserver_boot(body)
    body = _inject_preloads(body)
    return _inject_jingepi_assets(body)


@lru_cache(maxsize=16)
def _lab_bytes(filename: str) -> bytes:
    return (_STATIC_DIR / filename).read_bytes()


def _serve_lab_asset(filename: str):
    if filename not in _LAB_ASSETS:
        return Response(f"missing {filename}", status=404, mimetype="text/plain")
    mime = _LAB_ASSETS[filename]
    if filename == "auth.html":
        data = (_STATIC_DIR / "auth.html").read_bytes()
        return _respond_bytes(
            data,
            content_type=mime,
            cache_control="no-cache",
            extra_headers=_frame_extra_headers(),
            gzip_cached=_gzip_body(data) if _should_compress(mime, data) else None,
        )
    return _respond_bytes(
        _lab_bytes(filename),
        content_type=mime,
        cache_control=_cache_control_for(filename),
        extra_headers=_frame_extra_headers(),
        gzip_cached=_gzip_body(_lab_bytes(filename)),
    )


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


def _fetch_upstream_bytes(clean: str) -> tuple[bytes, str, int]:
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
    if not clean or clean == "index.html":
        body = _maybe_rewrite_html(body, content_type)
    mime = _guess_mime(clean, content_type)
    _store_asset_cache(clean, body, mime)
    return body, mime


def _is_prewarm_candidate(rel: str) -> bool:
    if not rel or rel in _LAB_ASSETS:
        return False
    if _SKIP_PREWARM_RE.search(rel):
        return False
    if rel.startswith("canvaskit/") and rel.endswith(".symbols"):
        return False
    return _cache_storage_key(rel) is not None


def _docker_public_paths() -> list[str] | None:
    """从 FluffyChat 容器枚举静态文件列表（本机 Docker 可用时）。"""
    try:
        proc = subprocess.run(
            [
                "docker",
                "exec",
                "matrix-fluffychat-1",
                "find",
                "/home/sws/public",
                "-type",
                "f",
            ],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    prefix = "/home/sws/public/"
    out: list[str] = []
    for line in proc.stdout.splitlines():
        line = line.strip().replace("\\", "/")
        if not line.startswith(prefix):
            continue
        rel = line[len(prefix) :]
        if _is_prewarm_candidate(rel):
            out.append(rel)
    return out or None


def _discover_prewarm_paths() -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []

    def add(path: str) -> None:
        if path not in seen:
            seen.add(path)
            paths.append(path)

    for p in _PREWARM_PATHS:
        add(p)

    docker_paths = _docker_public_paths()
    if docker_paths:
        for rel in docker_paths:
            add(rel)
    else:
        for i in range(1, 280):
            add(f"main.dart.js_{i}.part.js")

    return paths


def _prewarm_one(clean: str) -> None:
    if _get_asset_cache(clean) is not None:
        return
    try:
        raw, ctype, _ = _fetch_upstream_bytes(clean)
        _prepare_asset(clean, raw, ctype)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            logger.debug("FluffyChat 预热失败 %s: HTTP %s", clean or "index", e.code)
    except Exception as exc:
        logger.debug("FluffyChat 预热跳过 %s: %s", clean or "index", exc)


def _prewarm_fluffy_cache() -> None:
    """后台并行预热：穿透首访尽量命中内存/磁盘 gzip 缓存。"""
    todo = [p for p in _discover_prewarm_paths() if _get_asset_cache(p) is None]
    if not todo:
        logger.info("FluffyChat 资源已预热：%d 项", len(_ASSET_CACHE))
        return
    workers = min(4, max(2, len(todo) // 6))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_prewarm_one, clean) for clean in todo]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:
                logger.debug("FluffyChat 预热任务异常: %s", exc)
    logger.info("FluffyChat 资源预热完成：%d 项（本轮 %d）", len(_ASSET_CACHE), len(todo))


def _proxy(subpath: str, *, rewrite_base: bool = True):
    if not auth_config.FLUFFY_PROXY_ENABLED:
        return Response("FluffyChat proxy disabled", status=404)

    clean = (subpath or "").lstrip("/")
    if clean in _LAB_ASSETS:
        return _serve_lab_asset(clean)
    if clean == "config.json":
        return _serve_config_json()

    if rewrite_base or _cache_storage_key(clean) is not None:
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
        upstream = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        body = e.read()
        ctype = e.headers.get("Content-Type", "")
        if rewrite_base:
            body = _maybe_rewrite_html(body, ctype)
        return _respond_bytes(
            body,
            status=e.code,
            content_type=_guess_mime(clean, ctype),
            cache_control=_cache_control_for(clean),
            extra_headers=_frame_extra_headers(),
        )
    except urllib.error.URLError as e:
        return Response(
            f"FluffyChat upstream unavailable: {e.reason}",
            status=502,
            mimetype="text/plain",
        )

    ctype = upstream.headers.get("Content-Type", "")
    status = upstream.status

    if rewrite_base and "text/html" in ctype.lower():
        body = upstream.read()
        upstream.close()
        body = _maybe_rewrite_html(body, ctype)
        return _respond_prepared(clean, body, ctype, status=status)

    if _cache_storage_key(clean) is not None:
        body = upstream.read()
        upstream.close()
        return _respond_prepared(clean, body, ctype, status=status)

    body = upstream.read()
    upstream.close()
    mime = _guess_mime(clean, ctype)
    return _respond_bytes(
        body,
        status=status,
        content_type=mime,
        cache_control=_cache_control_for(clean),
        extra_headers=_frame_extra_headers(),
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
    """FluffyChat SSO 回调写在 origin/auth.html，须挂在站点根路径。"""
    return _serve_lab_asset("auth.html")


def register_fluffy_proxy(app):
    if auth_config.FLUFFY_PROXY_ENABLED:
        app.register_blueprint(fluffy_proxy_bp)
        loaded = _load_disk_cache()
        if loaded:
            logger.info("FluffyChat 磁盘缓存已加载 %d 项", loaded)
        if len(_ASSET_CACHE) < 12:
            threading.Thread(target=_prewarm_fluffy_cache, daemon=True).start()
