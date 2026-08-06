"""Matrix / Element 主题色管理：JSON 持久化 + 生成 jingepi-theme-vars.css。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

ROOT = os.path.dirname(os.path.abspath(__file__))
ELEMENT_STATIC = os.path.join(ROOT, "matrix", "element-static")
COLORS_JSON = os.path.join(ELEMENT_STATIC, "jingepi-theme-colors.json")
VARS_CSS = os.path.join(ELEMENT_STATIC, "jingepi-theme-vars.css")
ELEMENT_CONFIG = os.path.join(ROOT, "matrix", "element-config.json")

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
    os.makedirs(ELEMENT_STATIC, exist_ok=True)


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
    _maybe_patch_element_config(merged)
    return merged


def reset_colors() -> dict[str, str]:
    return save_colors(default_colors())


def write_vars_css(colors: dict[str, str] | None = None) -> None:
    c = colors or load_colors()
    lines = [
        "/* 金格Pi Element 主题变量 — 由管理后台生成，请勿手改；改色请用 /jingepi-console */",
        ":root,",
        "html,",
        "body,",
        ".cpd-theme-dark,",
        ".cpd-theme-light,",
        '[class*="cpd-theme-"] {',
    ]
    for d in COLOR_DEFS:
        lines.append(f"  {d['css']}: {c[d['key']]};")
    # 同步常用 accent / Compound 入口，便于先于 lab CSS 生效
    lines.extend(
        [
            f"  --accent: {c['btn']};",
            f"  --accent-color: {c['btn']};",
            f"  --primary-color: {c['btn']};",
            f"  --secondary-content: {c['gold_deep']};",
            f"  --tertiary-content: {c['gold_light']};",
            f"  --background: {c['surface']};",
            f"  --system: {c['gold']};",
            f"  --cpd-color-bg-action-primary-rest: {c['btn']};",
            f"  --cpd-color-bg-action-primary-hovered: {c['btn_hover']};",
            f"  --cpd-color-bg-action-primary-pressed: {c['gold_deep']};",
            f"  --cpd-color-bg-accent-rest: {c['btn']};",
            f"  --cpd-color-bg-accent-hovered: {c['btn_hover']};",
            f"  --cpd-color-bg-accent-pressed: {c['gold_deep']};",
            f"  --cpd-color-text-on-solid-primary: {c['gold_on']};",
            f"  --cpd-color-icon-on-solid-primary: {c['gold_on']};",
            f"  --cpd-color-gradient-action-stop1: {c['btn']};",
            f"  --cpd-color-gradient-action-stop2: {c['btn_hover']};",
            f"  --cpd-color-gradient-action-stop3: {c['gold_deep']};",
            f"  --cpd-color-gradient-action-stop4: {c['gold_stop4']};",
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


def _maybe_patch_element_config(colors: dict[str, str]) -> None:
    """尽力同步 element-config.json 自定义主题关键色（热更新弱，硬刷新后生效）。"""
    if not os.path.isfile(ELEMENT_CONFIG):
        return
    try:
        with open(ELEMENT_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        themes = (
            cfg.get("setting_defaults", {})
            .get("custom_themes", [])
        )
        if not themes:
            return
        theme = themes[0]
        cols = theme.setdefault("colors", {})
        cols["accent-color"] = colors["btn"]
        cols["accent"] = colors["btn"]
        cols["primary-color"] = colors["btn"]
        cols["warning-color"] = colors["warning"]
        cols["sidebar-color"] = colors["surface"]
        cols["roomlist-background-color"] = colors["surface"]
        cols["roomlist-text-color"] = colors["text"]
        cols["roomlist-text-secondary-color"] = colors["text_muted"]
        cols["roomlist-highlights-color"] = colors["highlight"]
        cols["timeline-background-color"] = colors["surface"]
        cols["timeline-text-color"] = colors["text"]
        cols["timeline-text-secondary-color"] = colors["text_muted"]
        cols["timeline-highlights-color"] = colors["highlight"]
        cols["secondary-content"] = colors["gold_deep"]
        cols["tertiary-content"] = colors["gold_light"]
        cols["system"] = colors["gold"]
        compound = theme.setdefault("compound", {})
        for k in (
            "--cpd-color-bg-canvas-default",
            "--cpd-color-bg-canvas-disabled",
            "--cpd-color-bg-subtle-primary",
            "--cpd-color-bg-subtle-secondary",
            "--cpd-color-bg-subtle-tertiary",
            "--cpd-color-bg-canvas-default-level-1",
            "--cpd-color-bg-subtle-secondary-level-0",
            "--cpd-color-gradient-info-stop2",
        ):
            compound[k] = colors["surface"]
        compound["--cpd-color-text-primary"] = colors["text"]
        compound["--cpd-color-text-secondary"] = colors["text_muted"]
        compound["--cpd-color-text-action-accent"] = colors["gold"]
        compound["--cpd-color-text-link-external"] = colors["gold_light"]
        compound["--cpd-color-text-on-solid-primary"] = colors["gold_on"]
        compound["--cpd-color-text-badge-accent"] = colors["gold_on"]
        compound["--cpd-color-text-critical-primary"] = colors["warning"]
        compound["--cpd-color-icon-primary"] = colors["text"]
        compound["--cpd-color-icon-secondary"] = colors["text_muted"]
        compound["--cpd-color-icon-accent-tertiary"] = colors["gold"]
        compound["--cpd-color-icon-accent-primary"] = colors["gold"]
        compound["--cpd-color-icon-on-solid-primary"] = colors["gold_on"]
        compound["--cpd-color-icon-critical-primary"] = colors["warning"]
        compound["--cpd-color-bg-action-primary-rest"] = colors["btn"]
        compound["--cpd-color-bg-action-primary-hovered"] = colors["btn_hover"]
        compound["--cpd-color-bg-action-primary-pressed"] = colors["gold_deep"]
        compound["--cpd-color-bg-action-secondary-rest"] = colors["input"]
        compound["--cpd-color-bg-action-secondary-pressed"] = colors["highlight"]
        compound["--cpd-color-bg-accent-rest"] = colors["btn"]
        compound["--cpd-color-bg-accent-hovered"] = colors["btn_hover"]
        compound["--cpd-color-bg-accent-pressed"] = colors["gold_deep"]
        compound["--cpd-color-bg-badge-accent"] = colors["gold_light"]
        compound["--cpd-color-bg-badge-default"] = colors["input"]
        compound["--cpd-color-bg-badge-primary"] = colors["gold"]
        compound["--cpd-color-bg-badge-secondary"] = colors["border"]
        compound["--cpd-color-border-accent-primary"] = colors["gold"]
        compound["--cpd-color-border-accent-subtle"] = colors["gold_deep"]
        compound["--cpd-color-border-focused"] = colors["gold"]
        compound["--cpd-color-border-interactive-primary"] = colors["border_strong"]
        compound["--cpd-color-border-interactive-secondary"] = colors["border"]
        compound["--cpd-color-border-interactive-hovered"] = colors["gold_deep"]
        compound["--cpd-color-border-disabled"] = colors["border"]
        compound["--cpd-color-gradient-action-stop1"] = colors["btn"]
        compound["--cpd-color-gradient-action-stop2"] = colors["btn_hover"]
        compound["--cpd-color-gradient-action-stop3"] = colors["gold_deep"]
        compound["--cpd-color-gradient-action-stop4"] = colors["gold_stop4"]
        tmp = ELEMENT_CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, ELEMENT_CONFIG)
    except (OSError, json.JSONDecodeError, TypeError, KeyError, IndexError):
        pass


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
