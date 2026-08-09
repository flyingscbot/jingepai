"""沙盘路由：行情/详情/交易/持仓/评论/管理。

全部挂到 sandbox_bp。使用 JINGEPI 账户系统；管理类路由加 @permission_required。
模板位于 templates/sandbox/ 目录。
"""
from datetime import datetime
from functools import wraps
from flask import render_template, request, jsonify, redirect, url_for, session, make_response

from . import sandbox_bp
from .db import (
    get_session, sync_user_from_session, Stock, Fund, Holding, Order,
    Comment, Watchlist, CommentModerationLog, User, PriceHistory,
)
from .permissions import (
    get_current_user, permission_required, ROLE_LABELS, ASSIGNABLE_ROLES,
    COMMENT_DAILY_LIMIT, today_comment_count,
)
from . import trade
from . import market_data

# JINGEPI 登录页重定向
_JINGEPI_LOGIN_REDIRECT = lambda: redirect(url_for("home.index", modal="login"))


def _no_cache(view):
    """装饰器：禁止浏览器缓存页面，确保切换用户后不会显示旧数据。"""
    @wraps(view)
    def wrapped(*args, **kwargs):
        resp = view(*args, **kwargs)
        if isinstance(resp, str):
            resp = make_response(resp)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    return wrapped


def _ctx_user():
    """返回当前用户上下文 dict（用于模板），未登录返回 None。"""
    u = get_current_user()
    if u is None:
        return None
    return {"id": u.id, "username": u.username, "role": u.role,
            "role_label": ROLE_LABELS.get(u.role, u.role), "cash": float(u.cash)}


# ====================================================================== 行情
@sandbox_bp.route("/market")
@_no_cache
def market_page():
    u = _ctx_user()
    if u is None:
        return _JINGEPI_LOGIN_REDIRECT()
    s = get_session()
    try:
        stocks = s.query(Stock).order_by(Stock.pct_chg.desc()).all()
        funds = s.query(Fund).order_by(Fund.est_pct.desc()).all()
        stock_list = [_stock_brief(s) for s in stocks]
        fund_list = [_fund_brief(f) for f in funds]
        any_stale = any(s.stale for s in stocks) or any(f.stale for f in funds)
        return render_template("sandbox/market.html", user=u, stocks=stock_list, funds=fund_list,
                               any_stale=any_stale, market_open=market_data.is_trading_hours())
    finally:
        s.close()


def _stock_brief(s):
    return {"code": s.code, "name": s.name, "price": float(s.price or 0),
            "pct_chg": float(s.pct_chg or 0), "chg": float(s.chg or 0),
            "stale": s.stale, "updated": (s.updated_at or datetime.now()).strftime("%H:%M:%S")}


def _fund_brief(f):
    return {"code": f.code, "name": f.name, "unit_nav": float(f.unit_nav or 0),
            "est_nav": float(f.est_nav or 0), "est_pct": float(f.est_pct or 0),
            "acc_nav": float(f.acc_nav or 0), "stale": f.stale, "fund_type": f.fund_type or "",
            "updated": (f.updated_at or datetime.now()).strftime("%H:%M:%S")}


@sandbox_bp.route("/market/search")
def search():
    q = request.args.get("q", "").strip()
    kind = request.args.get("kind", "stock")
    if kind == "fund":
        return jsonify({"success": True, "data": market_data.search_funds(q)})
    return jsonify({"success": True, "data": market_data.search_stocks(q)})


