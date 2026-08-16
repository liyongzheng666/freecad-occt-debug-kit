#!/usr/bin/env bash
# 起 凸/凹圆角对照 demo 的 Print viewer。
# 先跑：  python -m agent.demo.convex_concave.demo    （产出 + 网格化 session）
# 再跑本脚本：确保网格化(幂等) + bridge(:7341) + viewer(:5777)，浏览器开 http://127.0.0.1:5777/
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SESS="$REPO/.occ-debug/sessions/cvx-demo"
echo "[cvx-demo] session = $SESS"

if [ ! -f "$SESS/events.ndjson" ]; then
  echo "[cvx-demo] 还没产出 session，先跑： python -m agent.demo.convex_concave.demo" >&2
  exit 1
fi

OCC_DEBUG_MESH_BIN="$REPO/tools/occ-debug-mesh/build/occ-debug-mesh" \
  python3 "$REPO/scripts/occ-mesh-daemon.py" --session "$SESS" --once || true

python3 "$REPO/tools/Print/bridge/bridge.py" --session "$SESS" --port 7341 &
BRIDGE=$!
trap 'kill $BRIDGE 2>/dev/null || true' EXIT
echo "[cvx-demo] bridge pid $BRIDGE (:7341)  →  打开 http://127.0.0.1:5777/  (Ctrl-C 退出)"
( cd "$REPO/tools/Print" && npm run dev )
