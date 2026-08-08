from flask import Flask, request, jsonify, session, redirect, url_for, render_template, send_from_directory, abort
from functools import wraps
import datetime
import importlib.util
import os
import re
from pathlib import Path

# 须在 import auth_config 之前：读 domain.txt、必要时同步 yaml/json，并写入 PUBLIC_BASE_URL
def _sync_domain_before_auth_config() -> None:
    apply_path = Path(__file__).resolve().parent / "matrix" / "apply_public_base.py"
    if not apply_path.is_file():
        print(f"[domain] 未找到 {apply_path}，跳过 Matrix 配置同步")
        return
    spec = importlib.util.spec_from_file_location("apply_public_base", apply_path)
    if spec is None or spec.loader is None:
        print("[domain] 无法加载 apply_public_base，跳过同步")
        return
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
        mod.sync_for_flask_start(recreate_on_change=True)
    except Exception as e:
        print(f"[domain] 启动同步失败（Flask 仍会启动）: {e}")


_sync_domain_before_auth_config()

import auth_config
from home import home_bp
import user_db
import mbti_ai
import mbti_algo
import mbti_log
import room_type
import trade_history
import matrix_theme
from fluffy_proxy import register_fluffy_proxy
from matrix_proxy import register_matrix_proxy
from oidc_provider import init_oidc
import synapse_admin

app = Flask(__name__)
app.secret_key = "train_2026_abc123"
app.permanent_session_lifetime = datetime.timedelta(hours=2)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 上传最大 50MB
app.config["TEMPLATES_AUTO_RELOAD"] = True

# 本地 HTTP：避免 Secure + SameSite=None（Cursor Simple Browser / 明文 HTTP 会拒收）
if auth_config.oidc_uses_http():
    app.config["SESSION_COOKIE_SECURE"] = False
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
else:
    app.config["SESSION_COOKIE_SECURE"] = True
    # HTTPS 生产若需跨站嵌入可改为 "None"
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True

app.register_blueprint(home_bp)

user_db.bootstrap()
matrix_theme.ensure_seeded()
init_oidc(app)
register_fluffy_proxy(app)
register_matrix_proxy(app)
# 不显示功能 TAB 的页面
_NO_TAB_ENDPOINTS = (
    "home.index",
    "chat",
    "account_settings",
    "account_security",
    "jingepi_console",
)


@app.context_processor
def inject_user():
    user_id = session.get("user_id")
    username = session.get("username", "")
    return {
        "is_login": bool(session.get("is_login")),
        "username": username,
        "avatar": user_db.avatar_url(user_id, username or "guest"),
        "show_float_nav": bool(
            session.get("is_login") and request.endpoint not in _NO_TAB_ENDPOINTS
        ),
    }


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("is_login"):
            return redirect(url_for("home.index", modal="login"))
        user = _current_user()
        if not user or not user.get("is_active", True):
            session.clear()
            return redirect(url_for("home.index", modal="login"))
        return f(*args, **kwargs)
    return decorated_function


def _admin_api_denied(status: int, message: str):
    return jsonify({"success": False, "message": message}), status


def admin_required(f):
    """登录 + role 为 admin / super_admin；可选 ADMIN_CONSOLE_TOKEN 额外门禁。"""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        wants_json = request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json"
        if not session.get("is_login"):
            if wants_json or request.path.startswith("/api/"):
                return _admin_api_denied(401, "请先登录")
            return redirect(url_for("home.index", modal="login"))
        user = _current_user()
        if not user or not user.get("is_active", True):
            session.clear()
            if wants_json or request.path.startswith("/api/"):
                return _admin_api_denied(401, "账号已停用或未登录")
            return redirect(url_for("home.index", modal="login"))
        if not user_db.is_console_role(user.get("role")):
            if wants_json or request.path.startswith("/api/"):
                return _admin_api_denied(403, "需要管理员权限")
            abort(403)
        token = (os.environ.get("ADMIN_CONSOLE_TOKEN") or "").strip()
        if token:
            provided = (
                request.args.get("token")
                or request.headers.get("X-Admin-Console-Token")
                or ""
            ).strip()
            if provided != token:
                if wants_json or request.path.startswith("/api/"):
                    return _admin_api_denied(403, "管理控制台令牌无效")
                abort(403)
        return f(*args, **kwargs)

    return decorated_function


