from flask import Blueprint, render_template, request, session

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def index():
    modal = request.args.get("modal", "")
    return render_template(
        "home/index.html",
        is_login=bool(session.get("is_login")),
        username=session.get("username", ""),
        open_modal=modal if modal in ("login", "register") else "",
    )
