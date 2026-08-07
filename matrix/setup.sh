#!/usr/bin/env bash
# 金格Pi × 自建 Matrix（Synapse）快速配置脚本
# 适用于：macOS / Linux / Git Bash / WSL
#
# 用法示例：
#   ./setup.sh
#   ./setup.sh --port 1000
#   ./setup.sh --issuer "http://host.docker.internal:1000/"
#   OIDC_ISSUER=http://host.docker.internal:1000/ ./setup.sh
#
# 前置：已安装 Docker，并先启动金格 Flask（默认端口 1000）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SYNAPSE_IMAGE="docker.io/matrixdotorg/synapse:latest"
POSTGRES_IMAGE="docker.io/postgres:16-alpine"
# 优先加速镜像（官方 Docker Hub 在国内常超时）
SYNAPSE_MIRRORS=(
  "hub.rat.dev/matrixdotorg/synapse:latest"
  "docker.1ms.run/matrixdotorg/synapse:latest"
  "docker.m.daocloud.io/docker.io/matrixdotorg/synapse:latest"
)
POSTGRES_MIRRORS=(
  "hub.rat.dev/library/postgres:16-alpine"
  "docker.1ms.run/library/postgres:16-alpine"
  "docker.m.daocloud.io/docker.io/library/postgres:16-alpine"
)
SKIP_OFFICIAL=1
[[ "${DOCKER_TRY_OFFICIAL:-}" == "1" ]] && SKIP_OFFICIAL=0

SERVER_NAME="matrix.localhost"
SIGNING_KEY="data/${SERVER_NAME}.signing.key"
DEFAULT_ISSUER="http://host.docker.internal:1000/"
DEFAULT_PORT="1000"

ISSUER=""
PORT=""

usage() {
  cat <<'EOF'
用法: ./setup.sh [--issuer URL] [--port PORT] [-h|--help]

  --issuer URL   覆盖 homeserver.yaml 中的 OIDC issuer
                 （默认 http://host.docker.internal:1000/）
  --port PORT    按端口生成 issuer：http://host.docker.internal:PORT/
                 （也可用环境变量 JINGEPI_PORT / FLASK_PORT）
  -h, --help     显示帮助

环境变量（可选）：
  OIDC_ISSUER    同 --issuer
  JINGEPI_PORT / FLASK_PORT  同 --port
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --issuer)
      ISSUER="${2:-}"
      shift 2
      ;;
    --port)
      PORT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

# 解析最终 issuer：命令行 > 环境变量 > 默认
if [[ -z "$ISSUER" && -n "${OIDC_ISSUER:-}" ]]; then
  ISSUER="$OIDC_ISSUER"
fi
if [[ -z "$PORT" ]]; then
  PORT="${JINGEPI_PORT:-${FLASK_PORT:-}}"
fi
if [[ -z "$ISSUER" && -n "$PORT" ]]; then
  ISSUER="http://host.docker.internal:${PORT}/"
fi
# 规范化尾部斜杠
if [[ -n "$ISSUER" ]]; then
  ISSUER="${ISSUER%/}/"
fi

log() { echo "[setup] $*"; }
die() { echo "[setup] 错误: $*" >&2; exit 1; }

# ---------- 1. 检查 Docker / Compose ----------
check_docker() {
  command -v docker >/dev/null 2>&1 || die "未找到 docker，请先安装 Docker Desktop 或 Docker Engine"
  docker info >/dev/null 2>&1 || die "Docker 守护进程未运行，请先启动 Docker"
  if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
  else
    die "未找到 docker compose / docker-compose"
  fi
  log "Docker 与 Compose 可用"
}

# Docker Desktop + Git Bash：挂载路径需避免 MSYS 错误转换
docker_data_volume() {
  local data_dir="$SCRIPT_DIR/data"
  if command -v cygpath >/dev/null 2>&1; then
    echo "$(cygpath -w "$data_dir"):/data"
  elif [[ "${OSTYPE:-}" == msys* || "${OSTYPE:-}" == cygwin* || -n "${MSYSTEM:-}" ]]; then
    # Git Bash：用 Windows 盘符路径
    local win
    win="$(cd "$data_dir" && pwd -W 2>/dev/null || true)"
    if [[ -n "$win" ]]; then
      echo "${win}:/data"
    else
      echo "${data_dir}:/data"
    fi
  else
    echo "${data_dir}:/data"
  fi
}

run_docker() {
  if [[ -n "${MSYSTEM:-}" || "${OSTYPE:-}" == msys* ]]; then
    MSYS_NO_PATHCONV=1 docker "$@"
  else
    docker "$@"
  fi
}

# ---------- 2. 创建 data ----------
ensure_data_dir() {
  mkdir -p "$SCRIPT_DIR/data"
  log "已确保目录存在: matrix/data"
}

# ---------- 3. 生成签名密钥等 ----------
needs_generate() {
  [[ ! -f "$SCRIPT_DIR/$SIGNING_KEY" ]]
}