def _actor_is_super_admin(actor: dict | None) -> bool:
    return bool(actor and user_db.is_super_admin_role(actor.get("role")))


def _deny_plain_admin_target(actor: dict, target: dict) -> tuple | None:
    """普通管理不可操作 admin / super_admin。"""
    if _actor_is_super_admin(actor):
        return None
    if target.get("role") != user_db.ROLE_USER:
        return _admin_api_denied(403, "普通管理只能操作普通用户账号")
    return None


def _current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = user_db.get_user_by_id(user_id)
    if user and not user.get("is_active", True):
        return None
    return user


def _set_login_session(user: dict) -> None:
    user_db.ensure_user_folder(user)
    trade_history.ensure_history_csv(user["id"])
    mbti_log.ensure_log_csv(user["id"])
    session["is_login"] = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["role"] = user.get("role") or user_db.DEFAULT_ROLE
    session.permanent = True


@app.route("/user_assets/<folder>/<path:filename>")
def user_assets(folder, filename):
    if not re.fullmatch(r"[0-9a-f]{32}", folder):
        abort(404)
    if ".." in filename or filename.startswith(("/", "\\")):
        abort(404)
    directory = os.path.join(user_db.USERS_DIR, folder)
    if not os.path.isdir(directory):
        abort(404)
    return send_from_directory(directory, filename)


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return redirect(url_for("home.index", modal="login"))
    if not request.is_json:
        return jsonify({"success": False, "message": "请提交JSON数据"})
    data = request.get_json()
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username or not password:
        return jsonify({"success": False, "message": "账号密码不能为空"})

    user = user_db.get_user_by_name(username)
    if user and user_db.verify_password(user, password):
        if not user.get("is_active", True):
            return jsonify({"success": False, "message": "账号已停用，无法登录"}), 403
        _set_login_session(user)
        return jsonify({"success": True, "message": "登录成功"})
    return jsonify({"success": False, "message": "用户名或密码错误"})


@app.route("/main")
@login_required
def main():
    return redirect(url_for("trade"))


@app.route("/account_settings")
@login_required
def account_settings():
    user = _current_user()
    if not user:
        return redirect(url_for("logout"))
    return render_template(
        "account_settings.html",
        user=user,
        avatar_src=user_db.avatar_url(user["id"], user["username"]),
    )


@app.route("/account_security")
@login_required
def account_security():
    user = _current_user()
    if not user:
        return redirect(url_for("logout"))
    return render_template("account_security.html", user=user)


@app.route("/api/settings/username", methods=["POST"])
@login_required
def api_update_username():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    data = request.get_json(silent=True) or {}
    try:
        updated = user_db.update_username(user["id"], data.get("username", ""))
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    session["username"] = updated["username"]
    # Matrix 会话可能仍登录：Admin API 即时推送 displayname；
    # 另：下次 SSO 登录也会经 OIDC name + sso.update_profile_information 同步。
    try:
        synapse_admin.set_displayname(updated["id"], updated["username"])
    except Exception:
        app.logger.exception("同步 Matrix displayname 失败（金格用户名已更新）")
    return jsonify({"success": True, "message": "用户名已更新", "username": updated["username"]})


@app.route("/api/settings/avatar", methods=["POST"])
@login_required
def api_update_avatar():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    file = request.files.get("avatar")
    try:
        url = user_db.save_avatar_upload(user["id"], file)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "上传失败，请稍后重试"})
    # 金格本地头像 → Synapse 媒体库 mxc → Admin API 设 avatar_url
    try:
        synapse_admin.set_avatar(user["id"])
    except Exception:
        app.logger.exception("同步 Matrix avatar 失败（金格头像已更新）")
    return jsonify({"success": True, "message": "头像已更新", "avatar": url})


@app.route("/api/settings/password", methods=["POST"])
@login_required
def api_update_password():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    data = request.get_json(silent=True) or {}
    try:
        user_db.update_password(
            user["id"],
            data.get("old_password") or "",
            data.get("new_password") or "",
        )
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    return jsonify({"success": True, "message": "密码已更新"})


