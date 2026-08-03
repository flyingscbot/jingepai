"""投资性格 MBTI 分析 — AI 接口预留。

后续在 analyze_mbti_files() 中接入真实大模型 API。
"""

from __future__ import annotations

import os
from typing import Any

# TODO: 填入真实 AI 服务配置
AI_API_URL = os.environ.get("MBTI_AI_API_URL", "")
AI_API_KEY = os.environ.get("MBTI_AI_API_KEY", "")


def analyze_mbti_files(files: list[tuple[str, bytes]]) -> dict[str, Any]:
    """
    分析用户选择的一个或多个文件，返回 MBTI / 投资性格结果。

    files: [(filename, file_bytes), ...]
    预留位置：在此调用 AI API（如 OpenAI / 国产大模型）。
    """
    if not files:
        raise ValueError("请先选择文件")

    # --- AI API 接入预留 ---
    # import urllib.request, json, base64
    # payload = {
    #     "files": [
    #         {"filename": name, "content_b64": base64.b64encode(raw).decode("ascii")}
    #         for name, raw in files
    #     ]
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
    # return { ... }
    # --- 预留结束 ---

    names = [name for name, _ in files]
    total_size = sum(len(raw) for _, raw in files)
    joined = "、".join(names[:5])
    if len(names) > 5:
        joined += f" 等 {len(names)} 个文件"

    return {
        "mbti": "未知",
        "title": "未知",
        "summary": (
            f"已选择 {len(names)} 个文件（共 {total_size} 字节）：{joined}。"
            "当前为预留分析结果，接入 AI API 后将基于所选文件内容生成真实投资性格报告。"
        ),
        "details": (
           
        ),
        "source_file": "、".join(names),
        "ai_ready": bool(AI_API_URL and AI_API_KEY),
    }


# 兼容旧单文件调用
def analyze_mbti_file(filename: str, file_bytes: bytes) -> dict[str, Any]:
    return analyze_mbti_files([(filename, file_bytes)])
