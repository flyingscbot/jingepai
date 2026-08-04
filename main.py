from flask import Flask, request, jsonify, session, redirect, url_for, render_template, send_from_directory, abort
from functools import wraps
import datetime
import os
import re

from home import home_bp
import user_db
import mbti_ai
import mbti_log
import trade_history

app = Flask(__name__)
app.secret_key = "train_2026_abc123"
app.permanent_session_lifetime = datetime.timedelta(hours=2)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 上传最大 50MB
app.config["TEMPLATES_AUTO_RELOAD"] = True

app.register_blueprint(home_bp)

user_db.bootstrap()

# 不显示功能 TAB 的页面
_NO_TAB_ENDPOINTS = (
    "home.index",
    "main",
    "account_settings",
    "account_security",
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
        return f(*args, **kwargs)
    return decorated_function


def _current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return user_db.get_user_by_id(user_id)


def _set_login_session(user: dict) -> None:
    user_db.ensure_user_folder(user)
    trade_history.ensure_history_csv(user["id"])
    mbti_log.ensure_log_csv(user["id"])
    session["is_login"] = True
    session["user_id"] = user["id"]
    session["username"] = user["username"]
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
        _set_login_session(user)
        return jsonify({"success": True, "message": "登录成功"})
    return jsonify({"success": False, "message": "用户名或密码错误"})


@app.route("/main")
@login_required
def main():
    return render_template("main.html")


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
        log_row = mbti_log.append_record(user["id"], result["mbti"])
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
    return render_template("chat.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home.index"))


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
    app.run(host="127.0.0.1", port=1000, debug=True, use_reloader=True)