@app.route("/mbti")
@login_required
def mbti():
    user = _current_user()
    if not user:
        return redirect(url_for("logout"))
    user_db.ensure_user_folder(user)
    trade_history.ensure_history_csv(user["id"])
    mbti_log.ensure_log_csv(user["id"])
    all_rows = trade_history.load_all_records(user["id"])
    recent = trade_history.recent_records_for_ai(user["id"])
    return render_template(
        "mbti.html",
        user=user,
        history_total=len(all_rows),
        history_used=len(recent),
        history_limit=trade_history.MBTI_RECORD_LIMIT,
        mbti_types=mbti_log.MBTI_TYPES,
    )


@app.route("/api/mbti/analyze", methods=["POST"])
@login_required
def api_mbti_analyze():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    try:
        result = mbti_ai.analyze_mbti_for_user(user["id"])
        prev = mbti_log.latest_record(user["id"])
        algo_tags = result.get("algo_tags") or ""
        dims = mbti_algo.split_tags(algo_tags)
        log_row = mbti_log.append_record(user["id"], result["mbti"], dims=dims)
        rows = mbti_log.load_all_records(user["id"])
        suggested = room_type.apply_suggested_room_type(
            user["id"],
            role=user.get("role"),
            mbti_type=result["mbti"],
            algo_code=(result.get("algo") or {}).get("code"),
            confidence=result.get("algo_confidence"),
            rows=rows,
        )
        result["suggested_room_type"] = suggested
        input_hash = result.pop("input_hash", None)
        if input_hash:
            mbti_log.save_input_hash(user["id"], input_hash)
        result["log_time"] = log_row["时间"]
        result["changed"] = bool(prev and prev.get("类型") != log_row["类型"])
        result["prev_type"] = (prev or {}).get("类型", "")
    except mbti_ai.AlreadyAnalyzedError as e:
        return jsonify(
            {
                "success": False,
                "code": e.code,
                "message": str(e),
            }
        )
    except mbti_ai.AnalyzeInProgressError as e:
        return jsonify(
            {
                "success": False,
                "code": e.code,
                "message": str(e),
            }
        )
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "分析失败，请稍后重试"})
    return jsonify({"success": True, "message": "分析完成，已写入 MBTI_log.csv", "result": result})


@app.route("/my-mbti")
@login_required
def my_mbti():
    user = _current_user()
    if not user:
        return redirect(url_for("logout"))
    user_db.ensure_user_folder(user)
    mbti_log.ensure_log_csv(user["id"])
    points = mbti_log.change_points(user["id"])
    latest = points[-1] if points else None
    transitions = [p for p in points if p.get("prev_type") and p.get("类型") != p.get("prev_type")]
    owned_types = sorted(
        {p.get("类型") for p in points if p.get("类型") in mbti_log.MBTI_LEVEL},
        key=lambda t: mbti_log.MBTI_LEVEL[t],
    )
    icon_urls = {
        t: url_for("static", filename=f"icons/{mbti_log.MBTI_ICONS[t]}")
        for t in owned_types
        if t in mbti_log.MBTI_ICONS
    }
    return render_template(
        "my_mbti.html",
        user=user,
        latest=latest,
        points=points,
        transitions=transitions,
        show_ray=len(owned_types) > 0,
        ray_types=owned_types,
        mbti_types=mbti_log.MBTI_TYPES,
        mbti_level=mbti_log.MBTI_LEVEL,
        mbti_icons=icon_urls,
    )


@app.route("/trade")
@login_required
def trade():
    user = _current_user()
    if not user:
        return redirect(url_for("logout"))
    user_db.ensure_user_folder(user)
    trade_history.ensure_history_csv(user["id"])
    files = user_db.list_trade_files(user["id"])
    now = datetime.datetime.now()
    latest_date = trade_history.latest_trade_date(user["id"])
    return render_template(
        "trade.html",
        user=user,
        trade_files=files,
        calendar_year=now.year,
        calendar_month=now.month,
        latest_trade_date=latest_date or "",
    )


@app.route("/api/trade/upload", methods=["POST"])
@login_required
def api_trade_upload():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    file = request.files.get("file")
    try:
        item = user_db.save_trade_file(user["id"], file)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "上传失败，请稍后重试"})
    return jsonify({"success": True, "message": "上传成功", "file": item})


@app.route("/api/trade/delete", methods=["POST"])
@login_required
def api_trade_delete():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    data = request.get_json(silent=True) or {}
    try:
        user_db.delete_trade_file(user["id"], data.get("name") or "")
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "删除失败，请稍后重试"})
    return jsonify({"success": True, "message": "已删除"})


