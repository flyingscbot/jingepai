"""用户投资性格 MBTI 历史日志。

每位用户一份：users/<id>/MBTI_log.csv
字段：时间 类型
"""

from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Any

import user_db

LOG_FILENAME = "MBTI_log.csv"
CSV_HEADERS = ["时间", "类型"]

# 从保守到激进
MBTI_TYPES = ["苟住型", "稳字型", "端水型", "操作型", "梭哈型"]
MBTI_LEVEL = {name: i for i, name in enumerate(MBTI_TYPES)}

# 各类型对应原创图标文件名（static/icons/）
MBTI_ICONS = {
    "苟住型": "mbti_gouzhu.svg",
    "稳字型": "mbti_wenzi.svg",
    "端水型": "mbti_duanshui.svg",
    "操作型": "mbti_caozuo.svg",
    "梭哈型": "mbti_suoha.svg",
}


def log_path(user_id: str) -> str:
    user_db.ensure_profile_dir(user_id)
    return os.path.join(user_db.USERS_DIR, user_id, LOG_FILENAME)


def ensure_log_csv(user_id: str) -> str:
    """确保 MBTI_log.csv 存在（仅表头）。"""
    path = log_path(user_id)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
    return path


def normalize_type(value: str) -> str:
    type_v = (value or "").strip()
    if type_v not in MBTI_LEVEL:
        raise ValueError(f"类型须为：{' / '.join(MBTI_TYPES)}")
    return type_v


def load_all_records(user_id: str) -> list[dict[str, str]]:
    """按文件顺序返回全部日志（旧 → 新）。"""
    path = ensure_log_csv(user_id)
    rows: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            time_v = (row.get("时间") or "").strip()
            type_v = (row.get("类型") or "").strip()
            if not time_v and not type_v:
                continue
            rows.append({"时间": time_v, "类型": type_v})
    return rows


def latest_record(user_id: str) -> dict[str, str] | None:
    rows = load_all_records(user_id)
    return rows[-1] if rows else None


def append_record(user_id: str, mbti_type: str, at: datetime | None = None) -> dict[str, str]:
    """追加一条分析结果。"""
    type_v = normalize_type(mbti_type)
    when = at or datetime.now()
    rec = {
        "时间": when.strftime("%Y-%m-%d %H:%M:%S"),
        "类型": type_v,
    }
    path = ensure_log_csv(user_id)
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerow(rec)
    return rec


def change_points(user_id: str) -> list[dict[str, Any]]:
    """
    返回类型发生变化的节点（含首次记录）。
    每项：时间、类型、level、changed(bool)、prev_type
    """
    rows = load_all_records(user_id)
    out: list[dict[str, Any]] = []
    prev: str | None = None
    for row in rows:
        cur = row.get("类型", "")
        level = MBTI_LEVEL.get(cur)
        changed = prev is not None and cur != prev
        out.append(
            {
                "时间": row.get("时间", ""),
                "类型": cur,
                "level": level if level is not None else -1,
                "changed": changed or prev is None,
                "prev_type": prev or "",
            }
        )
        prev = cur
    return out
