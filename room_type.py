"""金融 MBTI V2 聊天室分层：计算 users.suggested_room_type。

主群按 C1–C5 同型分（见《金融MBTI_算法V2_聊天室分层逻辑》）。
管理员（admin / super_admin）与专家（specialist）固定为 all。
普通用户：算法主型映射 C1–C5；置信度 ≥0.65 且连续两周同型才更新（滞回）。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import mbti_algo
import mbti_log
import user_db

ROOM_TYPE_ALL = "all"
ROOM_TYPES = frozenset({"C1", "C2", "C3", "C4", "C5"})
CONFIDENCE_THRESHOLD = 0.65
STABILITY_DAYS = 14


def room_type_for_role(role: str | None) -> str | None:
    """管理员与专家进全部主群；普通用户待 MBTI 分型后写入。"""
    if user_db.should_join_all_rooms(role):
        return ROOM_TYPE_ALL
    return None


def normalize_room_type(value: str | None) -> str | None:
    v = (value or "").strip()
    if not v:
        return None
    if v == ROOM_TYPE_ALL:
        return ROOM_TYPE_ALL
    v = v.upper()
    if v not in ROOM_TYPES:
        raise ValueError(f"suggested_room_type 无效，仅支持 all / C1–C5")
    return v


def mbti_type_to_room_code(mbti_type: str | None) -> str | None:
    t = (mbti_type or "").strip()
    if not t:
        return None
    return mbti_algo.CODE_BY_TYPE.get(t)


def _parse_log_time(value: str) -> datetime | None:
    s = (value or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def type_streak_from_log(
    rows: list[dict[str, str]],
    target_type: str,
) -> tuple[int, datetime | None]:
    """从日志末尾统计连续为 target_type 的条数及 streak 起始时间。"""
    target_type = (target_type or "").strip()
    if not target_type or not rows:
        return 0, None

    count = 0
    streak_start: datetime | None = None
    for row in reversed(rows):
        if (row.get("类型") or "").strip() != target_type:
            break
        count += 1
        streak_start = _parse_log_time(row.get("时间", "")) or streak_start

    return count, streak_start


def is_room_assignment_stable(
    user_id: str,
    target_code: str,
    *,
    rows: list[dict[str, str]] | None = None,
) -> bool:
    """连续两周同主型（或仅一条 MBTI 记录）视为可分配主群。"""
    target_code = normalize_room_type(target_code)
    if not target_code or target_code == ROOM_TYPE_ALL:
        return False

    target_type = mbti_algo.TYPE_BY_CODE.get(target_code)
    if not target_type:
        return False

    if rows is None:
        rows = mbti_log.load_all_records(user_id)

    streak_len, streak_start = type_streak_from_log(rows, target_type)
    if streak_len == 0:
        return False
    if streak_len == 1 and len(rows) == 1:
        return True
    if streak_start is None:
        return False
    return datetime.now() - streak_start >= timedelta(days=STABILITY_DAYS)


def compute_suggested_room_type(
    user_id: str,
    *,
    role: str | None = None,
    mbti_type: str | None = None,
    algo_code: str | None = None,
    confidence: float | None = None,
    current_room_type: str | None = None,
    rows: list[dict[str, str]] | None = None,
) -> str | None:
    """按分层逻辑计算建议主群类型（不写库）。"""
    if role is None:
        user = user_db.get_user_by_id(user_id)
        role = (user or {}).get("role")
    if current_room_type is None:
        user = user_db.get_user_by_id(user_id)
        current_room_type = (user or {}).get("suggested_room_type")

    admin_room = room_type_for_role(role)
    if admin_room:
        return admin_room

    code = normalize_room_type(algo_code) if algo_code else None
    if not code:
        code = mbti_type_to_room_code(mbti_type)
    if not code:
        return current_room_type

    conf = confidence
    if conf is not None and conf < CONFIDENCE_THRESHOLD:
        return current_room_type

    if rows is None:
        rows = mbti_log.load_all_records(user_id)

    if is_room_assignment_stable(user_id, code, rows=rows):
        return code
    return current_room_type


def apply_suggested_room_type(
    user_id: str,
    *,
    role: str | None = None,
    mbti_type: str | None = None,
    algo_code: str | None = None,
    confidence: float | None = None,
    rows: list[dict[str, str]] | None = None,
) -> str | None:
    """计算并写入 users.suggested_room_type。"""
    room = compute_suggested_room_type(
        user_id,
        role=role,
        mbti_type=mbti_type,
        algo_code=algo_code,
        confidence=confidence,
        rows=rows,
    )
    user_db.set_suggested_room_type(user_id, room)
    return room


def sync_suggested_room_type_for_user(user_id: str) -> str | None:
    """从 users 角色 + MBTI_log 回填单个用户（无置信度时仅看两周滞回）。"""
    user = user_db.get_user_by_id(user_id)
    if not user:
        return None

    admin_room = room_type_for_role(user.get("role"))
    if admin_room:
        user_db.set_suggested_room_type(user_id, admin_room)
        return admin_room

    rows = mbti_log.load_all_records(user_id)
    if not rows:
        return user.get("suggested_room_type")

    latest_type = (rows[-1].get("类型") or "").strip()
    code = mbti_type_to_room_code(latest_type)
    if not code:
        return user.get("suggested_room_type")

    room = compute_suggested_room_type(
        user_id,
        role=user.get("role"),
        mbti_type=latest_type,
        algo_code=code,
        confidence=None,
        current_room_type=user.get("suggested_room_type"),
        rows=rows,
    )
    user_db.set_suggested_room_type(user_id, room)
    return room


def sync_all_suggested_room_types() -> dict[str, Any]:
    """启动或维护时批量同步全部用户。"""
    users = user_db.list_users()
    updated = 0
    for u in users:
        uid = u.get("id")
        if not uid:
            continue
        before = u.get("suggested_room_type")
        after = sync_suggested_room_type_for_user(uid)
        if after != before:
            updated += 1
    return {"total": len(users), "updated": updated}