@app.route("/api/trade/download/<path:filename>")
@login_required
def api_trade_download(filename):
    user = _current_user()
    if not user:
        abort(401)
    try:
        safe_name = user_db.safe_trade_filename(filename)
    except ValueError:
        abort(404)
    directory = user_db.trade_dir(user["id"])
    path = os.path.join(directory, safe_name)
    if not os.path.isfile(path):
        abort(404)
    return send_from_directory(directory, safe_name, as_attachment=True)


@app.route("/api/trade/organize", methods=["POST"])
@login_required
def api_trade_organize():
    """从已上传文件自动整理交易记录（AI API 预留），去重追加到 CSV。"""
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    try:
        result = trade_history.organize_from_user_files(user["id"])
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "整理失败，请稍后重试"})
    msg = f"整理完成：新增 {result['added']} 条，跳过重复 {result['skipped']} 条"
    return jsonify({"success": True, "message": msg, **result})


@app.route("/api/trade/history/dates")
@login_required
def api_trade_history_dates():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    try:
        year = int(request.args.get("year") or 0)
        month = int(request.args.get("month") or 0)
        if year < 1970 or month < 1 or month > 12:
            raise ValueError("年月无效")
        dates = trade_history.list_dates_in_month(user["id"], year, month)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "获取失败"})
    return jsonify({"success": True, "dates": dates})


@app.route("/api/trade/history/by-date")
@login_required
def api_trade_history_by_date():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    date = (request.args.get("date") or "").strip()
    try:
        records = trade_history.list_records_by_date(user["id"], date)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "获取失败"})
    return jsonify({"success": True, "date": date, "records": records})


@app.route("/api/trade/history/all")
@login_required
def api_trade_history_all():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    try:
        records = trade_history.list_all_records_indexed(user["id"])
    except Exception:
        return jsonify({"success": False, "message": "获取失败"})
    return jsonify({"success": True, "records": records, "total": len(records)})


@app.route("/api/trade/history/update", methods=["POST"])
@login_required
def api_trade_history_update():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    data = request.get_json(silent=True) or {}
    try:
        row_index = int(data.get("row_index"))
        rec = trade_history.update_record_by_index(user["id"], row_index, data)
    except (TypeError, ValueError) as e:
        return jsonify({"success": False, "message": str(e) if str(e) else "参数无效"})
    except Exception:
        return jsonify({"success": False, "message": "更新失败，请稍后重试"})
    return jsonify({"success": True, "message": "已更新", "record": rec})


@app.route("/api/trade/history/add", methods=["POST"])
@login_required
def api_trade_history_add():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    data = request.get_json(silent=True) or {}
    try:
        rec = trade_history.add_record(user["id"], data)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "添加失败，请稍后重试"})
    return jsonify({"success": True, "message": "已添加", "record": rec})


@app.route("/api/trade/history/delete", methods=["POST"])
@login_required
def api_trade_history_delete():
    user = _current_user()
    if not user:
        return jsonify({"success": False, "message": "未登录"}), 401
    data = request.get_json(silent=True) or {}
    try:
        row_index = int(data.get("row_index"))
        trade_history.delete_record_by_index(user["id"], row_index)
    except (TypeError, ValueError) as e:
        return jsonify({"success": False, "message": str(e) if str(e) else "参数无效"})
    except Exception:
        return jsonify({"success": False, "message": "删除失败，请稍后重试"})
    return jsonify({"success": True, "message": "已删除"})


@app.route("/chat")
@login_required
def chat():
    # 嵌入 FluffyChat（同源 /fluffychat/）
    chat_url = auth_config.chat_embed_path()
    return render_template(
        "chat.html",
        chat_url=chat_url,
    )


@app.route("/api/matrix/capabilities", methods=["GET"])
def api_matrix_capabilities():
    """客户端用于隐藏建群/建空间入口；服务端 createRoom 仍会再校验。

    鉴权：金格 Session，或 Matrix Bearer（localpart = users.id）。
    """
    from matrix_proxy import resolve_jingepi_user_from_matrix_token

    user = None
    uid = session.get("user_id")
    if uid:
        user = user_db.get_user_by_id(uid)
    if user is None:
        user = resolve_jingepi_user_from_matrix_token()

    if user is None or not user.get("is_active", True):
        return jsonify(
            {
                "success": True,
                "can_create_room": False,
                "can_create_space": False,
                "role": None,
            }
        )

    allowed = user_db.can_create_matrix_rooms(user.get("role"))
    return jsonify(
        {
            "success": True,
            "can_create_room": allowed,
            "can_create_space": allowed,
            "role": user.get("role"),
            "role_label": user.get("role_label")
            or user_db.ROLE_LABELS.get(user.get("role") or "", ""),
        }
    )


