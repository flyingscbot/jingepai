"""交易历史 CSV 管理 + AI 自动整理预留。

每位用户一份：users/<id>/trade_history.csv
字段：成交日期 时间 证券代码 证券名称 操作 成交数量 成交均价 成交金额
"""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime
from typing import Any

import user_db

# TODO: 填入真实 AI 服务配置
AI_API_URL = os.environ.get("TRADE_AI_API_URL", "")
AI_API_KEY = os.environ.get("TRADE_AI_API_KEY", "")

HISTORY_FILENAME = "trade_history.csv"
CSV_HEADERS = [
    "成交日期",
    "时间",
    "证券代码",
    "证券名称",
    "操作",
    "成交数量",
    "成交均价",
    "成交金额",
]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
_TIME_HM_RE = re.compile(r"^\d{2}:\d{2}$")


def history_path(user_id: str) -> str:
    user_db.ensure_profile_dir(user_id)
    return os.path.join(user_db.USERS_DIR, user_id, HISTORY_FILENAME)


def ensure_history_csv(user_id: str) -> str:
    """确保交易历史 CSV 存在（仅表头）。"""
    path = history_path(user_id)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
    return path


def normalize_time(value: str) -> str:
    """统一为 HH:MM:SS；空则默认 00:00:00。"""
    time_v = (value or "").strip()
    if not time_v:
        return "00:00:00"
    if "." in time_v:
        time_v = time_v.split(".", 1)[0]
    if _TIME_HM_RE.match(time_v):
        return time_v + ":00"
    if _TIME_RE.match(time_v):
        return time_v
    raise ValueError("时间格式应为 HH:MM:SS")


def normalize_record(raw: dict[str, Any]) -> dict[str, str]:
    """规范化一条交易记录。"""
    date = str(raw.get("成交日期") or raw.get("date") or "").strip()
    time_v = normalize_time(str(raw.get("时间") or raw.get("time") or "").strip())
    code = str(raw.get("证券代码") or raw.get("code") or "").strip()
    name = str(raw.get("证券名称") or raw.get("name") or "").strip()
    action = str(raw.get("操作") or raw.get("action") or "").strip()
    qty = str(raw.get("成交数量") or raw.get("quantity") or "").strip()
    price = str(raw.get("成交均价") or raw.get("price") or "").strip()
    amount = str(raw.get("成交金额") or raw.get("amount") or "").strip()

    rec = {
        "成交日期": date,
        "时间": time_v,
        "证券代码": code,
        "证券名称": name,
        "操作": action,
        "成交数量": qty,
        "成交均价": price,
        "成交金额": amount,
    }
    validate_record(rec)
    return rec


def validate_record(rec: dict[str, str]) -> None:
    if not _DATE_RE.match(rec["成交日期"]):
        raise ValueError("成交日期格式应为 YYYY-MM-DD")
    if not _TIME_RE.match(rec["时间"]):
        raise ValueError("时间格式应为 HH:MM:SS")
    if not rec["证券代码"]:
        raise ValueError("证券代码不能为空")
    if not rec["证券名称"]:
        raise ValueError("证券名称不能为空")
    if not rec["操作"]:
        raise ValueError("操作不能为空")
    for key in ("成交数量", "成交均价", "成交金额"):
        if rec[key] == "":
            raise ValueError(f"{key}不能为空")
        try:
            float(rec[key])
        except ValueError as e:
            raise ValueError(f"{key}必须是数字") from e


def record_key(rec: dict[str, str]) -> str:
    """去重键：日期+时间+代码+操作+数量+均价+金额。"""
    return "|".join(
        [
            rec.get("成交日期", ""),
            rec.get("时间", ""),
            rec.get("证券代码", ""),
            rec.get("操作", ""),
            rec.get("成交数量", ""),
            rec.get("成交均价", ""),
            rec.get("成交金额", ""),
        ]
    )


