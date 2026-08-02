from flask import Blueprint, render_template, request

home_bp = Blueprint("home", __name__)


@home_bp.route("/")
def index():
    modal = request.args.get("modal", "")
    return render_template(
        "home/index.html",
        open_modal=modal if modal in ("login", "register") else "",
    )
