"""Matrix 主题色管理：JSON 持久化 + 生成 jingepi-theme-vars.css（管理后台用）。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

ROOT = os.path.dirname(os.path.abspath(__file__))
THEME_DIR = os.path.join(ROOT, "matrix", "theme")
COLORS_JSON = os.path.join(THEME_DIR, "jingepi-theme-colors.json")
VARS_CSS = os.path.join(THEME_DIR, "jingepi-theme-vars.css")

HEX_RE = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")

GROUP_LABELS = {
    "surface": "页面/表面",
    "text": "文字",
    "border": "边框",
    "button": "主按钮",
    "accent": "强调色/其它",
}

# key → CSS 变量名（不含 --）、中文标签、分组、默认值
COLOR_DEFS: list[dict[str, str]] = [
    # 页面/表面
    {"key": "bg", "css": "--jingepi-bg", "label": "页面底色", "group": "surface", "default": "#12151c"},
    {"key": "surface", "css": "--jingepi-surface", "label": "表面/主区底", "group": "surface", "default": "#12151c"},
    {"key": "panel", "css": "--jingepi-panel", "label": "面板底", "group": "surface", "default": "#12151c"},
    {"key": "panel_raised", "css": "--jingepi-panel-raised", "label": "抬升面板", "group": "surface", "default": "#12151c"},
    {"key": "input", "css": "--jingepi-input", "label": "输入框底", "group": "surface", "default": "#161a22"},
    {"key": "highlight", "css": "--jingepi-highlight", "label": "高亮/悬停底", "group": "surface", "default": "#241c0e"},
    {"key": "blue", "css": "--jingepi-blue", "label": "氛围蓝（渐变）", "group": "surface", "default": "#172554"},
    # 文字
    {"key": "text", "css": "--jingepi-text", "label": "主文字", "group": "text", "default": "#f5f5f5"},
    {"key": "text_muted", "css": "--jingepi-text-muted", "label": "次要文字", "group": "text", "default": "#aaaaaa"},
    {"key": "gold_on", "css": "--jingepi-gold-on", "label": "按钮内淡黄色文字", "group": "text", "default": "#fff6d1"},
    # 边框
    {"key": "border", "css": "--jingepi-border", "label": "边框", "group": "border", "default": "#2e3440"},
    {"key": "border_strong", "css": "--jingepi-border-strong", "label": "强边框", "group": "border", "default": "#3a4250"},
    # 主按钮
    {"key": "btn", "css": "--jingepi-btn", "label": "主按钮填色", "group": "button", "default": "#e0a80a"},
    {"key": "btn_hover", "css": "--jingepi-btn-hover", "label": "主按钮悬停", "group": "button", "default": "#c99400"},
    {"key": "gold_deep", "css": "--jingepi-gold-deep", "label": "主按钮按下/深金", "group": "button", "default": "#c99400"},
    {"key": "gold_hover", "css": "--jingepi-gold-hover", "label": "描边按钮悬停金", "group": "button", "default": "#d4a017"},
    # 强调色/其它
    {"key": "gold", "css": "--jingepi-gold", "label": "强调金", "group": "accent", "default": "#f0b90b"},
    {"key": "gold_light", "css": "--jingepi-gold-light", "label": "浅金/徽章", "group": "accent", "default": "#fcd535"},
    {"key": "gold_stop4", "css": "--jingepi-gold-stop4", "label": "渐变终点金", "group": "accent", "default": "#a67c00"},
    {"key": "warning", "css": "--jingepi-warning", "label": "警告色", "group": "accent", "default": "#ff4b55"},
]


def default_colors() -> dict[str, str]:
    return {d["key"]: d["default"] for d in COLOR_DEFS}


def normalize_hex(value: str) -> str | None:
    raw = (value or "").strip()
    if not HEX_RE.match(raw):
        return None
    if len(raw) == 4:
        raw = "#" + "".join(c * 2 for c in raw[1:])
    return raw.lower()


def _ensure_dir() -> None:
    os.makedirs(THEME_DIR, exist_ok=True)


def load_colors() -> dict[str, str]:
    """读取 JSON；缺失则用默认并落盘。"""
    colors = default_colors()
    if os.path.isfile(COLORS_JSON):
        try:
            with open(COLORS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                src = data.get("colors") if isinstance(data.get("colors"), dict) else data
                for key, val in src.items():
                    if key not in colors:
                        continue
                    norm = normalize_hex(str(val))
                    if norm:
                        colors[key] = norm
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass
    return colors


def save_colors(colors: dict[str, str]) -> dict[str, str]:
    """校验并写入 JSON，再生成 vars CSS；返回最终颜色表。"""
    merged = default_colors()
    for key, val in (colors or {}).items():
        if key not in merged:
            continue
        norm = normalize_hex(str(val))
        if not norm:
            raise ValueError(f"颜色「{key}」不是有效十六进制（#RRGGBB）")
        merged[key] = norm
    _ensure_dir()
    payload = {"colors": merged}
    tmp = COLORS_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, COLORS_JSON)
    write_vars_css(merged)
    return merged


def reset_colors() -> dict[str, str]:
    return save_colors(default_colors())


def write_vars_css(colors: dict[str, str] | None = None) -> None:
    c = colors or load_colors()
    lines = [
        "/* 金格Pi 主题变量 — 由管理后台生成，请勿手改；改色请用 /jingepi-console */",
        ":root,",
        "html,",
        "body {",
    ]
    for d in COLOR_DEFS:
        lines.append(f"  {d['css']}: {c[d['key']]};")
    lines.extend(
        [
            f"  --accent: {c['btn']};",
            f"  --accent-color: {c['btn']};",
            f"  --primary-color: {c['btn']};",
            f"  --background: {c['surface']};",
            f"  --system: {c['gold']};",
            "}",
            "",
        ]
    )
    _ensure_dir()
    text = "\n".join(lines)
    tmp = VARS_CSS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, VARS_CSS)


def ensure_seeded() -> dict[str, str]:
    """启动时：缺 JSON 或 vars CSS 则按当前默认写入。"""
    colors = load_colors()
    if not os.path.isfile(COLORS_JSON):
        save_colors(colors)
    elif not os.path.isfile(VARS_CSS):
        write_vars_css(colors)
    return colors


def api_payload() -> dict[str, Any]:
    colors = load_colors()
    items = []
    for d in COLOR_DEFS:
        items.append(
            {
                "key": d["key"],
                "label": d["label"],
                "group": d["group"],
                "group_label": GROUP_LABELS.get(d["group"], d["group"]),
                "css": d["css"],
                "value": colors[d["key"]],
                "default": d["default"],
            }
        )
    groups = [
        {"id": gid, "label": label}
        for gid, label in GROUP_LABELS.items()
    ]
    return {
        "success": True,
        "colors": colors,
        "items": items,
        "groups": groups,
        "total": len(items),
    }
