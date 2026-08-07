#!/usr/bin/env python3
"""按仓库根 domain.txt（或环境变量）同步穿透根并启动 Matrix + Flask。

跨平台主入口（Windows / macOS / Linux）。PowerShell / bash 脚本仅作薄封装。

用法（在仓库根）：
  python start_with_domain.py
  python3 start_with_domain.py
  python start_with_domain.py --skip-compose   # 只起 Flask（已 compose 过）
  python start_with_domain.py --skip-apply     # 不改 yaml/json，只起服务
  python start_with_domain.py --no-flask       # 只 apply + compose，不起 Flask

改 domain.txt 后：
  - 仅 Flask：python main.py（会轻量同步；配置有变才 recreate）
  - 显式一键含 recreate：本脚本（始终 force-recreate，除非 --skip-compose）

Flask 单独启动也会读 domain.txt（auth_config），不依赖本脚本或 .ps1。
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOMAIN_FILE = ROOT / "domain.txt"
APPLY_SCRIPT = ROOT / "matrix" / "apply_public_base.py"
MAIN_PY = ROOT / "main.py"
MATRIX_DIR = ROOT / "matrix"
_DEFAULT_PUBLIC_BASE = "http://127.0.0.1:1000"


def _load_apply_mod():
    if not APPLY_SCRIPT.is_file():
        raise SystemExit(f"未找到 {APPLY_SCRIPT}")
    spec = importlib.util.spec_from_file_location("apply_public_base", APPLY_SCRIPT)
    if spec is None or spec.loader is None:
        raise SystemExit(f"无法加载 {APPLY_SCRIPT}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
        return s.rstrip("/")
    return ""


def resolve_public_base() -> str:
    raw = (
        (os.environ.get("PUBLIC_BASE_URL") or "").strip()
        or (os.environ.get("OIDC_PUBLIC_BASE") or "").strip()
        or _read_domain_file()
        or _DEFAULT_PUBLIC_BASE
    )
    return raw.rstrip("/")


def find_python() -> str:
    """优先用仓库 venv，否则用当前解释器。"""
    if sys.platform == "win32":
        venv_py = ROOT / "venv" / "Scripts" / "python.exe"
    else:
        venv_py = ROOT / "venv" / "bin" / "python"
    if venv_py.is_file():
        return str(venv_py)
    return sys.executable


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None) -> None:
    print(f"[run] {' '.join(cmd)}")
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env)
    if r.returncode != 0:
        raise SystemExit(f"命令失败 (exit {r.returncode}): {' '.join(cmd)}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="读 domain.txt，同步穿透根，可选启动 compose + Flask"
    )
    p.add_argument(
        "--skip-compose",
        action="store_true",
        help="跳过 docker compose（只起 Flask）",
    )
    p.add_argument(
        "--skip-apply",
        action="store_true",
        help="不改 homeserver.yaml / cinny-config.json",
    )
    p.add_argument(
        "--no-flask",
        action="store_true",
        help="只 apply + compose，不启动 Flask",
    )
    args = p.parse_args(argv)

    apply_mod = _load_apply_mod()
    try:
        base = apply_mod.resolve_public_base()
    except ValueError:
        # 与旧行为兼容：宽松解析，留给 apply 再校验
        base = resolve_public_base()
    print(f"[domain] PUBLIC_BASE_URL = {base}")

    py = find_python()

    if not args.skip_apply:
        print("[apply] sync homeserver.yaml + cinny-config.json ...")
        try:
            apply_mod.apply(base)
        except (OSError, ValueError, RuntimeError) as e:
            raise SystemExit(str(e)) from e

    if not args.skip_compose:
        if not shutil.which("docker"):
            raise SystemExit("未找到 docker，请先安装 Docker Desktop / Docker Engine")
        print("[compose] force-recreate synapse + cinny（改 yaml 后必须 recreate）...")
        run(
            [
                "docker",
                "compose",
                "up",
                "-d",
                "--force-recreate",
                "synapse",
                "cinny",
            ],
            cwd=MATRIX_DIR,
        )

    if not args.no_flask:
        if not MAIN_PY.is_file():
            raise SystemExit(f"未找到 {MAIN_PY}")
        # 显式设环境变量，避免与其它 shell 残留冲突；auth_config 也会读 domain.txt
        env = os.environ.copy()
        env["PUBLIC_BASE_URL"] = base
        print("[flask] 启动 0.0.0.0:1000 （Ctrl+C 结束）...")
        print(f"        自检: {base}/.well-known/matrix/client")
        # 前台阻塞，与原先 .ps1 行为一致
        raise SystemExit(
            subprocess.call([py, str(MAIN_PY)], cwd=str(ROOT), env=env)
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
