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
import os
import re
import urllib.error
import urllib.request
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse

from flask import Blueprint, Response, jsonify, request, stream_with_context

import auth_config
import synapse_admin
import user_db

logger = logging.getLogger(__name__)

# #region debug-point helper:log-reporter
_DEBUG_ENV_PATH = os.path.join(os.path.dirname(__file__), ".dbg", "fluffychat-public-rooms.env")
_DEBUG_SERVER_URL = "http://127.0.0.1:7777/event"
_DEBUG_SESSION_ID = "fluffychat-public-rooms"
try:
    if os.path.exists(_DEBUG_ENV_PATH):
        with open(_DEBUG_ENV_PATH, "r", encoding="utf-8") as _f:
            for _line in _f:
                if _line.startswith("DEBUG_SERVER_URL="):
                    _DEBUG_SERVER_URL = _line.strip().split("=", 1)[1]
                elif _line.startswith("DEBUG_SESSION_ID="):
                    _DEBUG_SESSION_ID = _line.strip().split("=", 1)[1]
except Exception:
    pass


def _debug_log(hypothesis_id: str, msg: str, data: dict | None = None, run_id: str = "pre-fix") -> None:
    try:
        payload = json.dumps({
            "sessionId": _DEBUG_SESSION_ID,
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": "matrix_proxy.py",
            "msg": f"[DEBUG] {msg}",
            "data": data or {},
        }).encode("utf-8")
        req = urllib.request.Request(_DEBUG_SERVER_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=2)
    except Exception:
        pass
# #endregion

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
    # Synapse public_baseurl 固定本机；上游 Host 始终用 canonical，避免穿透 Host
    # 触发 SSO 规范化 302 死循环（Location 改回穿透后反复 /login/sso/redirect）。
    local = auth_config.LOCAL_SYNAPSE_PUBLIC_BASE
    local_parsed = urlparse(local)
    synapse_host = local_parsed.netloc or "127.0.0.1:1000"
    synapse_proto = local_parsed.scheme or "http"
    headers["Host"] = synapse_host
    headers["X-Forwarded-Host"] = synapse_host
    headers["X-Forwarded-Proto"] = synapse_proto
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
    """按客户端可见根改写上游 Location。

    Synapse public_baseurl 固定为本机（LOCAL_SYNAPSE_PUBLIC_BASE），SSO/OIDC
  浏览器链从 127.0.0.1 发起。穿透访问时把 Location 中的本机根改写到当前穿透根；
    本机访问时若 Location 仍带穿透根（旧配置残留），改回当前本机根。

    同时重写 redirect_uri 参数中的回环域名：Synapse 用 public_baseurl 生成
    redirect_uri（固定 127.0.0.1），但浏览器从 localhost 访问时 session cookie
    绑定到 localhost。若不重写 redirect_uri，OAuth 回调会落到 127.0.0.1，
    cookie 不发送 → "No session cookie found"。
    """
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return value

    facing = auth_config.client_facing_base_url(request).rstrip("/")
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    suffix = parsed.path or ""
    if parsed.query:
        suffix += f"?{parsed.query}"
    if parsed.fragment:
        suffix += f"#{parsed.fragment}"

    if origin == facing:
        return value

    req_host = (request.host or "").split(",")[0].strip()
    is_local_client = auth_config._is_loopback_host(req_host.split(":")[0])

    local = auth_config.LOCAL_SYNAPSE_PUBLIC_BASE.rstrip("/")
    local_origins = {
        local,
        "http://127.0.0.1",
        "http://127.0.0.1:1000",
        "http://localhost",
        "http://localhost:1000",
        "https://127.0.0.1",
        "https://127.0.0.1:1000",
        "https://localhost",
        "https://localhost:1000",
    }
    pub = auth_config.PUBLIC_BASE_URL.rstrip("/")

    if not is_local_client and origin in local_origins:
        new_location = facing + suffix
    elif is_local_client and pub and (origin == pub or value.startswith(pub + "/")):
        new_location = facing + suffix
    elif origin in (local_origins | ({pub} if pub else set())):
        new_location = facing + suffix
    else:
        return value

    if new_location != value:
        new_location = _rewrite_redirect_uri_in_location(new_location, facing)
    return new_location


