from flask import Blueprint, render_template, request
from urllib.parse import urlencode
import json

import auth_config
home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def index():
    # FluffyChat SSO：loginToken 落在站点根时，用 HTML 回传凭证（302 无法在弹窗里跑脚本）
    token = request.args.get("loginToken")
    if token and auth_config.FLUFFY_PROXY_ENABLED:
        qs = urlencode(request.args.to_dict(flat=True))
        base = auth_config.client_facing_base_url(request).rstrip("/")
        href = base + "/"
        if qs:
            href += "?" + qs
        fluffy_dest = (
            (auth_config.FLUFFY_PROXY_PATH.rstrip("/") or "/fluffychat") + "/"
        )
        if qs:
            fluffy_dest += "?" + qs
        href_js = json.dumps(href)
        dest_js = json.dumps(fluffy_dest)
        return (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            "<title>登录完成</title></head><body>"
            "<script>"
            "(function(){"
            f"var href={href_js};"
            "var payload={'flutter-web-auth-2':href};"
            "var origin=window.location.origin;"
            "try{localStorage.setItem('flutter-web-auth-2',href);}catch(e){}"
            "if(window.opener){try{window.opener.postMessage(payload,origin);}catch(e){}"
            "try{window.close();}catch(e){}}else{"
            f"window.location.replace({dest_js});" "}"
            "})();"
            "</script></body></html>",
            200,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    modal = request.args.get("modal", "")
    return render_template(
        "home/index.html",
        open_modal=modal if modal in ("login", "register") else "",
    )
