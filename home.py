from flask import Blueprint, redirect, render_template, request
from urllib.parse import urlencode

import auth_config

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def index():
    # Cinny SSO 若 redirectUrl 误落在站点根（缺 /cinny），Synapse 会带回 loginToken。
    # 转发到 /cinny/ 让 hashRouter 完成 token 登录，避免主站黑底空白。
    if request.args.get("loginToken") and auth_config.CINNY_PROXY_ENABLED:
        qs = urlencode(request.args.to_dict(flat=True))
        base = (auth_config.CINNY_PROXY_PATH.rstrip("/") or "/cinny") + "/"
        return redirect(f"{base}?{qs}" if qs else base, code=302)

    modal = request.args.get("modal", "")
    return render_template(
        "home/index.html",
        open_modal=modal if modal in ("login", "register") else "",
    )
