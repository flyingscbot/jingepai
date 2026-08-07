#!/usr/bin/env python3
"""按 PUBLIC_BASE_URL（穿透/公网根）同步改 Synapse + FluffyChat 配置。

用法（优先级：命令行参数 > 环境变量 > 仓库根 domain.txt）：
  python matrix/apply_public_base.py
  python matrix/apply_public_base.py https://xxxx.ngrok-free.app

  或：
  export PUBLIC_BASE_URL=https://xxxx.ngrok-free.app   # bash
  set PUBLIC_BASE_URL=https://xxxx.ngrok-free.app      # cmd
  python matrix/apply_public_base.py

会改：
  - matrix/homeserver.yaml → public_baseurl、authorization_endpoint
  - matrix/fluffychat-config.json → defaultHomeserver（完整 PUBLIC_BASE_URL）

不会改 OIDC issuer / token / jwks（仍为 host.docker.internal，供容器内访问）。

改完后务必 recreate（仅 restart 不够，Synapse 启动时读 yaml）：
  cd matrix
  docker compose up -d --force-recreate synapse fluffychat

Flask 侧：写好仓库根 domain.txt 后重启即可（或设 PUBLIC_BASE_URL）。
一键（跨平台）：python start_with_domain.py
  Windows 也可：.\\start_with_domain.ps1
  macOS/Linux 也可：./start_with_domain.sh

也可由 main.py 启动时轻量同步（有变化才 recreate）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
DOMAIN_FILE = REPO / "domain.txt"
HS = ROOT / "homeserver.yaml"
FLUFFY_CFG = ROOT / "fluffychat-config.json"
_DEFAULT_PUBLIC_BASE = "http://127.0.0.1:1000"


def _read_domain_file() -> str:
    if not DOMAIN_FILE.is_file():
        return ""
    try:
        text = DOMAIN_FILE.read_text(encoding="utf-8-sig")
    except OSError:
        return ""
    for line in text.splitlines():
        s = line.strip().lstrip("\ufeff")
        if not s or s.startswith("#"):
            continue
        return s.strip().rstrip("/")
    return ""


def _norm_base(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        raise ValueError("PUBLIC_BASE_URL 为空")
    if "://" not in u:
        raise ValueError(f"需要完整 URL（含 https:// 或 http://）: {url!r}")
    p = urlparse(u)
    if p.path and p.path not in ("", "/"):
        raise ValueError(
            f"请只填穿透根地址，不要带路径（不要 /fluffychat、/_matrix）：{url!r}"
        )
    return f"{p.scheme}://{p.netloc}"


def resolve_public_base(
    *,
    cli: str | None = None,
    default: str = _DEFAULT_PUBLIC_BASE,
) -> str:
    """优先级：cli > PUBLIC_BASE_URL > OIDC_PUBLIC_BASE > domain.txt > default。"""
    raw = (
        (cli or "").strip()
        or (os.environ.get("PUBLIC_BASE_URL") or "").strip()
        or (os.environ.get("OIDC_PUBLIC_BASE") or "").strip()
        or _read_domain_file()
        or default
    )
    return _norm_base(raw)


def _fluffy_homeserver_from_cfg(data: dict) -> str | None:
    raw = data.get("defaultHomeserver")
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip().rstrip("/")
    if "://" in raw:
        try:
            return _norm_base(raw)
        except ValueError:
            return raw
    return None


def read_current_bases() -> tuple[str | None, str | None]:
    """读当前配置中的 (homeserver public_baseurl, fluffychat defaultHomeserver)，无尾斜杠。"""
    hs_base: str | None = None
    fluffy_base: str | None = None
    if HS.is_file():
        text = HS.read_text(encoding="utf-8")
        m = re.search(r'(?m)^public_baseurl:\s*"([^"]*)"', text)
        if m:
            hs_base = m.group(1).rstrip("/")
    if FLUFFY_CFG.is_file():
        try:
            data = json.loads(FLUFFY_CFG.read_text(encoding="utf-8"))
            fluffy_base = _fluffy_homeserver_from_cfg(data)
        except (OSError, json.JSONDecodeError, TypeError):
            fluffy_base = None
    return hs_base, fluffy_base


def bases_need_update(base: str) -> bool:
    """目标 base 与 yaml/json 是否不一致。"""
    target = _norm_base(base)
    hs_base, fluffy_base = read_current_bases()
    return hs_base != target or fluffy_base != target


def patch_homeserver(base: str) -> None:
    text = HS.read_text(encoding="utf-8")
    pub = base + "/"
    auth = base + "/oauth/authorize"
    text2, n1 = re.subn(
        r'(?m)^(public_baseurl:\s*")[^"]*(")',
        rf"\g<1>{pub}\2",
        text,
        count=1,
    )
    text2, n2 = re.subn(
        r'(?m)^(\s*authorization_endpoint:\s*")[^"]*(")',
        rf"\g<1>{auth}\2",
        text2,
        count=1,
    )
    if n1 != 1 or n2 != 1:
        raise RuntimeError(
            f"homeserver.yaml 替换失败（public_baseurl={n1}, authorization_endpoint={n2}）"
        )
    HS.write_text(text2, encoding="utf-8", newline="\n")
    print(f"[ok] {HS.name}: public_baseurl -> {pub}")
    print(f"[ok] {HS.name}: authorization_endpoint -> {auth}")


def patch_fluffychat_config(base: str) -> None:
    data = json.loads(FLUFFY_CFG.read_text(encoding="utf-8"))
    data["defaultHomeserver"] = base
    data.setdefault("applicationName", "金格Pi聊天室")
    data.setdefault("welcomeText", "金格Pi · FluffyChat")
    data.setdefault("colorSchemeSeedInt", 4293966091)
    FLUFFY_CFG.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"[ok] {FLUFFY_CFG.name}: defaultHomeserver -> {base}")


def apply(base: str) -> str:
    """写入 homeserver.yaml + fluffychat-config.json，返回规范化后的 base。"""
    base = _norm_base(base)
    if not HS.is_file():
        raise FileNotFoundError(f"未找到 {HS}")
    if not FLUFFY_CFG.is_file():
        raise FileNotFoundError(f"未找到 {FLUFFY_CFG}")
    patch_homeserver(base)
    patch_fluffychat_config(base)
    return base


def try_recreate_synapse_fluffychat(*, quiet_fail: bool = True) -> bool:
    """docker compose force-recreate synapse + fluffychat。成功 True，失败 False。"""
    if not shutil.which("docker"):
        msg = (
            "[domain] 未找到 docker，无法自动 recreate。"
            "请手动执行：cd matrix && docker compose up -d --force-recreate synapse fluffychat"
        )
        print(msg)
        return False
    cmd = [
        "docker",
        "compose",
        "up",
        "-d",
        "--force-recreate",
        "synapse",
        "fluffychat",
    ]
    print(f"[compose] {' '.join(cmd)}")
    try:
        r = subprocess.run(cmd, cwd=str(ROOT))
    except OSError as e:
        print(f"[domain] docker compose 执行失败: {e}")
        if quiet_fail:
            print(
                "请手动执行：cd matrix && docker compose up -d --force-recreate synapse fluffychat"
            )
            return False
        raise
    if r.returncode != 0:
        print(
            f"[domain] docker compose 失败 (exit {r.returncode})。"
            "请手动执行：cd matrix && docker compose up -d --force-recreate synapse cinny"
        )
        return False
    return True


# 旧名兼容（若外部脚本仍调用）
try_recreate_synapse_cinny = try_recreate_synapse_fluffychat
try_recreate_synapse_element = try_recreate_synapse_fluffychat


def sync_for_flask_start(*, recreate_on_change: bool = True) -> str:
    """main.py 启动用：解析穿透根、必要时写配置并 recreate。

    - 保证 os.environ['PUBLIC_BASE_URL'] 与解析结果一致（供本进程后续逻辑）
    - 仅当 yaml/json 相对目标有变化时才 apply；变化且 recreate_on_change 时才 compose recreate
    - 无 domain.txt / 环境变量时回退 127.0.0.1:1000（与现行为一致）

    注意：仓库根 domain.txt 优先于本进程里先前注入的 PUBLIC_BASE_URL。
    Flask --reload 会继承旧环境变量；若仍让 env 压过 domain.txt，改穿透根永不生效。

    返回规范化后的 PUBLIC_BASE_URL。
    """
    domain = _read_domain_file()
    if domain:
        base = _norm_base(domain)
    else:
        base = resolve_public_base()
    os.environ["PUBLIC_BASE_URL"] = base

    hs_base, fluffy_base = read_current_bases()
    changed = hs_base != base or fluffy_base != base

    if not changed:
        print(f"[domain] PUBLIC_BASE_URL = {base}（配置未变，跳过 apply / recreate）")
        return base

    print(f"[domain] PUBLIC_BASE_URL = {base}")
    print(
        f"[domain] 检测到配置变化（homeserver={hs_base!r}, fluffychat={fluffy_base!r}）→ 同步 yaml/json"
    )
    try:
        apply(base)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as e:
        print(f"[domain] 同步配置失败: {e}")
        return base

    if recreate_on_change:
        print("[domain] 正在 recreate synapse + fluffychat（改 yaml/json 后必须 recreate）...")
        try_recreate_synapse_fluffychat(quiet_fail=True)
    else:
        print(
            "[domain] 已写入配置但未 recreate。"
            "请手动：cd matrix && docker compose up -d --force-recreate synapse fluffychat"
        )
    return base


def main(argv: list[str]) -> int:
    raw = (
        (argv[1] if len(argv) > 1 else "")
        or os.environ.get("PUBLIC_BASE_URL")
        or os.environ.get("OIDC_PUBLIC_BASE")
        or _read_domain_file()
        or ""
    )
    if not raw:
        print(
            "用法: python matrix/apply_public_base.py [<穿透根URL>]\n"
            "  或写仓库根 domain.txt（见 domain.txt.example）\n"
            "  或设环境变量 PUBLIC_BASE_URL\n"
            "例: python matrix/apply_public_base.py https://xxxx.ngrok-free.app",
            file=sys.stderr,
        )
        return 2
    try:
        base = apply(raw)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print()
    print("下一步：")
    print(f"  1) 确认仓库根 domain.txt 为：{base}  （Flask 启动会读）")
    print("  2) 重启 Flask（须监听 0.0.0.0:1000）")
    print("  3) cd matrix && docker compose up -d --force-recreate synapse fluffychat")
    print("     （改 homeserver.yaml 后必须 --force-recreate，restart 不够）")
    print(f"  4) 客户端 Homeserver URL 填：{base}")
    print(f"  5) 自检：GET {base}/.well-known/matrix/client")
    print("  或一键：python start_with_domain.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
