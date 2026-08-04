"""投资性格 MBTI 分析。

测试阶段默认走本地 Ollama；云端 API 可通过环境变量覆盖。
输入：trade_history.csv 中最近最多 10000 条交易记录。
输出类型仅限：苟住型 / 稳字型 / 端水型 / 操作型 / 梭哈型
结果由调用方写入 users/<id>/MBTI_log.csv。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

import mbti_log
import trade_history


class AlreadyAnalyzedError(ValueError):
    """交易数据与上次成功分析相同，无需再次调用 AI。"""

    code = "already_analyzed"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message
            or "你已经生成过MBTI报告。当前交易数据没有变化，无需重复分析；更新交易记录后可再试。"
        )


class AnalyzeInProgressError(ValueError):
    """同一用户已有分析任务在进行中。"""

    code = "analyze_in_progress"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or "正在分析中，请稍候")


# 测试默认：本地 Ollama；生产可设 MBTI_AI_PROVIDER=cloud 并配置 URL/KEY
AI_PROVIDER = (os.environ.get("MBTI_AI_PROVIDER") or "ollama").strip().lower()
AI_API_URL = os.environ.get(
    "MBTI_AI_API_URL",
    "http://127.0.0.1:11434/api/chat" if AI_PROVIDER == "ollama" else "",
).strip()
AI_API_KEY = os.environ.get("MBTI_AI_API_KEY", "").strip()
AI_MODEL = os.environ.get("MBTI_AI_MODEL", "gpt-oss:20b").strip()
AI_TIMEOUT = int(os.environ.get("MBTI_AI_TIMEOUT", "300"))

MBTI_TYPES = mbti_log.MBTI_TYPES

SYSTEM_PROMPT = """你是投资性格分析助手。请根据用户的证券成交记录（CSV），判断其投资性格类型。

必须且只能从以下 5 类中选出最匹配的 1 类（原样输出类型名，不要自创）：

1. 苟住型：极少交易、长期持有、极度厌恶风险，宁可错过也不轻易出手。
2. 稳字型：节奏偏慢、仓位克制、偏爱稳健标的，买卖决策谨慎。
3. 端水型：攻守相对平衡，既会把握机会也会控制回撤，风格中庸。
4. 操作型：交易较频繁，善于波段与调仓，对市场波动反应积极。
5. 梭哈型：偏好重仓、短线博弈或高波动标的，风险偏好很高。

请结合买卖频率、持仓时长线索、操作集中度、金额波动等综合判断。
只输出一个 JSON 对象，不要输出其它说明文字，字段如下：
{
  "mbti": "五类之一",
  "title": "简短称号（可与类型相同或更口语）",
  "summary": "2～4 句中文总结",
  "details": "分点说明判断依据（纯文本）"
}
"""

USER_PROMPT_TEMPLATE = """以下是该用户 trade_history.csv 中最近 {record_count} 条成交记录（全库共 {total_in_csv} 条，上限 {limit}）。
字段：{schema}

请据此给出投资性格类型（仅限：{types}）。

