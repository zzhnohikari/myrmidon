#!/bin/bash
# 控制台容器入口：环境校验 → 账号提示 → 启动 console
set -euo pipefail

DATA="${SAPPER_DATA:-/data}"
ROOTS="${SAPPER_ROOTS:-$DATA/roots}"
PORT="${SAPPER_PORT:-8890}"
USERS="${SAPPER_USERS:-$DATA/users.json}"
ENGINES="${SAPPER_ENGINES:-$DATA/engines.json}"

mkdir -p "$ROOTS" "$DATA/.sapper"

# console-user 的默认落点是 $HOME/.sapper/users.json（镜像里即 $DATA/.sapper/）。
# 两条路径都认，避免"账号建了但控制台还是开放模式"的静默失效。
if [[ ! -f "$USERS" && -f "$DATA/.sapper/users.json" ]]; then
  USERS="$DATA/.sapper/users.json"
fi

echo "[console] data   = $DATA"
echo "[console] roots  = $ROOTS"
echo "[console] port   = $PORT"

if [[ -f "$USERS" ]]; then
  echo "[console] auth   = 已启用（$USERS）"
else
  echo "[console] auth   = ⚠️  未配置 $USERS —— 任何能访问该端口的人都能操作控制台"
  echo "[console]          生成账号: sapper console-user add admin --password '<强密码>' --file $USERS"
fi

ARGS=(console --root "$ROOTS" --host 0.0.0.0 --port "$PORT")
[[ -f "$USERS" ]] && ARGS+=(--users "$USERS")
[[ -f "$ENGINES" ]] && ARGS+=(--engines "$ENGINES")

if [[ -z "${ANTHROPIC_BASE_URL:-}" || -z "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
  echo "[console] 提示: 未设置 ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN，"
  echo "[console]       Auto/跑分会用容器内 ~/.claude/settings.json（若存在）否则失败。"
fi

exec python3 /app/lib/sapper.py "${ARGS[@]}"
