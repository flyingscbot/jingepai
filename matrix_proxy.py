"""Same-origin reverse proxy for Synapse client/OIDC under Flask :1000.

Keeps Element SSO on one origin so:
- iframe /chat can show Synapse SSO pages (strip X-Frame-Options)
- browsers accept OIDC session cookies on plain HTTP (strip Secure from Set-Cookie)
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from urllib.parse import urljoin

from flask import Blueprint, Response, request, stream_with_context

import auth_config

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


def _filter_request_headers() -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in request.headers:
        lk = key.lower()
        if lk in _HOP_BY_HOP:
            continue
        headers[key] = value
    # Synapse public_baseurl is :1000 — must present Host as browser-facing
    # or Synapse 302-loops back to the same SSO URL forever.
    headers["Host"] = request.host
    headers["X-Forwarded-Host"] = request.host
    headers["X-Forwarded-Proto"] = request.scheme
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
            value = re.sub(
                r"frame-ancestors[^;]*;?",
                "frame-ancestors 'self' http://127.0.0.1:1000 http://localhost:1000;",
                value,
                flags=re.I,
            )
            if "frame-ancestors" not in value.lower():
                value = (
                    value.rstrip(" ;")
                    + "; frame-ancestors 'self' http://127.0.0.1:1000 http://localhost:1000"
                )
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


def _proxy(subpath: str):
    if not auth_config.SYNAPSE_PROXY_ENABLED:
        return Response("Synapse proxy disabled", status=404)

    path = subpath if subpath.startswith("/") else "/" + subpath
    if request.method == "POST" and _DEACTIVATE_RE.match(path):
        return _blocked_deactivate_response()
    if _ROOM_KEYS_RE.match(path):
        return _blocked_room_keys_response()

    url = _upstream(path)
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
    """Expose Synapse client/server well-known on the Flask origin (:1000).

    Element and probes use http://127.0.0.1:1000/.well-known/matrix/client
    (includes io.element.e2ee.force_disable from extra_well_known_client_content).
    Does not overlap OIDC /.well-known/openid-configuration.
    """
    return _proxy("/.well-known/matrix/" + subpath)


def register_matrix_proxy(app):
    if auth_config.SYNAPSE_PROXY_ENABLED:
        app.register_blueprint(matrix_proxy_bp)