def load_all_records(user_id: str) -> list[dict[str, str]]:
    path = ensure_history_csv(user_id)
    rows: list[dict[str, str]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row:
                continue
            rec = {h: (row.get(h) or "").strip() for h in CSV_HEADERS}
            if not any(rec.values()):
                continue
            # 旧数据若只有 HH:MM，读出时补秒
            try:
                rec["时间"] = normalize_time(rec.get("时间", ""))
            except ValueError:
                pass
            rows.append(rec)
    return rows


def save_all_records(user_id: str, records: list[dict[str, str]]) -> None:
    path = ensure_history_csv(user_id)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writeheader()
        for rec in records:
            writer.writerow({h: rec.get(h, "") for h in CSV_HEADERS})


def append_unique_records(user_id: str, new_records: list[dict[str, Any]]) -> dict[str, int]:
    """追加记录，跳过重复项。返回 added / skipped / total。"""
    existing = load_all_records(user_id)
    seen = {record_key(r) for r in existing}
    added = 0
    skipped = 0
    for raw in new_records:
        try:
            rec = normalize_record(raw)
        except ValueError:
            skipped += 1
            continue
        key = record_key(rec)
        if key in seen:
            skipped += 1
            continue
        existing.append(rec)
        seen.add(key)
        added += 1
    # 按日期时间排序
    existing.sort(key=lambda r: (r["成交日期"], r["时间"], r["证券代码"]))
    save_all_records(user_id, existing)
    return {"added": added, "skipped": skipped, "total": len(existing)}


def list_records_by_date(user_id: str, date: str) -> list[dict[str, str]]:
    if not _DATE_RE.match(date):
        raise ValueError("日期格式应为 YYYY-MM-DD")
    rows = [r for r in load_all_records(user_id) if r["成交日期"] == date]
    rows.sort(key=lambda r: (r["时间"], r["证券代码"]))
    # 附加稳定行号（在全表中的位置），便于删除
    all_rows = load_all_records(user_id)
    keyed = {}
    for i, r in enumerate(all_rows):
        keyed.setdefault(record_key(r), []).append(i)

    result = []
    used: dict[str, int] = {}
    for r in rows:
        k = record_key(r)
        idx_in_bucket = used.get(k, 0)
        used[k] = idx_in_bucket + 1
        indices = keyed.get(k, [])
        row_index = indices[idx_in_bucket] if idx_in_bucket < len(indices) else -1
        item = dict(r)
        item["row_index"] = row_index
        result.append(item)
    return result


def list_dates_in_month(user_id: str, year: int, month: int) -> list[str]:
    prefix = f"{year:04d}-{month:02d}-"
    dates = sorted(
        {
            r["成交日期"]
            for r in load_all_records(user_id)
            if r["成交日期"].startswith(prefix)
        }
    )
    return dates


def latest_trade_date(user_id: str) -> str | None:
    """返回最近一笔记录的成交日期；无记录则 None。"""
    dates = sorted({r["成交日期"] for r in load_all_records(user_id) if r.get("成交日期")})
    return dates[-1] if dates else None


def list_all_records_indexed(user_id: str) -> list[dict[str, Any]]:
    """全部记录（含 row_index），按日期时间倒序便于浏览。"""
    rows = load_all_records(user_id)
    indexed: list[dict[str, Any]] = []
    for i, r in enumerate(rows):
        item = dict(r)
        item["row_index"] = i
        indexed.append(item)
    indexed.sort(key=lambda r: (r["成交日期"], r["时间"], r["证券代码"]), reverse=True)
    return indexed


def update_record_by_index(user_id: str, row_index: int, raw: dict[str, Any]) -> dict[str, str]:
    """按全表行号更新一条记录（去重校验）。"""
    rows = load_all_records(user_id)
    if row_index < 0 or row_index >= len(rows):
        raise ValueError("记录不存在")
    rec = normalize_record(raw)
    key = record_key(rec)
    for i, r in enumerate(rows):
        if i != row_index and record_key(r) == key:
            raise ValueError("修改后的记录与已有记录重复")
    rows[row_index] = rec
    rows.sort(key=lambda r: (r["成交日期"], r["时间"], r["证券代码"]))
    save_all_records(user_id, rows)
    return rec


def add_record(user_id: str, raw: dict[str, Any]) -> dict[str, str]:
    rec = normalize_record(raw)
    stats = append_unique_records(user_id, [rec])
    if stats["added"] == 0:
        raise ValueError("该记录已存在，未重复添加")
    return rec


def delete_record_by_index(user_id: str, row_index: int) -> None:
    rows = load_all_records(user_id)
    if row_index < 0 or row_index >= len(rows):
        raise ValueError("记录不存在")
    rows.pop(row_index)
    save_all_records(user_id, rows)


def extract_records_from_files(files: list[tuple[str, bytes]]) -> list[dict[str, Any]]:
    """
    调用 AI 从上传文件中整理交易记录。

    预留位置：在此接入真实大模型 API。
    当前返回占位示例记录，便于前端联调。
    """
    if not files:
        raise ValueError("没有可整理的交易文件，请先上传")

    # --- AI API 接入预留 ---
    # import json, base64, urllib.request
    # payload = {
    #     "files": [
    #         {"filename": name, "content_b64": base64.b64encode(raw).decode("ascii")}
    #         for name, raw in files
    #     ],
    #     "schema": CSV_HEADERS,
    # }
    # req = urllib.request.Request(
    #     AI_API_URL,
    #     data=json.dumps(payload).encode("utf-8"),
    #     headers={
    #         "Content-Type": "application/json",
    #         "Authorization": f"Bearer {AI_API_KEY}",
    #     },
    #     method="POST",
    # )
    # with urllib.request.urlopen(req, timeout=120) as resp:
    #     data = json.loads(resp.read().decode("utf-8"))
    # return data["records"]  # list[dict]
    # --- 预留结束 ---

    today = datetime.now().strftime("%Y-%m-%d")
    # 占位：按文件名生成示意记录，真实环境由 AI 解析文件内容
    demo: list[dict[str, Any]] = []
    for i, (name, raw) in enumerate(files[:3]):
        demo.append(
            {
                "成交日期": today,
                "时间": f"{10 + i:02d}:30:00",
                "证券代码": f"60{i:04d}",
                "证券名称": f"示例证券{i + 1}",
                "操作": "买入" if i % 2 == 0 else "卖出",
                "成交数量": str(100 * (i + 1)),
                "成交均价": f"{10 + i}.50",
                "成交金额": f"{(100 * (i + 1)) * (10 + i) + 0.0:.2f}",
                "_source": name,
                "_bytes": len(raw),
            }
        )
    return demo


def organize_from_user_files(user_id: str) -> dict[str, Any]:
    """读取用户 trade_file 下全部文件，AI 整理后追加到历史 CSV。"""
    file_list = user_db.list_trade_files(user_id)
    if not file_list:
        raise ValueError("没有可整理的交易文件，请先上传")
    files: list[tuple[str, bytes]] = []
    for item in file_list:
        filename, raw = user_db.read_trade_file(user_id, item["name"])
        files.append((filename, raw))
    records = extract_records_from_files(files)
    stats = append_unique_records(user_id, records)
    return {
        "added": stats["added"],
        "skipped": stats["skipped"],
        "total": stats["total"],
        "source_files": len(files),
        "ai_ready": bool(AI_API_URL and AI_API_KEY),
    }