@app.route("/jingepi-console")
@admin_required
def jingepi_console():
    """隐藏管理后台入口（不在任何导航中挂链）。"""
    user = _current_user()
    return render_template(
        "jingepi_console.html",
        user=user,
        is_super_admin=_actor_is_super_admin(user),
    )


@app.route("/api/admin/users", methods=["GET"])
@admin_required
def api_admin_list_users():
    q = (request.args.get("q") or request.args.get("username") or "").strip()
    users = user_db.list_users(q=q or None)
    return jsonify({"success": True, "users": users, "total": len(users)})


@app.route("/api/admin/users", methods=["POST"])
@admin_required
def api_admin_create_user():
    actor = _current_user()
    data = request.get_json(silent=True) or {}
    role = (data.get("role") or user_db.DEFAULT_ROLE).strip().lower()
    if not _actor_is_super_admin(actor):
        if role != user_db.ROLE_USER:
            return _admin_api_denied(403, "普通管理只能创建普通用户")
        role = user_db.ROLE_USER
    try:
        created = user_db.create_user(
            (data.get("username") or "").strip(),
            data.get("password") or "",
            role=role,
        )
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "创建失败，请稍后重试"})
    return jsonify(
        {
            "success": True,
            "message": "用户已创建",
            "user": user_db.public_user(created),
        }
    )


@app.route("/api/admin/users/<user_id>", methods=["PATCH", "PUT"])
@admin_required
def api_admin_update_user(user_id):
    actor = _current_user()
    data = request.get_json(silent=True) or {}
    before = user_db.get_user_by_id(user_id)
    if not before:
        return jsonify({"success": False, "message": "用户不存在"}), 404

    denied = _deny_plain_admin_target(actor, before)
    if denied:
        return denied

    kwargs = {}
    if _actor_is_super_admin(actor):
        if "username" in data:
            kwargs["username"] = data.get("username")
        if "password" in data:
            kwargs["password"] = data.get("password")
        if "role" in data:
            kwargs["role"] = data.get("role")
        if "is_active" in data:
            kwargs["is_active"] = bool(data.get("is_active"))
    else:
        # 普通管理：仅可对 user 重置密码 / 启停
        if "username" in data or "role" in data:
            return _admin_api_denied(
                403, "普通管理不能修改用户名或角色"
            )
        if "password" in data:
            kwargs["password"] = data.get("password")
        if "is_active" in data:
            kwargs["is_active"] = bool(data.get("is_active"))
        if not kwargs:
            return jsonify({"success": False, "message": "没有可更新的字段"})

    try:
        updated = user_db.admin_update_user(user_id, **kwargs)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "更新失败，请稍后重试"})

    # 用户名变更 → 同步 Matrix displayname
    if (
        "username" in kwargs
        and updated["username"] != before["username"]
    ):
        try:
            synapse_admin.set_displayname(updated["id"], updated["username"])
        except Exception:
            app.logger.exception("管理后台同步 Matrix displayname 失败")

    # 停用 / 恢复 → 尽量同步 Matrix
    if "is_active" in kwargs and bool(kwargs["is_active"]) != bool(
        before.get("is_active", True)
    ):
        try:
            synapse_admin.set_deactivated(
                updated["id"], deactivated=not updated.get("is_active", True)
            )
        except Exception:
            app.logger.exception("管理后台同步 Matrix 停用状态失败")

    # 若停用了当前管理员自己，清 session
    if (
        updated["id"] == session.get("user_id")
        and not updated.get("is_active", True)
    ):
        session.clear()

    return jsonify(
        {
            "success": True,
            "message": "已更新",
            "user": user_db.public_user(updated),
        }
    )