# ====================================================================== 详情
@sandbox_bp.route("/market/<kind>/<code>")
@_no_cache
def detail_page(kind, code):
    code = str(code).zfill(6)
    u = _ctx_user()
    if u is None:
        return _JINGEPI_LOGIN_REDIRECT()
    s = get_session()
    try:
        if kind == "stock":
            obj = s.query(Stock).get(code)
            if not obj:
                return ("未找到该股票", 404)
            info = {"kind": "stock", "code": obj.code, "name": obj.name,
                    "price": float(obj.price or 0), "pct_chg": float(obj.pct_chg or 0),
                    "chg": float(obj.chg or 0), "open": float(obj.open or 0),
                    "high": float(obj.high or 0), "low": float(obj.low or 0),
                    "pre_close": float(obj.pre_close or 0), "turnover": float(obj.turnover or 0),
                    "pe": float(obj.pe or 0), "pb": float(obj.pb or 0),
                    "stale": obj.stale, "updated": (obj.updated_at or datetime.now()).strftime("%H:%M:%S")}
        else:
            obj = s.query(Fund).get(code)
            if not obj:
                return ("未找到该基金", 404)
            info = {"kind": "fund", "code": obj.code, "name": obj.name,
                    "unit_nav": float(obj.unit_nav or 0), "acc_nav": float(obj.acc_nav or 0),
                    "est_nav": float(obj.est_nav or 0), "est_pct": float(obj.est_pct or 0),
                    "fund_type": obj.fund_type or "", "nav_date": obj.nav_date.isoformat() if obj.nav_date else "",
                    "stale": obj.stale, "updated": (obj.updated_at or datetime.now()).strftime("%H:%M:%S")}

        # 当前用户该标的持仓
        h = s.query(Holding).filter(
            Holding.user_id == u["id"], Holding.kind == kind, Holding.code == code
        ).first()
        holding = None
        if h:
            holding = {"total_shares": float(h.total_shares),
                       "available_shares": float(h.available_shares),
                       "frozen_shares": float(h.frozen_shares),
                       "avg_cost": float(h.avg_cost)}
        # 评论限额信息
        cmt_limit = COMMENT_DAILY_LIMIT.get(u["role"])
        cmt_used = today_comment_count(u["id"])
        cmt_remaining = (cmt_limit - cmt_used) if cmt_limit is not None else None
        return render_template("sandbox/detail.html", user=u, info=info, holding=holding,
                               market_open=market_data.is_trading_hours(),
                               cmt_remaining=cmt_remaining)
    finally:
        s.close()


@sandbox_bp.route("/market/<kind>/<code>/history")
def history_json(kind, code):
    code = str(code).zfill(6)
    if kind == "stock":
        data = market_data.get_stock_history(code)
    else:
        data = market_data.get_fund_history(code)
    return jsonify({"success": True, "data": data})


# ====================================================================== 交易
@sandbox_bp.route("/api/order", methods=["POST"])
def place_order():
    u = _ctx_user()
    if u is None:
        return jsonify({"success": False, "message": "请先登录"}), 401
    data = request.get_json() or {}
    kind = data.get("kind")
    side = data.get("side")
    code = data.get("code")
    try:
        shares = data.get("shares")
        amount = data.get("amount")
    except Exception:
        shares = amount = None

    if kind == "stock" and side == "buy":
        if shares is None:
            return jsonify({"success": False, "message": "缺少股数"})
        res = trade.buy_stock(u["id"], code, shares)
    elif kind == "stock" and side == "sell":
        if shares is None:
            return jsonify({"success": False, "message": "缺少股数"})
        res = trade.sell_stock(u["id"], code, shares)
    elif kind == "fund" and side == "subscribe":
        if amount is None:
            return jsonify({"success": False, "message": "缺少金额"})
        res = trade.subscribe_fund(u["id"], code, amount)
    elif kind == "fund" and side == "redeem":
        if shares is None:
            return jsonify({"success": False, "message": "缺少份额"})
        res = trade.redeem_fund(u["id"], code, shares)
    else:
        return jsonify({"success": False, "message": "无效的交易请求"}), 400
    return jsonify(res)


# ====================================================================== 持仓
@sandbox_bp.route("/portfolio")
@_no_cache
def portfolio_page():
    u = _ctx_user()
    if u is None:
        return _JINGEPI_LOGIN_REDIRECT()
    summary = trade.portfolio_summary(u["id"])
    return render_template("sandbox/portfolio.html", user=u, summary=summary)


@sandbox_bp.route("/api/portfolio")
def portfolio_json():
    u = _ctx_user()
    if u is None:
        return jsonify({"success": False, "message": "请先登录"}), 401
    return jsonify({"success": True, "data": trade.portfolio_summary(u["id"])})


