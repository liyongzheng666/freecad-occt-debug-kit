"""凸/凹圆角对照 demo —— 把"两面之间的凸圆角 vs 凹圆角"用真实圆角面 + 外法向箭头画进 Print viewer。

跑：  python -m agent.demo.convex_concave.demo
看：  agent/demo/convex_concave/view.sh   （浏览器 http://127.0.0.1:5777/）
说明见同目录 README.md（含第三例"重叠可裁剪"的局限说明）。
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]                                  # agent/demo/convex_concave -> repo
SESSION = REPO / ".occ-debug" / "sessions" / "cvx-demo"
EMIT = HERE / "emit.py"
FREECADCMD = REPO / "FreeCAD" / "build" / "debug" / "bin" / "FreeCADCmd"
MESHER = REPO / "tools" / "occ-debug-mesh" / "build" / "occ-debug-mesh"
DAEMON = REPO / "scripts" / "occ-mesh-daemon.py"


def main() -> int:
    if not FREECADCMD.exists():
        print(f"FreeCADCmd 不在：{FREECADCMD}")
        return 1
    SESSION.mkdir(parents=True, exist_ok=True)
    (SESSION / "assets").mkdir(exist_ok=True)
    (SESSION / "manifest.json").write_text('{"session_id": "cvx-demo"}', encoding="utf-8")

    env = dict(os.environ)
    env["OCC_DEBUG_SESSION"] = str(SESSION)
    env["PYTHONIOENCODING"] = "utf-8"

    print("[cvx] emit convex+concave geometry via FreeCADCmd ...")
    r = subprocess.run([str(FREECADCMD), str(EMIT)], env=env, capture_output=True, text=True, timeout=180)
    tail = [ln for ln in r.stdout.splitlines() if "cvx-concave" in ln] or [r.stdout.strip()[-160:]]
    print("[cvx]", tail[-1])

    if MESHER.exists() and DAEMON.exists():
        env["OCC_DEBUG_MESH_BIN"] = str(MESHER)
        m = subprocess.run(["python3", str(DAEMON), "--session", str(SESSION), "--once"],
                           env=env, capture_output=True, text=True, timeout=180)
        print("[cvx] mesh:", (m.stdout.strip().splitlines() or ["?"])[-1])
    else:
        print("[cvx] 跳过网格化（occ-debug-mesh/daemon 不在）——viewer 只会显示占位框")

    print(
        "\n──────── 看凸/凹对照 ────────\n"
        "  agent/demo/convex_concave/view.sh     # 一键：网格化 + bridge + viewer\n"
        "  浏览器 http://127.0.0.1:5777/\n"
        "  橙=真实圆角面 / 红=OCCT放弃(重叠可裁剪)；黄箭头岔开=凸 / 对冲指向缺口=凹\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