@app.route("/api/admin/users/<user_id>", methods=["DELETE"])
@admin_required
def api_admin_delete_user(user_id):
    """硬删除：仅最高管理。从 users.db 删除，并尽量停用/擦除 Matrix 账号。"""
    actor = _current_user()
    if not _actor_is_super_admin(actor):
        return _admin_api_denied(403, "仅最高管理可硬删除用户")
    if user_id == session.get("user_id"):
        return jsonify({"success": False, "message": "不能删除当前登录账号"})
    before = user_db.get_user_by_id(user_id)
    if not before:
        return jsonify({"success": False, "message": "用户不存在"}), 404
    try:
        deleted = user_db.delete_user(user_id)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "删除失败，请稍后重试"})
    try:
        synapse_admin.erase_user(deleted["id"])
    except Exception:
        app.logger.exception("管理后台同步 Matrix 硬删除失败")
    return jsonify(
        {
            "success": True,
            "message": "已永久删除该账号",
            "user": deleted,
        }
    )


def _require_super_admin_api():
    actor = _current_user()
    if not _actor_is_super_admin(actor):
        return _admin_api_denied(403, "仅最高管理可管理 Matrix 主题")
    return None


@app.route("/api/admin/matrix-theme", methods=["GET"])
@admin_required
def api_admin_matrix_theme_get():
    denied = _require_super_admin_api()
    if denied:
        return denied
    return jsonify(matrix_theme.api_payload())


@app.route("/api/admin/matrix-theme", methods=["PUT"])
@admin_required
def api_admin_matrix_theme_put():
    denied = _require_super_admin_api()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    colors = data.get("colors")
    if not isinstance(colors, dict) or not colors:
        return jsonify({"success": False, "message": "请提交 colors 对象"}), 400
    try:
        saved = matrix_theme.save_colors(colors)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 400
    except Exception:
        app.logger.exception("保存 Matrix 主题失败")
        return jsonify({"success": False, "message": "保存失败，请稍后重试"}), 500
    payload = matrix_theme.api_payload()
    payload["message"] = "主题色已保存；请对 /fluffychat/ 硬刷新后查看"
    payload["colors"] = saved
    return jsonify(payload)


@app.route("/api/admin/matrix-theme/reset", methods=["POST"])
@admin_required
def api_admin_matrix_theme_reset():
    denied = _require_super_admin_api()
    if denied:
        return denied
    try:
        saved = matrix_theme.reset_colors()
    except Exception:
        app.logger.exception("重置 Matrix 主题失败")
        return jsonify({"success": False, "message": "重置失败，请稍后重试"}), 500
    payload = matrix_theme.api_payload()
    payload["message"] = "已恢复默认主题色；请对 /fluffychat/ 硬刷新后查看"
    payload["colors"] = saved
    return jsonify(payload)


@app.route("/logout")
def logout():
    session.clear()
    return render_template("logout.html", redirect_url=url_for("home.index"))


@app.route("/register", methods=["GET", "POST"])
def register_page():
    if request.method == "GET":
        return redirect(url_for("home.index", modal="register"))

    if not request.is_json:
        return jsonify({"success": False, "message": "请提交JSON数据"})
    data = request.get_json()
    un = (data.get("username") or "").strip()
    pw = data.get("password") or ""
    if not un or not pw:
        return jsonify({"success": False, "message": "账号密码不能为空"})

    try:
        user_db.create_user(un, pw)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)})
    except Exception:
        return jsonify({"success": False, "message": "注册失败，请稍后重试"})

    return jsonify({"success": True, "message": "注册成功"})


if __name__ == "__main__":
    # 需 0.0.0.0 以便 Docker 内 Synapse 经 host.docker.internal 访问 OIDC
    # 启动早期已 sync domain.txt → yaml/json（有变才 recreate）；auth_config 读 PUBLIC_BASE_URL
    print(f"[jingepi] PUBLIC_BASE_URL = {auth_config.PUBLIC_BASE_URL}")

    # 房间分配守护线程：仅在 reloader 子进程启动，避免父进程重复起一个
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        import threading
        import room_allocator

        _room_thread = threading.Thread(
            target=room_allocator.run_in_thread,
            name="room_allocator",
            daemon=True,
        )
        _room_thread.start()
        print("[jingepi] 房间分配守护线程已启动（每 30 秒同步）")

    # threaded：Matrix sync 长轮询不能堵死其它 /fluffychat、/_matrix 请求
    app.run(
        host="0.0.0.0",
        port=1000,
        debug=True,
        use_reloader=True,
        threaded=True,
    )