# ====================================================================== 评论
@sandbox_bp.route("/api/comment", methods=["GET", "POST"])
def comments():
    u = _ctx_user()
    if u is None:
        return jsonify({"success": False, "message": "请先登录"}), 401
    if request.method == "GET":
        kind = request.args.get("kind")
        code = str(request.args.get("code", "")).zfill(6)
        s = get_session()
        try:
            q = s.query(Comment).filter(Comment.kind == kind, Comment.code == code,
                                        Comment.status == "visible")
            q = q.order_by(Comment.featured.desc(), Comment.created_at.desc())
            rows = q.all()
            data = []
            for c in rows:
                data.append({"id": c.id, "user_id": c.user_id, "username": c.username,
                             "role": c.role, "role_label": ROLE_LABELS.get(c.role, c.role),
                             "content": c.content, "featured": c.featured,
                             "created_at": c.created_at.strftime("%Y-%m-%d %H:%M")})
            return jsonify({"success": True, "data": data})
        finally:
            s.close()

    # POST
    data = request.get_json() or {}
    content = (data.get("content") or "").strip()
    kind = data.get("kind")
    code = str(data.get("code", "")).zfill(6)
    if not content:
        return jsonify({"success": False, "message": "评论内容不能为空"})
    if len(content) > 500:
        return jsonify({"success": False, "message": "评论不能超过 500 字"})

    limit = COMMENT_DAILY_LIMIT.get(u["role"])
    if limit is not None:
        used = today_comment_count(u["id"])
        if used >= limit:
            return jsonify({"success": False, "message": f"今日评论已达上限({limit}条)"})

    s = get_session()
    try:
        c = Comment(kind=kind, code=code, user_id=u["id"], username=u["username"],
                    role=u["role"], content=content, status="visible", featured=False)
        s.add(c)
        s.commit()
        return jsonify({"success": True, "message": "评论成功"})
    except Exception as e:
        s.rollback()
        return jsonify({"success": False, "message": f"评论失败：{e}"})
    finally:
        s.close()


@sandbox_bp.route("/api/comment/<int:cid>/moderate", methods=["POST"])
@permission_required("can_moderate")
def moderate_comment(cid):
    data = request.get_json() or {}
    action = data.get("action")  # hide|delete|restore|feature
    reason = data.get("reason", "")
    s = get_session()
    try:
        c = s.query(Comment).get(cid)
        if not c:
            return jsonify({"success": False, "message": "评论不存在"}), 404
        status_map = {"hide": "hidden", "delete": "deleted", "restore": "visible"}
        if action in status_map:
            c.status = status_map[action]
        elif action == "feature":
            c.featured = not c.featured
        else:
            return jsonify({"success": False, "message": "未知操作"}), 400
        u = _ctx_user()
        s.add(CommentModerationLog(comment_id=cid, moderator_id=u["id"], action=action, reason=reason))
        s.commit()
        return jsonify({"success": True, "message": "操作成功"})
    except Exception as e:
        s.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        s.close()


# ====================================================================== 管理后台
@sandbox_bp.route("/admin")
@_no_cache
@permission_required("can_view_all_students", json_response=False)
def admin_page():
    u = _ctx_user()
    if u is None:
        return _JINGEPI_LOGIN_REDIRECT()
    return render_template("sandbox/admin.html", user=u, roles=ASSIGNABLE_ROLES,
                          role_labels=ROLE_LABELS)


@sandbox_bp.route("/api/admin/users")
@permission_required("can_manage_users")
def admin_users():
    s = get_session()
    try:
        users = s.query(User).order_by(User.id.asc()).all()
        data = [{"id": us.id, "username": us.username, "role": us.role,
                 "role_label": ROLE_LABELS.get(us.role, us.role),
                 "cash": float(us.cash), "disabled": us.disabled} for us in users]
        return jsonify({"success": True, "data": data})
    finally:
        s.close()


@sandbox_bp.route("/api/admin/user/<uid>/role", methods=["POST"])
@permission_required("can_manage_users")
def admin_change_role(uid):
    data = request.get_json() or {}
    role = data.get("role")
    if role not in ASSIGNABLE_ROLES:
        return jsonify({"success": False, "message": "无效角色"})
    s = get_session()
    try:
        us = s.query(User).get(uid)
        if not us:
            return jsonify({"success": False, "message": "用户不存在"}), 404
        us.role = role
        s.commit()
        return jsonify({"success": True, "message": "角色已更新"})
    except Exception as e:
        s.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        s.close()


