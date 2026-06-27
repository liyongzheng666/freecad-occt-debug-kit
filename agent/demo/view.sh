#!/usr/bin/env bash
# 一键起 wedge-demo 的 Print viewer。
# 先跑：python -m agent.demo.wedge_demo   （产出 session：抓的失败几何 + agent 结论）
# 再跑本脚本：起 daemon(网格化) + bridge(:7341) + viewer(:5777)，浏览器开 http://127.0.0.1:5777/
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export OCC_DEBUG_SESSION="$REPO/.occ-debug/sessions/wedge-demo"
echo "[wedge-demo] session = $OCC_DEBUG_SESSION"

if [ ! -f "$OCC_DEBUG_SESSION/events.ndjson" ]; then
  echo "[wedge-demo] 还没产出 session，先跑： python -m agent.demo.wedge_demo" >&2
  exit 1
fi

"$REPO/scripts/occ-debug-start.sh" start            # daemon 把 assets/*.brep 网格化
python3 "$REPO/tools/Print/bridge/bridge.py" --session "$OCC_DEBUG_SESSION" &
BRIDGE=$!
trap 'kill $BRIDGE 2>/dev/null || true' EXIT
echo "[wedge-demo] bridge pid $BRIDGE (:7341)  →  viewer 起在 :5777"
( cd "$REPO/tools/Print" && npm run dev )            # 前台，Ctrl-C 退出
