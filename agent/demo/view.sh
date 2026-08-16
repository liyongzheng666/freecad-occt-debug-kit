#!/usr/bin/env bash
# 起 wedge-demo 的 Print viewer。
# 先跑：  python -m agent.demo.wedge_demo     （抓失败几何 + 网格化 + agent 结论 → session）
# 再跑本脚本：确保网格化(幂等) + bridge(:7341) + viewer(:5777)，浏览器开 http://127.0.0.1:5777/
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAME="${1:-wedge-demo}"                       # view.sh [session 名]，默认 wedge-demo；凸凹对照用 cvx-demo
SESS="$REPO/.occ-debug/sessions/$NAME"
echo "[demo] session = $SESS"

if [ ! -f "$SESS/events.ndjson" ]; then
  echo "[demo] 还没产出 session '$NAME'，先跑对应 demo（如 python -m agent.demo.convex_concave_demo）" >&2
  exit 1
fi

# 安全网：把所有抓到的 brep 网格化（幂等；已网格化的跳过）——否则 viewer 只见占位框
OCC_DEBUG_MESH_BIN="$REPO/tools/occ-debug-mesh/build/occ-debug-mesh" \
  python3 "$REPO/scripts/occ-mesh-daemon.py" --session "$SESS" --once || true

python3 "$REPO/tools/Print/bridge/bridge.py" --session "$SESS" --port 7341 &
BRIDGE=$!
trap 'kill $BRIDGE 2>/dev/null || true' EXIT
echo "[wedge-demo] bridge pid $BRIDGE (:7341)  →  打开 http://127.0.0.1:5777/  (Ctrl-C 退出)"
( cd "$REPO/tools/Print" && npm run dev )
