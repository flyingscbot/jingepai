from flask import Blueprint, redirect, render_template, request
from urllib.parse import urlencode

import auth_config

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def index():
    # FluffyChat SSO 若 loginToken 落在站点根，转发到 /fluffychat/
    if request.args.get("loginToken") and auth_config.FLUFFY_PROXY_ENABLED:
        qs = urlencode(request.args.to_dict(flat=True))
        base = (auth_config.FLUFFY_PROXY_PATH.rstrip("/") or "/fluffychat") + "/"
        return redirect(f"{base}?{qs}" if qs else base, code=302)

    modal = request.args.get("modal", "")
    return render_template(
        "home/index.html",
        open_modal=modal if modal in ("login", "register") else "",
    )