--- CSV 开始 ---
{csv}
--- CSV 结束 ---
"""


def ai_is_ready() -> bool:
    if not AI_API_URL:
        return False
    if AI_PROVIDER == "ollama":
        return True
    return bool(AI_API_KEY)


def _build_user_prompt(
    csv_text: str,
    *,
    used: int,
    total: int,
    limit: int,
) -> str:
    return USER_PROMPT_TEMPLATE.format(
        record_count=used,
        total_in_csv=total,
        limit=limit,
        schema="、".join(trade_history.CSV_HEADERS),
        types=" / ".join(MBTI_TYPES),
        csv=csv_text,
    )


def _normalize_ai_type(raw: str) -> str:
    text = (raw or "").strip()
    for name in MBTI_TYPES:
        if name in text:
            return name
    raise ValueError(f"AI 返回了无法识别的类型：{raw!r}")


def _extract_json_object(content: str) -> dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise ValueError("AI 返回为空")

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("AI 返回格式无效（未找到 JSON）")


def _http_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=AI_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise ValueError(f"无法连接 AI 服务（{url}）：{e.reason}") from e
    except TimeoutError as e:
        raise ValueError(f"AI 响应超时（>{AI_TIMEOUT}s）") from e


def _content_from_response(data: dict[str, Any]) -> str:
    if data.get("mbti") or data.get("类型"):
        return json.dumps(data, ensure_ascii=False)

    # Ollama /api/chat
    msg = data.get("message")
    if isinstance(msg, dict) and msg.get("content"):
        return str(msg["content"])

    # OpenAI-compatible
    choices = data.get("choices") or []
    if choices:
        c0 = choices[0] or {}
        m = c0.get("message") or {}
        if m.get("content"):
            return str(m["content"])
        if c0.get("text"):
            return str(c0["text"])

    # Ollama /api/generate
    if data.get("response"):
        return str(data["response"])

    if data.get("content"):
        return str(data["content"])
    if data.get("text"):
        return str(data["text"])
    return ""


def _call_ollama(user_prompt: str) -> dict[str, Any]:
    """调用本地 Ollama Chat API。"""
    url = AI_API_URL or "http://127.0.0.1:11434/api/chat"
    # 兼容用户把 URL 配成根地址或 /v1
    if url.rstrip("/").endswith(":11434"):
        url = url.rstrip("/") + "/api/chat"
    elif url.rstrip("/").endswith("/v1"):
        url = url.rstrip("/") + "/chat/completions"

    if url.rstrip("/").endswith("/chat/completions"):
        payload = {
            "model": AI_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "stream": False,
        }
        headers = {}
        if AI_API_KEY:
            headers["Authorization"] = f"Bearer {AI_API_KEY}"
        data = _http_json(url, payload, headers=headers)
    else:
        payload = {
            "model": AI_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }
        data = _http_json(url, payload)

    content = _content_from_response(data)
    return _extract_json_object(content)


def _call_cloud(user_prompt: str) -> dict[str, Any]:
    """调用云端 OpenAI 兼容接口。"""
    if not AI_API_URL:
        raise ValueError("未配置 MBTI_AI_API_URL")
    if not AI_API_KEY:
        raise ValueError("未配置 MBTI_AI_API_KEY")

    payload = {
        "model": AI_MODEL or "default",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
    }
    data = _http_json(
        AI_API_URL,
        payload,
        headers={"Authorization": f"Bearer {AI_API_KEY}"},
    )
    content = _content_from_response(data)
    return _extract_json_object(content)


def _call_ai_api(user_prompt: str) -> dict[str, Any]:
    if AI_PROVIDER == "ollama":
        return _call_ollama(user_prompt)
    return _call_cloud(user_prompt)


def fingerprint_ai_input(records: list[dict[str, str]]) -> str:
    """对送入 AI 的 CSV 文本做稳定 SHA256 指纹。"""
    csv_text = trade_history.records_to_csv_text(records)
    return hashlib.sha256(csv_text.encode("utf-8")).hexdigest()


def analyze_mbti_from_history(
    records: list[dict[str, str]],
    *,
    total_in_csv: int | None = None,
    limit: int = trade_history.MBTI_RECORD_LIMIT,
) -> dict[str, Any]:
    """基于交易历史记录分析投资性格 MBTI。"""
    if not records:
        raise ValueError("暂无交易历史记录，请先在「我的交易数据」中整理或添加")

    csv_text = trade_history.records_to_csv_text(records)
    used = len(records)
    total = total_in_csv if total_in_csv is not None else used
    user_prompt = _build_user_prompt(csv_text, used=used, total=total, limit=limit)

    if not ai_is_ready():
        raise ValueError("AI 接口尚未配置，暂不生成类型结果（不会写入 MBTI_log）")

    try:
        raw = _call_ai_api(user_prompt)
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"AI 分析失败：{e}") from e

    mbti = _normalize_ai_type(str(raw.get("mbti") or raw.get("类型") or ""))
    title = str(raw.get("title") or mbti).strip() or mbti
    summary = str(raw.get("summary") or "").strip()
    details = str(raw.get("details") or "").strip()

    date_from = records[-1].get("成交日期", "")
    date_to = records[0].get("成交日期", "")
    range_hint = ""
    if date_from and date_to:
        range_hint = f"覆盖成交日期 {date_from} ~ {date_to}。"

    return {
        "mbti": mbti,
        "title": title,
        "summary": summary if summary else f"判定为「{mbti}」。{range_hint}",
        "details": details,
        "source_file": f"trade_history.csv（最近 {used} 条）",
        "record_count": used,
        "total_in_csv": total,
        "csv_chars": len(csv_text),
        "ai_ready": True,
        "ai_used": True,
        "ai_provider": AI_PROVIDER,
        "ai_model": AI_MODEL,
        "types": list(MBTI_TYPES),
    }


def analyze_mbti_for_user(user_id: str, limit: int = trade_history.MBTI_RECORD_LIMIT) -> dict[str, Any]:
    """读取用户交易历史并分析。

    若当前 AI 输入指纹与上次成功分析相同，抛出 AlreadyAnalyzedError（不调用 AI）。
    若已有进行中的分析，抛出 AnalyzeInProgressError（不调用 AI）。
    成功时在结果中附带 input_hash，由调用方在写入日志后落盘。
    """
    trade_history.ensure_history_csv(user_id)
    all_rows = trade_history.load_all_records(user_id)
    recent = trade_history.recent_records_for_ai(user_id, limit=limit)
    if not recent:
        raise ValueError("暂无交易历史记录，请先在「我的交易数据」中整理或添加")

    input_hash = fingerprint_ai_input(recent)
    prev_hash = mbti_log.load_input_hash(user_id)
    if prev_hash and prev_hash == input_hash:
        raise AlreadyAnalyzedError()

    lock_token = mbti_log.try_acquire_analyze_lock(
        user_id,
        ttl_sec=AI_TIMEOUT + 120,
    )
    if not lock_token:
        raise AnalyzeInProgressError()

    try:
        result = analyze_mbti_from_history(recent, total_in_csv=len(all_rows), limit=limit)
        result["input_hash"] = input_hash
        return result
    finally:
        mbti_log.release_analyze_lock(user_id, lock_token)


# 兼容旧文件调用（已弃用：请使用 analyze_mbti_for_user）
def analyze_mbti_files(files: list[tuple[str, bytes]]) -> dict[str, Any]:
    raise ValueError("MBTI 分析已改为使用 trade_history.csv，请使用最新接口")


def analyze_mbti_file(filename: str, file_bytes: bytes) -> dict[str, Any]:
    return analyze_mbti_files([(filename, file_bytes)])