def _rewrite_redirect_uri_in_location(location: str, target_base: str) -> str:
    """重写 Location URL 中 redirect_uri 参数的回环域名/端口。

    当 Location 的 origin 被改写（例如 127.0.0.1→localhost 或→穿透根）时，
    query 里的 redirect_uri 仍指向 Synapse 的 public_baseurl（127.0.0.1），
    须同步改写为 target_base，确保 OAuth 回调与 session cookie 同源。
    仅改写回环地址，避免误伤已指向公网的 redirect_uri。
    """
    parsed = urlparse(location)
    if not parsed.query:
        return location

    target = urlparse(target_base)
    target_netloc = target.netloc
    if not target_netloc:
        return location

    params = parse_qsl(parsed.query, keep_blank_values=True)
    modified = False
    new_params: list[tuple[str, str]] = []
    for key, val in params:
        if key == "redirect_uri" and val:
            ru = urlparse(val)
            if ru.scheme in ("http", "https") and ru.netloc:
                if ru.hostname and auth_config._is_loopback_host(ru.hostname):
                    new_ru = ru._replace(scheme=target.scheme, netloc=target_netloc)
                    val = new_ru.geturl()
                    modified = True
        new_params.append((key, val))

    if not modified:
        return location
    new_query = urlencode(new_params)
    return parsed._replace(query=new_query).geturl()


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

_PUBLIC_ROOMS_RE = re.compile(
    r"^/_matrix/client/(?:r0|v3|unstable)/publicRooms/?$",
    re.I,
)

# delete_devices / devices/{id}: 需 UIA 认证；密码禁用时走 SSO fallback，
# 但 FluffyChat 在 iframe 内，oidc_session cookie（SameSite=Lax）在 iframe
# 导航时不发送 → OIDC callback "no session cookie"。代理用 admin API 绕过 UIA。
_DELETE_DEVICES_RE = re.compile(
    r"^/_matrix/client/(?:r0|v3|unstable)/delete_devices/?$",
    re.I,
)
_DELETE_DEVICE_RE = re.compile(
    r"^/_matrix/client/(?:r0|v3|unstable)/devices/([^/]+)/?$",
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


def _delete_devices_via_admin(devices: list[str], mxid: str) -> tuple[int, int]:
    """用 Synapse admin v2 API 批量删除设备，绕过 UIA。返回 (成功数, 失败数)。

    注意：Synapse 1.158 设备管理 admin API 在 v2 路径（v1 返回 M_UNRECOGNIZED）。
    """
    admin_token = synapse_admin.ensure_admin_token()
    if not admin_token:
        logger.error("delete_devices: 无可用 admin token")
        return 0, len(devices)
    quoted_user = quote(mxid, safe="")
    ok = 0
    fail = 0
    for device_id in devices:
        did = quote(str(device_id), safe="")
        # v2 API: /_synapse/admin/v2/users/{user_id}/devices/{device_id}
        url = _upstream(f"/_synapse/admin/v2/users/{quoted_user}/devices/{did}")
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {admin_token}", "Accept": "application/json"},
            method="DELETE",
        )
        try:
            with _OPENER.open(req, timeout=10) as resp:
                if 200 <= resp.status < 300:
                    ok += 1
                else:
                    fail += 1
                    logger.warning("删除设备 %s 返回 HTTP %s", device_id, resp.status)
        except urllib.error.HTTPError as e:
            fail += 1
            try:
                body = e.read().decode()[:200]
            except Exception:
                body = ""
            logger.error("删除设备 %s 失败: HTTP %s - %s", device_id, e.code, body)
        except Exception as e:
            fail += 1
            logger.error("删除设备 %s 异常: %s", device_id, e)
    return ok, fail


def _handle_delete_devices(data: bytes) -> Response | None:
    """拦截 POST delete_devices：用 admin API 绕过 UIA（iframe 内 SSO cookie 丢失）。

    返回 None 表示无法处理，放行让 Synapse 走原生 UIA fallback。
    """
    try:
        body = json.loads(data.decode("utf-8")) if data else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        body = {}
    devices = body.get("devices") if isinstance(body, dict) else None
    if not devices or not isinstance(devices, list):
        return None
    token = _bearer_token()
    if not token:
        return None
    mxid = _whoami_user_id(token)
    if not mxid:
        return None
    ok, fail = _delete_devices_via_admin(devices, mxid)
    logger.info("delete_devices 拦截: %s 删除 %d 设备 (%d 失败)", mxid, ok, fail)
    return Response("{}", status=200, mimetype="application/json")