generate_synapse() {
  log "缺少签名密钥，执行 synapse generate …"
  local vol
  vol="$(docker_data_volume)"
  # 优先用已拉取的官方名；若尚未拉取则用镜像名直接跑（generate 会顺带拉）
  local img="$SYNAPSE_IMAGE"
  if ! docker image inspect "$SYNAPSE_IMAGE" >/dev/null 2>&1; then
    # 尝试已 tag 的短名
    if docker image inspect "matrixdotorg/synapse:latest" >/dev/null 2>&1; then
      img="matrixdotorg/synapse:latest"
    fi
  fi
  run_docker run --rm \
    -v "$vol" \
    -e SYNAPSE_SERVER_NAME="$SERVER_NAME" \
    -e SYNAPSE_REPORT_STATS=no \
    "$img" generate
  # compose 挂载仓库根目录 homeserver.yaml（含 OIDC），生成物仅保留密钥/日志配置等
  if [[ ! -f "$SCRIPT_DIR/$SIGNING_KEY" ]]; then
    die "generate 后仍未找到 $SIGNING_KEY"
  fi
  log "签名密钥已生成: $SIGNING_KEY"
}

# ---------- 4. 拉取镜像（官方失败则镜像 + tag） ----------
pull_or_mirror() {
  local official="$1"
  shift
  local mirrors=("$@")
  local short_name="${official#docker.io/}"

  if [[ "$SKIP_OFFICIAL" != "1" ]]; then
    log "拉取镜像: $official"
    if docker pull "$official"; then
      docker tag "$official" "$short_name" 2>/dev/null || true
      return 0
    fi
    log "官方拉取失败，尝试镜像 …"
  else
    log "跳过官方源，直接使用加速镜像 …"
  fi

  local m
  for m in "${mirrors[@]}"; do
    log "尝试: $m"
    if docker pull "$m"; then
      docker tag "$m" "$official"
      docker tag "$m" "$short_name" 2>/dev/null || true
      log "已拉取并 tag 为 $official"
      return 0
    fi
  done
  return 1
}

pull_images() {
  pull_or_mirror "$SYNAPSE_IMAGE" "${SYNAPSE_MIRRORS[@]}" \
    || die "无法拉取 Synapse 镜像（官方与镜像均失败）"
  pull_or_mirror "$POSTGRES_IMAGE" "${POSTGRES_MIRRORS[@]}" \
    || die "无法拉取 Postgres 镜像（官方与镜像均失败）"
  log "镜像就绪"
}

# ---------- 更新 homeserver.yaml issuer ----------
update_issuer() {
  local target="$1"
  local hs="$SCRIPT_DIR/homeserver.yaml"
  [[ -f "$hs" ]] || die "未找到 homeserver.yaml"

  # 仅替换 oidc_providers 段中的 issuer 行（保持简单）
  if grep -qE '^[[:space:]]*issuer:[[:space:]]*"' "$hs"; then
    if [[ "$(uname -s)" == "Darwin" ]]; then
      sed -i '' -E "s|^([[:space:]]*issuer:[[:space:]]*\")[^\"]*(\")|\1${target}\2|" "$hs"
    else
      sed -i -E "s|^([[:space:]]*issuer:[[:space:]]*\")[^\"]*(\")|\1${target}\2|" "$hs"
    fi
    log "已更新 homeserver.yaml issuer → $target"
  else
    die "homeserver.yaml 中未找到 issuer 字段"
  fi
}

# ---------- 5. compose up ----------
compose_up() {
  log "启动 docker compose …"
  "${COMPOSE[@]}" up -d
  log "容器已后台启动"
}

# ---------- 6. 打印说明 ----------
print_summary() {
  local show_issuer="${ISSUER:-}"
  if [[ -z "$show_issuer" ]]; then
    show_issuer="$(grep -E '^[[:space:]]*issuer:' "$SCRIPT_DIR/homeserver.yaml" | head -1 | sed -E 's/.*issuer:[[:space:]]*"([^"]+)".*/\1/')"
  fi
  cat <<EOF

========================================
  Matrix（Synapse）已启动
========================================
  Synapse 地址:  http://localhost:8008

  OIDC Issuer:   ${show_issuer}
  （请先启动金格 Flask，Issuer 需与 OIDC_ISSUER 一致；
   容器访问宿主机用 host.docker.internal，金格本机可用
   http://127.0.0.1:${PORT:-$DEFAULT_PORT} ）

  客户端默认：jingepi-synapse / change-me-synapse-oidc-secret

  Cinny 登录简要步骤：
  1. 打开 http://127.0.0.1:1000/cinny/ （或 /chat）
  2. Homeserver 应为 http://127.0.0.1:1000（已预填）
  3. 选择「金格Pi」OIDC 登录
  4. 在金格授权页输入实训账号完成登录
========================================
EOF
}

# ---------- main ----------
main() {
  check_docker
  ensure_data_dir

  if [[ -n "$ISSUER" ]]; then
    update_issuer "$ISSUER"
  fi

  # 先尽量拉镜像，再 generate（generate 也需要 synapse 镜像）
  pull_images

  if needs_generate; then
    generate_synapse
  else
    log "已存在签名密钥，跳过 generate"
  fi

  compose_up
  print_summary
}

main