@sandbox_bp.route("/api/admin/user/<uid>/toggle", methods=["POST"])
@permission_required("can_manage_users")
def admin_toggle_user(uid):
    s = get_session()
    try:
        us = s.query(User).get(uid)
        if not us:
            return jsonify({"success": False, "message": "用户不存在"}), 404
        us.disabled = not us.disabled
        s.commit()
        return jsonify({"success": True, "message": "已禁用" if us.disabled else "已启用",
                        "disabled": us.disabled})
    except Exception as e:
        s.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        s.close()


@sandbox_bp.route("/api/admin/watchlist")
@permission_required("can_curate")
def admin_watchlist():
    s = get_session()
    try:
        rows = s.query(Watchlist).order_by(Watchlist.kind.asc(), Watchlist.id.asc()).all()
        data = [{"id": r.id, "kind": r.kind, "code": r.code, "name": r.name} for r in rows]
        return jsonify({"success": True, "data": data})
    finally:
        s.close()


@sandbox_bp.route("/api/admin/watchlist", methods=["POST"])
@permission_required("can_curate")
def admin_add_watch():
    data = request.get_json() or {}
    kind = data.get("kind")
    code = str(data.get("code", "")).zfill(6)
    name = data.get("name", "")
    if kind not in ("stock", "fund") or not code:
        return jsonify({"success": False, "message": "参数无效"})
    s = get_session()
    try:
        if s.query(Watchlist).filter(Watchlist.kind == kind, Watchlist.code == code).first():
            return jsonify({"success": False, "message": "该标的已在自选"})
        u = _ctx_user()
        s.add(Watchlist(kind=kind, code=code, name=name, added_by=u["username"]))
        # 立即触发一次该标的历史抓取（股票/基金表会在下次刷新写入）
        s.commit()
        return jsonify({"success": True, "message": "已添加"})
    except Exception as e:
        s.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        s.close()


@sandbox_bp.route("/api/admin/watchlist/<int:wid>", methods=["POST", "DELETE"])
@permission_required("can_curate")
def admin_del_watch(wid):
    s = get_session()
    try:
        w = s.query(Watchlist).get(wid)
        if not w:
            return jsonify({"success": False, "message": "不存在"}), 404
        s.delete(w)
        s.commit()
        return jsonify({"success": True, "message": "已移除"})
    except Exception as e:
        s.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        s.close()


@sandbox_bp.route("/api/admin/comments")
@permission_required("can_moderate")
def admin_comments():
    s = get_session()
    try:
        rows = s.query(Comment).order_by(Comment.created_at.desc()).limit(200).all()
        data = [{"id": c.id, "kind": c.kind, "code": c.code, "username": c.username,
                 "role": ROLE_LABELS.get(c.role, c.role), "content": c.content,
                 "status": c.status, "featured": c.featured,
                 "created_at": c.created_at.strftime("%Y-%m-%d %H:%M")} for c in rows]
        return jsonify({"success": True, "data": data})
    finally:
        s.close()


@sandbox_bp.route("/api/admin/reset", methods=["POST"])
@permission_required("can_reset", json_response=False)
def admin_reset():
    data = request.get_json() or {}
    scope = data.get("scope")  # user | cache | all
    target_uid = data.get("user_id")
    from .db import INITIAL_CAPITAL
    s = get_session()
    try:
        if scope == "user" and target_uid:
            us = s.query(User).get(target_uid)
            if us:
                us.cash = INITIAL_CAPITAL
                s.query(Holding).filter(Holding.user_id == target_uid).delete()
                s.query(Order).filter(Order.user_id == target_uid).delete()
        elif scope == "cache":
            s.query(Stock).delete()
            s.query(Fund).delete()
            s.query(PriceHistory).delete()
            s.query(Watchlist).delete()
        elif scope == "all":
            s.query(Holding).delete()
            s.query(Order).delete()
            s.query(Comment).delete()
            s.query(CommentModerationLog).delete()
            s.query(Watchlist).delete()
            s.query(Stock).delete()
            s.query(Fund).delete()
            s.query(PriceHistory).delete()
            s.query(User).delete()
        s.commit()
    except Exception as e:
        s.rollback()
        s.close()
        return jsonify({"success": False, "message": str(e)})
    s.close()
    # 在 session 关闭后再 reseed，避免 SQLite 写锁冲突
    if scope in ("cache", "all"):
        from . import seed
        seed.ensure_seed(force=True)
    return jsonify({"success": True, "message": "重置完成"})
