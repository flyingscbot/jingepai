#!/usr/bin/env bash
# macOS / Linux 快捷方式：核心逻辑在 start_with_domain.py（跨平台）。
#
# 用法（在仓库根）：
#   ./start_with_domain.sh
#   ./start_with_domain.sh --skip-compose
#   ./start_with_domain.sh --skip-apply
#   ./start_with_domain.sh --no-flask
#
# 或直接：
#   python3 start_with_domain.py
#   python start_with_domain.py

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/venv/bin/python" ]]; then
  PY="$ROOT/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  PY=python
fi

exec "$PY" "$ROOT/start_with_domain.py" "$@"
