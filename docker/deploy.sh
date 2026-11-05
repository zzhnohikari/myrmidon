#!/usr/bin/env bash
# Myrmidon 控制台 —— 一键部署（离线镜像版）
#
#   ./deploy.sh                    # 交互式：建账号 → 启动 → 自检
#   ./deploy.sh --skip-admin       # 账号已建好，只启动
#
# 可用环境变量覆盖：
#   IMAGE      镜像 tag          （默认 myrmidon-console:1.0.0-amd64）
#   DATA_DIR   数据目录          （默认 ./data）
#   PORT      监听端口           （默认 8890，只绑 127.0.0.1）
#   ADMIN_USER 管理员账号        （默认 admin）
#   ADMIN_PASS 管理员密码        （不填则交互输入或随机生成）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${IMAGE:-myrmidon-console:1.0.0-amd64}"
DATA_DIR="${DATA_DIR:-$SCRIPT_DIR/data}"
PORT="${PORT:-8890}"
ADMIN_USER="${ADMIN_USER:-admin}"
SKIP_ADMIN=0
[[ "${1:-}" == "--skip-admin" ]] && SKIP_ADMIN=1

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# ---------- 1. 环境检查 ----------
command -v docker >/dev/null 2>&1 || die "未找到 docker，请先安装 Docker Engine 20.10+"
docker info >/dev/null 2>&1 || die "docker 守护进程不可用（试试 systemctl start docker）"
say "Docker: $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo unknown)"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  TARBALL="$(ls -1 "$SCRIPT_DIR"/镜像/myrmidon-console-*-linux-amd64.tar.gz "$SCRIPT_DIR"/myrmidon-console-*-linux-amd64.tar.gz 2>/dev/null | head -1 || true)"
  [[ -n "${TARBALL:-}" ]] || die "镜像 $IMAGE 不存在，且当前目录找不到 myrmidon-console-*-linux-amd64.tar.gz"
  say "导入镜像：${TARBALL}（约 400MB，首次约 10-30 秒）"
  docker load -i "$TARBALL"
fi

ARCH="$(docker image inspect "$IMAGE" --format '{{.Os}}/{{.Architecture}}' 2>/dev/null || echo '?')"
[[ "$ARCH" == "linux/amd64" ]] || warn "镜像架构是 ${ARCH}，本机是 $(uname -m)；不一致会报 exec format error"
say "镜像: ${IMAGE} (${ARCH})"

# ---------- 2. 数据目录 ----------
mkdir -p "$DATA_DIR/roots"
say "数据目录: ${DATA_DIR}"

# ---------- 3. 管理员账号 ----------
if [[ "$SKIP_ADMIN" == "0" && ! -f "$DATA_DIR/.sapper/users.json" && ! -f "$DATA_DIR/users.json" ]]; then
  if [[ -z "${ADMIN_PASS:-}" ]]; then
    if [[ -t 0 ]]; then
      read -r -s -p "设置管理员密码（回车则随机生成）: " ADMIN_PASS; echo
    fi
  fi
  if [[ -z "${ADMIN_PASS:-}" ]]; then
    ADMIN_PASS="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)"
    warn "已生成随机密码：$ADMIN_PASS   请立即记录并登录后修改"
  fi
  say "创建管理员账号：${ADMIN_USER}"
  docker run --rm --entrypoint python3 -v "$DATA_DIR:/data" "$IMAGE" \
    /app/lib/sapper.py console-user add "$ADMIN_USER" --role admin --password "$ADMIN_PASS" >/dev/null
  say "账号已写入 ${DATA_DIR}/.sapper/users.json"
fi

# ---------- 4. 启动 ----------
docker rm -f myrmidon >/dev/null 2>&1 || true
ENV_ARGS=()
[[ -f "$SCRIPT_DIR/model.env" ]] && ENV_ARGS+=(--env-file "$SCRIPT_DIR/model.env")

say "启动容器（端口 127.0.0.1:${PORT}）"
docker run -d --name myrmidon --restart unless-stopped \
  -p "127.0.0.1:$PORT:8890" \
  -v "$DATA_DIR:/data" \
  "${ENV_ARGS[@]}" \
  -e TZ=Asia/Shanghai \
  "$IMAGE" >/dev/null

# ---------- 5. 自检 ----------
say "等待服务就绪…"
READY=0
for _ in $(seq 1 30); do
  if curl -fsS --noproxy '*' -m 2 "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then READY=1; break; fi
  sleep 1
done
[[ "$READY" == "1" ]] || { docker logs --tail 40 myrmidon; die "服务 30 秒内未就绪，见上方日志"; }

HEALTH="$(curl -fsS --noproxy '*' -m 3 "http://127.0.0.1:$PORT/api/health")"
CODE="$(curl -s --noproxy '*' -m 3 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/api/missions")"
say "健康检查: $HEALTH"
say "未登录访问接口: HTTP ${CODE}（应为 401，说明登录已生效）"
if [[ "$CODE" != "401" ]]; then
  warn "返回 $CODE 说明鉴权没生效，检查 $DATA_DIR/.sapper/users.json 是否存在"
fi

cat <<EOF

部署完成
  控制台   http://127.0.0.1:$PORT
  账号     $ADMIN_USER
  数据目录 $DATA_DIR
  日志     docker logs -f myrmidon

下一步
  1. 登录后到「设置 → 模型网关」填 Base URL / Token，点「拉取模型」
  2. 「设置 → 执行默认参数」设定预算与步数
  3. 新建任务，输入目标，开始执行

常用
  停止   docker stop myrmidon
  启动   docker start myrmidon
  备份   tar czf backup-\$(date +%F).tar.gz -C "$(dirname "$DATA_DIR")" "$(basename "$DATA_DIR")"
EOF