def _handle_delete_device(device_id: str) -> Response | None:
    """拦截 DELETE devices/{deviceId}：用 admin API 绕过 UIA。"""
    token = _bearer_token()
    if not token:
        return None
    mxid = _whoami_user_id(token)
    if not mxid:
        return None
    ok, fail = _delete_devices_via_admin([device_id], mxid)
    logger.info("delete_device 拦截: %s 删除设备 %s (%s)", mxid, device_id, "成功" if ok else "失败")
    return Response("{}", status=200, mimetype="application/json")


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
        # 管理员创建房间时，自动设置 visibility: public + preset: public_chat 使其可搜索发现
        try:
            body_obj = json.loads(data.decode("utf-8")) if data else {}
            logger.info("createRoom: original body=%s", json.dumps(body_obj)[:200])
            if isinstance(body_obj, dict) and body_obj.get("visibility") != "public":
                user = resolve_jingepi_user_from_matrix_token()
                logger.info("createRoom: resolved user=%s", json.dumps(user)[:200] if user else "None")
                if user and user.get("role") in ("admin", "super_admin") and user.get("is_active", True):
                    # 私聊（DM）保持 visibility: private
                    if not body_obj.get("is_direct"):
                        body_obj["visibility"] = "public"
                        # 将 preset 改为 public_chat，使房间对所有人可加入
                        body_obj["preset"] = "public_chat"
                        # 设置 world_readable 使房间对所有人可读
                        body_obj["world_readable"] = True
                        data = json.dumps(body_obj).encode("utf-8")
                        logger.info("createRoom: auto-set visibility=public + preset=public_chat + world_readable for admin user %s", user.get("id"))
                    else:
                        logger.info("createRoom: is_direct room, keeping private")
                else:
                    logger.info("createRoom: user not admin/active, skip injection")
        except Exception as e:
            logger.warning("createRoom visibility injection failed: %s", e, exc_info=True)

    # delete_devices / devices/{id}: 用 admin API 绕过 UIA（iframe 内 SSO cookie 丢失）
    if request.method == "POST" and _DELETE_DEVICES_RE.match(path):
        resp = _handle_delete_devices(data)
        if resp is not None:
            return resp
        # 无法解析 token/设备列表时放行，让 Synapse 走原生 UIA fallback
    elif request.method == "DELETE":
        m = _DELETE_DEVICE_RE.match(path)
        if m:
            resp = _handle_delete_device(m.group(1))
            if resp is not None:
                return resp

    # Re-encode decoded PATH_INFO (# in #alias:server) before urllib upstream fetch.
    url = _upstream(_encode_path_for_upstream(path))
    # #region debug-point A:publicRooms-request
    if _PUBLIC_ROOMS_RE.match(path):
        _debug_log("A", "publicRooms request received", {
            "method": request.method,
            "path": path,
            "query": request.query_string.decode('latin-1') if request.query_string else "",
            "body": data.decode('utf-8') if data else None,
        })
    # #endregion
    if request.query_string:
        qs = request.query_string.decode('latin-1')
        # 对于 publicRooms 请求，去掉 server 参数（避免联邦请求失败）
        if _PUBLIC_ROOMS_RE.match(path) and 'server=' in qs:
            from urllib.parse import parse_qsl, urlencode
            params = dict(parse_qsl(qs, keep_blank_values=True))
            params.pop('server', None)
            qs = urlencode(params)
            # #region debug-point A:server-stripped
            _debug_log("A", "publicRooms server parameter stripped", {"new_qs": qs})
            # #endregion
            logger.info("publicRooms: stripped server parameter")
        url = f"{url}?{qs}"

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

    # 对于 createRoom 请求，读取完整响应体，获取 room_id，然后设置 canonical alias
    if request.method == "POST" and _CREATE_ROOM_RE.match(path):
        response_headers = dict(upstream.headers)
        response_body = upstream.read()
        upstream.close()
        try:
            resp_json = json.loads(response_body.decode("utf-8"))
            room_id = resp_json.get("room_id")
            if room_id and data:
                # 检查原始请求体是否被修改为 public
                orig_body = json.loads(data.decode("utf-8"))
                if orig_body.get("visibility") == "public":
                    user = resolve_jingepi_user_from_matrix_token()
                    if user and user.get("role") in ("admin", "super_admin"):
                        room_name = orig_body.get("name", "公开房间")
                        import re as _re
                        import time as _time
                        alias_base = _re.sub(r'[^\w\u4e00-\u9fff-]', '_', room_name)[:30]
                        alias_localpart = f"{alias_base}_{int(_time.time())}"
                        alias_localpart = _re.sub(r'_+', '_', alias_localpart).strip('_')
                        alias_name = f"#{alias_localpart}:matrix.localhost"
                        token = _bearer_token()

                        # Step 1: Set canonical alias via state event
                        alias_body = json.dumps({
                            "type": "m.room.canonical_alias",
                            "state_key": "",
                            "content": {"alias": alias_name}
                        }).encode()
                        url_alias = _upstream(f"/_matrix/client/v3/rooms/{room_id}/state/m.room.canonical_alias")
                        req_alias = urllib.request.Request(url_alias, data=alias_body, headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                            "Accept": "application/json"
                        }, method="PUT")
                        try:
                            r_alias = _OPENER.open(req_alias, timeout=15)
                            r_alias.read()
                            logger.info("Set canonical alias %s for room %s", alias_name, room_id)
                        except Exception as e_alias:
                            logger.warning("Failed to set canonical alias: %s", e_alias)

                        # Step 2: Publish to directory
                        try:
                            from urllib.parse import quote as _quote
                            dir_body = json.dumps({
                                "room_id": room_id,
                                "state_key": ""
                            }).encode()
                            url_dir = _upstream(f"/_matrix/client/v3/directory/room/{_quote(alias_name, safe='')}")
                            req_dir = urllib.request.Request(url_dir, data=dir_body, headers={
                                "Authorization": f"Bearer {token}",
                                "Content-Type": "application/json",
                                "Accept": "application/json"
                            }, method="PUT")
                            r_dir = _OPENER.open(req_dir, timeout=15)
                            r_dir.read()
                            logger.info("Published room %s to directory as %s", room_id, alias_name)
                        except Exception as e_dir:
                            logger.warning("Failed to publish to directory: %s", e_dir)

                        # Step 3: Ensure join_rules is public
                        try:
                            rules_body = json.dumps({
                                "join_rule": "public"
                            }).encode()
                            url_rules = _upstream(f"/_matrix/client/v3/rooms/{room_id}/state/m.room.join_rules")
                            req_rules = urllib.request.Request(url_rules, data=rules_body, headers={
                                "Authorization": f"Bearer {token}",
                                "Content-Type": "application/json",
                                "Accept": "application/json"
                            }, method="PUT")
                            r_rules = _OPENER.open(req_rules, timeout=15)
                            r_rules.read()
                            logger.info("Set join_rules=public for room %s", room_id)
                        except Exception as e_rules:
                            logger.warning("Failed to set join_rules: %s", e_rules)
        except Exception as e:
            logger.warning("createRoom post-processing failed: %s", e, exc_info=True)
        
        return Response(
            response_body,
            status=200,
            headers=_filter_response_headers(response_headers),
            mimetype="application/json",
        )

    # 对于 publicRooms 请求，读取响应体，修复 total_room_count 为 chunk 长度
    if request.method in ("GET", "POST") and _PUBLIC_ROOMS_RE.match(path):
        response_headers = dict(upstream.headers)
        response_body = upstream.read()
        upstream.close()
        try:
            resp_json = json.loads(response_body.decode("utf-8"))
            chunk = resp_json.get("chunk", [])
            # #region debug-point B:publicRooms-raw-response
            _debug_log("B", "publicRooms raw upstream response", {
                "total_room_count": resp_json.get("total_room_count"),
                "chunk_length": len(chunk),
                "first_room": chunk[0] if chunk else None,
            })
            # #endregion
            if isinstance(chunk, list) and len(chunk) > 0:
                # Fix total_room_count
                current_total = resp_json.get("total_room_count", 0)
                if current_total == 0:
                    resp_json["total_room_count"] = len(chunk)
                
                token = _bearer_token()
                for room in chunk:
                    # Set world_readable to True for all public rooms
                    if not room.get("world_readable", False):
                        room["world_readable"] = True
                    # Set guest_can_join to True for all public rooms
                    if not room.get("guest_can_join", False):
                        room["guest_can_join"] = True
                    # Inject canonical_alias if missing
                    if not room.get("canonical_alias") and token:
                        try:
                            from urllib.parse import quote as _quote
                            rid = room.get("room_id", "")
                            if rid:
                                encoded_rid = _quote(rid, safe="")
                                url_state = _upstream(f"/_matrix/client/v3/rooms/{encoded_rid}/state/m.room.canonical_alias")
                                req_state = urllib.request.Request(url_state, headers={
                                    "Authorization": f"Bearer {token}",
                                    "Accept": "application/json"
                                }, method="GET")
                                r_state = _OPENER.open(req_state, timeout=5)
                                b_state = json.loads(r_state.read().decode())
                                alias = b_state.get("content", {}).get("alias")
                                if alias:
                                    room["canonical_alias"] = alias
                        except Exception:
                            pass  # Silently ignore if alias lookup fails
                
                response_body = json.dumps(resp_json).encode("utf-8")
                # #region debug-point B:publicRooms-processed-response
                _debug_log("B", "publicRooms processed response", {
                    "total_room_count": resp_json.get("total_room_count"),
                    "chunk_length": len(chunk),
                    "first_room": chunk[0] if chunk else None,
                })
                # #endregion
                logger.info("publicRooms: processed %d rooms", len(chunk))
        except Exception as e:
            logger.warning("publicRooms post-processing failed: %s", e)
        
        return Response(
            response_body,
            status=200,
            headers=_filter_response_headers(response_headers),
            mimetype="application/json",
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
