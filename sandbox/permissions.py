"""角色权限矩阵与装饰器。

5 类角色与 JINGEPI users.db 一一对应：
trial（免费用户）/ user（用户）/ specialist（教师·专家）/ admin（管理员）/ super_admin（超级管理员）
所有角色同样 10000 元初始资金；权限为「功能分层」。
"""
from functools import wraps
from flask import session, jsonify, redirect, url_for

from .db import get_session, sync_user_from_session

ROLE_LABELS = {
    "trial": "免费用户",
    "user": "用户",
    "specialist": "教师（专家）",
    "admin": "管理员",
    "super_admin": "超级管理员",
}

# 每日评论上限：None = 无限
COMMENT_DAILY_LIMIT = {
    "trial": 10,
    "user": None,
    "specialist": None,
    "admin": None,
    "super_admin": None,
}

ROLE_PERMISSIONS = {
    "trial":       {"can_trade": True, "can_moderate": False, "can_view_all_students": False,
                    "can_feature": False, "can_curate": False, "can_manage_users": False, "can_reset": False},
    "user":        {"can_trade": True, "can_moderate": False, "can_view_all_students": False,
                    "can_feature": False, "can_curate": False, "can_manage_users": False, "can_reset": False},
    "specialist":  {"can_trade": True, "can_moderate": True, "can_view_all_students": True,
                    "can_feature": True, "can_curate": False, "can_manage_users": False, "can_reset": False},
    "admin":       {"can_trade": True, "can_moderate": True, "can_view_all_students": True,
                    "can_feature": True, "can_curate": True, "can_manage_users": True, "can_reset": False},
    "super_admin": {"can_trade": True, "can_moderate": True, "can_view_all_students": True,
                    "can_feature": True, "can_curate": True, "can_manage_users": True, "can_reset": True},
}

# 供前端下拉用的角色列表（管理员可分配）
ASSIGNABLE_ROLES = ["trial", "user", "specialist", "admin", "super_admin"]


def get_current_user():
    """返回当前登录的沙盘 User（含 role），未登录返回 None。"""
    s = get_session()
    try:
        user, _ = sync_user_from_session(s, session)
        return user
    finally:
        s.close()


def has_perm(role, perm):
    return ROLE_PERMISSIONS.get(role, {}).get(perm, False)


def permission_required(perm, json_response=True):
    """装饰器：校验当前用户具备指定权限。"""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            user = get_current_user()
            if user is None:
                if json_response:
                    return jsonify({"success": False, "message": "请先登录"}), 401
                return redirect(url_for("home.index", modal="login"))
            if user.disabled:
                if json_response:
                    return jsonify({"success": False, "message": "账号已被禁用"}), 403
                return redirect(url_for("home.index", modal="login"))
            if not has_perm(user.role, perm):
                if json_response:
                    return jsonify({"success": False, "message": "权限不足"}), 403
                return ("权限不足", 403)
            return f(*args, **kwargs)
        return wrapped
    return decorator


def today_comment_count(user_id):
    """今日该用户已发评论数（含 visible/hidden，不含 deleted）。"""
    from datetime import datetime
    from .db import Comment
    s = get_session()
    try:
        now = datetime.now()
        start = datetime(now.year, now.month, now.day)
        return s.query(Comment).filter(
            Comment.user_id == user_id,
            Comment.created_at >= start,
            Comment.status != "deleted",
        ).count()
    finally:
        s.close()
