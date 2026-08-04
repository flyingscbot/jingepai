"""用户投资性格 MBTI 历史日志。

每位用户一份：users/<id>/MBTI_log.csv
字段：时间 类型

成功分析后另存：users/<id>/MBTI_input_hash.txt（本次 AI 输入指纹）
分析进行中：users/<id>/MBTI_analyze.lock（防多端并发）
"""

from __future__ import annotations

import csv
import os
import time
import uuid
from datetime import datetime
from typing import Any

import user_db

LOG_FILENAME = "MBTI_log.csv"
INPUT_HASH_FILENAME = "MBTI_input_hash.txt"
ANALYZE_LOCK_FILENAME = "MBTI_analyze.lock"
# 与 MBTI_AI_TIMEOUT 对齐并留宽限，避免进程崩溃后锁永久卡住
ANALYZE_LOCK_TTL_SEC = int(os.environ.get("MBTI_AI_TIMEOUT", "300")) + 120
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


def input_hash_path(user_id: str) -> str:
    user_db.ensure_profile_dir(user_id)
    return os.path.join(user_db.USERS_DIR, user_id, INPUT_HASH_FILENAME)


def analyze_lock_path(user_id: str) -> str:
    user_db.ensure_profile_dir(user_id)
    return os.path.join(user_db.USERS_DIR, user_id, ANALYZE_LOCK_FILENAME)


def _read_analyze_lock(path: str) -> tuple[str, float] | None:
    """读取锁文件：token + 创建时间戳；损坏则 None。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = (f.read() or "").splitlines()
        if len(lines) < 2:
            return None
        token = (lines[0] or "").strip()
        started = float((lines[1] or "").strip())
        if not token:
            return None
        return token, started
    except (OSError, ValueError):
        return None


def try_acquire_analyze_lock(
    user_id: str,
    *,
    ttl_sec: int | None = None,
) -> str | None:
    """原子创建分析锁。成功返回 token；已有有效锁则返回 None。

    过期锁会被清理后重试一次，避免崩溃后永久占用。
    """
    path = analyze_lock_path(user_id)
    ttl = ANALYZE_LOCK_TTL_SEC if ttl_sec is None else max(1, int(ttl_sec))
    token = uuid.uuid4().hex
    payload = f"{token}\n{time.time():.6f}\n"

    def _create() -> bool:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        try:
            fd = os.open(path, flags)
        except FileExistsError:
            return False
        except OSError:
            return False
        try:
            os.write(fd, payload.encode("utf-8"))
            os.close(fd)
            return True
        except OSError:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.unlink(path)
            except OSError:
                pass
            return False

    if _create():
        return token

    existing = _read_analyze_lock(path)
    now = time.time()
    stale = False
    if existing is None:
        # 空/损坏：按 mtime 判断，读不到则视为过期
        try:
            age = now - os.path.getmtime(path)
            stale = age >= ttl
        except OSError:
            stale = True
    else:
        stale = (now - existing[1]) >= ttl

    if not stale:
        return None

    try:
        os.unlink(path)
    except OSError:
        return None

    return token if _create() else None


def release_analyze_lock(user_id: str, token: str) -> None:
    """仅当 token 匹配时删除锁，避免误清其它请求刚拿到的锁。"""
    token = (token or "").strip()
    if not token:
        return
    path = analyze_lock_path(user_id)
    existing = _read_analyze_lock(path)
    if existing is None or existing[0] != token:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def load_input_hash(user_id: str) -> str | None:
    """读取上次成功分析时保存的输入指纹；无则 None。"""
    path = input_hash_path(user_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = (f.read() or "").strip()
        return value or None
    except OSError:
        return None


def save_input_hash(user_id: str, digest: str) -> None:
    """写入成功分析所用交易数据的指纹。"""
    digest = (digest or "").strip()
    if not digest:
        return
    path = input_hash_path(user_id)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(digest)


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
